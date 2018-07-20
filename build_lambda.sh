#!/usr/bin/env bash

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

lambda_output_file=/opt/app/build/lambda.zip

set -e

yum update -y
yum install -y cpio python zip wget 
curl -O https://bootstrap.pypa.io/get-pip.py
python get-pip.py
pip install --no-cache-dir virtualenv
virtualenv env
. env/bin/activate
pip install --no-cache-dir -r requirements.txt
python --version 

pushd /tmp
wget http://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
rpm -ivh epel-release-latest-7.noarch.rpm
yum -y update
yum clean all
yum install -y clamav clamav-lib clamav-update
#rpm -qa
wget http://dl.fedoraproject.org/pub/epel/7/x86_64/Packages/c/clamav-0.100.0-2.el7.x86_64.rpm
wget http://dl.fedoraproject.org/pub/epel/7/x86_64/Packages/c/clamav-lib-0.100.0-2.el7.x86_64.rpm
wget http://dl.fedoraproject.org/pub/epel/7/x86_64/Packages/c/clamav-update-0.100.0-2.el7.x86_64.rpm
wget https://rpmfind.net/linux/centos/7.5.1804/os/x86_64/Packages/json-c-0.11-4.el7_0.i686.rpm
wget https://rpmfind.net/linux/centos/7.5.1804/os/x86_64/Packages/pcre2-10.23-2.el7.x86_64.rpm
rpm2cpio clamav-0.100.0-2.el7.x86_64.rpm | cpio -idmv
rpm2cpio clamav-lib-0.100.0-2.el7.x86_64.rpm | cpio -idmv
rpm2cpio clamav-update-0.100.0-2.el7.x86_64.rpm | cpio -idmv
rpm2cpio json-c-0.11-4.el7_0.i686.rpm | cpio -idmv
popd
mkdir -p bin
cp /tmp/usr/bin/clamscan /tmp/usr/bin/freshclam /tmp/usr/lib64/* bin/.
echo "DatabaseMirror database.clamav.net" > bin/freshclam.conf

mkdir -p build
zip -r9 $lambda_output_file *.py bin
cd env/lib/python2.7/site-packages
zip -r9 $lambda_output_file *
