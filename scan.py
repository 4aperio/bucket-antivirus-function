# Upside Travel, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import boto3
import clamav
import copy
import json
import metrics
import urllib
import os
from urllib.parse import urlparse
from common import *
from datetime import datetime
from distutils.util import strtobool

ENV = os.getenv("ENV", "")


def event_object(event):
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    if (not bucket) or (not key):
        print("Unable to retrieve object from event.\n%s" % event)
        raise Exception("Unable to retrieve object from event.")
    return s3.Object(bucket, key)

def verify_s3_object_version(s3_object):
    # validate that we only process the original version of a file, if asked to do so
    # security check to disallow processing of a new (possibly infected) object version
    # while a clean initial version is getting processed
    # downstream services may consume latest version by mistake and get the infected version instead
    if str_to_bool(AV_PROCESS_ORIGINAL_VERSION_ONLY):
        bucketVersioning = s3.BucketVersioning(s3_object.bucket_name)
        if (bucketVersioning.status == "Enabled"):
            bucket = s3.Bucket(s3_object.bucket_name)
            versions = list(bucket.object_versions.filter(Prefix=s3_object.key))
            if len(versions) > 1:
                print("Detected multiple object versions in %s.%s, aborting processing" % (s3_object.bucket_name, s3_object.key))
                raise Exception("Detected multiple object versions in %s.%s, aborting processing" % (s3_object.bucket_name, s3_object.key))
            else:
                print("Detected only 1 object version in %s.%s, proceeding with processing" % (s3_object.bucket_name, s3_object.key))
        else:
            # misconfigured bucket, left with no or suspended versioning
            print("Unable to implement check for original version, as versioning is not enabled in bucket %s" % s3_object.bucket_name)
            raise Exception("Object versioning is not enabled in bucket %s" % s3_object.bucket_name)

def download_s3_object(s3_object, local_prefix):
    local_path = "%s/%s/%s" % (local_prefix, s3_object.bucket_name, s3_object.key)
    create_dir(os.path.dirname(local_path))
    s3_object.download_file(local_path)
    return local_path


def set_av_metadata(s3_object, result):
    content_type = s3_object.content_type
    metadata = s3_object.metadata
    metadata[AV_STATUS_METADATA] = result
    metadata[AV_TIMESTAMP_METADATA] = datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
    s3_object.copy(
        {
            'Bucket': s3_object.bucket_name,
            'Key': s3_object.key
        },
        ExtraArgs={
            "ContentType": content_type,
            "Metadata": metadata,
            "MetadataDirective": "REPLACE"
        }
    )


def set_av_tags(s3_object, result):
    curr_tags = s3_client.get_object_tagging(Bucket=s3_object.bucket_name, Key=s3_object.key)["TagSet"]
    new_tags = copy.copy(curr_tags)
    for tag in curr_tags:
        if tag["Key"] in [AV_STATUS_METADATA, AV_TIMESTAMP_METADATA]:
            new_tags.remove(tag)
    new_tags.append({"Key": AV_STATUS_METADATA, "Value": result})
    new_tags.append({"Key": AV_TIMESTAMP_METADATA, "Value": datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")})
    s3_client.put_object_tagging(
        Bucket=s3_object.bucket_name,
        Key=s3_object.key,
        Tagging={"TagSet": new_tags}
    )

def del_infected_file(s3_object, result):
    if result is "INFECTED":
        s3_client.delete_object(
            Bucket=s3_object.bucket_name,
            Key=s3_object.key
        )
        print("Alert: File deleted due to infection!")


def sns_start_scan(s3_object):
    if AV_SCAN_START_SNS_ARN is None:
        return
    message = {
        "bucket": s3_object.bucket_name,
        "key": s3_object.key,
        "version": s3_object.version_id,
        AV_SCAN_START_METADATA: True,
        AV_TIMESTAMP_METADATA: datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
    }
    sns_client = boto3.client("sns")
    sns_client.publish(
        TargetArn=AV_SCAN_START_SNS_ARN,
        Message=json.dumps({'default': json.dumps(message)}),
        MessageStructure="json"
    )

def sns_scan_results(s3_object, result):
    if AV_STATUS_SNS_ARN is None:
        return
    message = {
        "bucket": s3_object.bucket_name,
        "key": s3_object.key,
        "version": s3_object.version_id,
        AV_STATUS_METADATA: result,
        AV_TIMESTAMP_METADATA: datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
    }
    sns_client = boto3.client("sns")
    sns_client.publish(
        TargetArn=AV_STATUS_SNS_ARN,
        Message=json.dumps({'default': json.dumps(message)}),
        MessageStructure="json"
    )


def lambda_handler(event, context):
    start_time = datetime.utcnow()
    print("Script starting at %s\n" %
          (start_time.strftime("%Y/%m/%d %H:%M:%S UTC")))
    s3_object = event_object(event)
    verify_s3_object_version(s3_object)
    sns_start_scan(s3_object)
    file_path = download_s3_object(s3_object, "/tmp")
    clamav.update_defs_from_s3(AV_DEFINITION_S3_BUCKET, AV_DEFINITION_S3_PREFIX)
    #print(file_path)
    scan_result = clamav.scan_file(file_path)
    print("Scan of s3://%s resulted in %s\n" % (os.path.join(s3_object.bucket_name, s3_object.key), scan_result))
    if "AV_UPDATE_METADATA" in os.environ:
        set_av_metadata(s3_object, scan_result)
    set_av_tags(s3_object, scan_result)
    del_infected_file(s3_object, scan_result)
    sns_scan_results(s3_object, scan_result)
    metrics.send(env=ENV, bucket=s3_object.bucket_name, key=s3_object.key, status=scan_result)
    # Delete downloaded file to free up room on re-usable lambda function container
    try:
        os.remove(file_path)
    except OSError:
        pass
    print("Script finished at %s\n" %
          datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC"))

def str_to_bool(s):
    return bool(strtobool(str(s)))
