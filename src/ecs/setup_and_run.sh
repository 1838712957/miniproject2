#!/bin/bash
# ============================================================================
# Alibaba Cloud ECS launcher for Mini-Project 2
# Runs Hadoop MapReduce + Ray on a single ECS instance, then auto-cleans up.
# ============================================================================
# Prerequisites:
#   - aliyun CLI installed and configured (aliyun configure)
#   - ECs key pair created in the target region
#   - Dataset already uploaded to OSS (python 01_upload_oss.py)
# ============================================================================

set -euo pipefail

REGION="cn-beijing"
ZONE="${REGION}-a"
IMAGE_ID="ubuntu_22_04_x64_20G_alibase_20250214.vhd"
INSTANCE_TYPE="ecs.c7.large"                     # 2 vCPU, 4 GB RAM
SYSTEM_DISK_SIZE=40                               # GB
BUCKET="comp3006j-mp2-iot-logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ---- Config ----
KEY_NAME="${ALIBABA_KEY_NAME:-}"                  # required
SECURITY_GROUP="${ALIBABA_SG:-}"                  # required
VSWITCH="${ALIBABA_VSWITCH:-}"                    # required

echo "=============================================="
echo " Mini-Project 2: ECS Hadoop + Ray Pipeline"
echo " Region:  $REGION"
echo "=============================================="

# ---- Validate inputs ----
if [ -z "$KEY_NAME" ] || [ -z "$SECURITY_GROUP" ] || [ -z "$VSWITCH" ]; then
    echo ""
    echo "ERROR: Set the following environment variables:"
    echo "  export ALIBABA_KEY_NAME=\"your-key-pair-name\""
    echo "  export ALIBABA_SG=\"sg-xxxxxxxxxxxx\""
    echo "  export ALIBABA_VSWITCH=\"vsw-xxxxxxxxxxxx\""
    exit 1
fi

# ---- Step 0: Upload mapper/reducer scripts to OSS ----
echo ""
echo "[0/5] Uploading mapper/reducer scripts to OSS..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
pip install oss2 -q 2>/dev/null || true

python3 -c "
import os, oss2
auth = oss2.Auth(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
                  os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])
bucket = oss2.Bucket(auth, 'oss-$REGION.aliyuncs.com', '$BUCKET')

# Upload mapper/reducer files
for f in ['mapper1.py','reducer1.py','mapper2.py','reducer2.py','mapper3.py','reducer3.py']:
    local = os.path.join('${SCRIPT_DIR}/../mapreduce', f)
    bucket.put_object_from_file(f'scripts/{f}', local)
    print(f'  Uploaded scripts/{f}')

# Upload Ray script
bucket.put_object_from_file('scripts/abnormal_detection_ray.py',
    '${SCRIPT_DIR}/../ray/abnormal_detection.py')
print('  Uploaded scripts/abnormal_detection_ray.py')
"

# ---- Step 1: Launch ECS instance ----
echo ""
echo "[1/5] Launching ECS instance..."

# Create the instance with user-data that pre-installs dependencies
INSTANCE_ID=$(aliyun ecs RunInstances \
    --RegionId "$REGION" \
    --ZoneId "$ZONE" \
    --ImageId "$IMAGE_ID" \
    --InstanceType "$INSTANCE_TYPE" \
    --KeyPairName "$KEY_NAME" \
    --SecurityGroupId "$SECURITY_GROUP" \
    --VSwitchId "$VSWITCH" \
    --SystemDisk.Category cloud_essd \
    --SystemDisk.Size $SYSTEM_DISK_SIZE \
    --InstanceName "comp3006j-mp2-${TIMESTAMP}" \
    --InternetMaxBandwidthOut 10 \
    --InternetChargeType PayByTraffic \
    --Amount 1 \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['InstanceIdSets']['InstanceIdSet'][0])")

echo "  Instance ID: ${INSTANCE_ID}"

# Wait for running
echo "  Waiting for instance to start..."
aliyun ecs WaitInstanceReady --InstanceId "$INSTANCE_ID" --RegionId "$REGION" 2>/dev/null || sleep 30

# Get public IP
PUBLIC_IP=$(aliyun ecs DescribeInstanceAttribute \
    --InstanceId "$INSTANCE_ID" --RegionId "$REGION" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('PublicIpAddress',{}).get('IpAddress',[''])[0])")

echo "  Public IP: ${PUBLIC_IP}"

# ---- Step 2: Wait for SSH ----
echo ""
echo "[2/5] Waiting for SSH..."
for i in $(seq 1 30); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
           "ubuntu@${PUBLIC_IP}" "echo ok" 2>/dev/null; then
        break
    fi
    sleep 5
done

# ---- Step 3: Setup environment on ECS ----
echo ""
echo "[3/5] Installing Java, Hadoop, Ray on ECS..."

ssh -o StrictHostKeyChecking=no "ubuntu@${PUBLIC_IP}" << 'REMOTE_SETUP'
set -e
echo "  [3.1] Updating packages..."
sudo apt-get update -qq

echo "  [3.2] Installing Java 8..."
sudo apt-get install -y -qq openjdk-8-jdk
java -version 2>&1 | head -1

echo "  [3.3] Installing Hadoop 3.3.6..."
wget -q https://dlcdn.apache.org/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz
tar xzf hadoop-3.3.6.tar.gz
sudo mv hadoop-3.3.6 /opt/hadoop
rm hadoop-3.3.6.tar.gz

# Configure Hadoop environment
export HADOOP_HOME=/opt/hadoop
export PATH=$HADOOP_HOME/bin:$PATH
echo 'export HADOOP_HOME=/opt/hadoop' >> ~/.bashrc
echo 'export PATH=$HADOOP_HOME/bin:$PATH' >> ~/.bashrc

# Configure Hadoop (pseudo-distributed mode for streaming, or just local mode)
# We use Hadoop streaming in local mode — no HDFS needed
echo "  Hadoop installed at $HADOOP_HOME"

echo "  [3.4] Installing Python packages..."
sudo apt-get install -y -qq python3 python3-pip awscli
pip3 install -q ray[default] oss2 boto3
echo "  Done."
REMOTE_SETUP

# ---- Step 4: Run MapReduce jobs ----
echo ""
echo "[4/5] Running MapReduce on ECS..."

ssh -o StrictHostKeyChecking=no "ubuntu@${PUBLIC_IP}" << 'RUN_MR'
set -e
HADOOP_HOME=/opt/hadoop
BUCKET="comp3006j-mp2-iot-logs"
REGION="cn-beijing"
OUTPUT_BASE="oss://${BUCKET}/output/mr"

# Download dataset and scripts from OSS
echo "  Downloading dataset and scripts from OSS..."
python3 -c "
import os, oss2, csv, io
auth = oss2.Auth(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
                  os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])
bucket = oss2.Bucket(auth, 'oss-${REGION}.aliyuncs.com', '${BUCKET}')

# Download dataset
result = bucket.get_object('dataset/iot_logs.csv')
with open('/tmp/iot_logs.csv', 'wb') as f:
    import shutil
    shutil.copyfileobj(result, f)
print('Downloaded dataset')

# Download scripts
for f in ['mapper1.py','reducer1.py','mapper2.py','reducer2.py','mapper3.py','reducer3.py']:
    bucket.get_object_to_file(f'scripts/{f}', f'/tmp/{f}')
    print(f'Downloaded {f}')
bucket.get_object_to_file('scripts/abnormal_detection_ray.py', '/tmp/abnormal_detection_ray.py')
"

export HADOOP_HOME=/opt/hadoop
export PATH=$HADOOP_HOME/bin:$PATH

INPUT=/tmp/iot_logs.csv
OUTPUT_DIR=/tmp/mr_outputs
mkdir -p $OUTPUT_DIR

echo ""
echo "  [MR1] Event Count by Sensor Type..."
cat $INPUT | python3 /tmp/mapper1.py | sort | python3 /tmp/reducer1.py > $OUTPUT_DIR/output1.txt
echo "    Done: $(wc -l < $OUTPUT_DIR/output1.txt) rows"

echo "  [MR2] Warning/Error Count by Building..."
cat $INPUT | python3 /tmp/mapper2.py | sort | python3 /tmp/reducer2.py > $OUTPUT_DIR/output2.txt
echo "    Done: $(wc -l < $OUTPUT_DIR/output2.txt) rows"

echo "  [MR3] Top 10 Most Active Devices..."
cat $INPUT | python3 /tmp/mapper3.py | sort | python3 /tmp/reducer3.py > $OUTPUT_DIR/output3.txt
echo "    Done: $(wc -l < $OUTPUT_DIR/output3.txt) rows"

# Upload MR results to OSS
echo ""
echo "  Uploading MR results to OSS..."
python3 -c "
import os, oss2
auth = oss2.Auth(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
                  os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])
bucket = oss2.Bucket(auth, 'oss-${REGION}.aliyuncs.com', '${BUCKET}')
for f in ['output1.txt','output2.txt','output3.txt']:
    bucket.put_object_from_file(f'output/mr/{f}', f'/tmp/mr_outputs/{f}')
    print(f'  Uploaded output/mr/{f}')
"
echo "  MapReduce complete."
RUN_MR

# ---- Step 5: Run Ray ----
echo ""
echo "[5/5] Running Ray on ECS..."

ssh -o StrictHostKeyChecking=no "ubuntu@${PUBLIC_IP}" << 'RUN_RAY'
set -e
BUCKET="comp3006j-mp2-iot-logs"
REGION="cn-beijing"

echo "  Starting Ray abnormal detection..."
python3 /tmp/abnormal_detection_ray.py \
    --local-input /tmp/iot_logs.csv \
    --chunk-size 5000 \
    --output /tmp/abnormal_devices_ray.txt 2>&1 | tail -5

echo ""
echo "  Uploading Ray results to OSS..."
python3 -c "
import os, oss2
auth = oss2.Auth(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
                  os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])
bucket = oss2.Bucket(auth, 'oss-${REGION}.aliyuncs.com', '${BUCKET}')
bucket.put_object_from_file('output/ray/abnormal_devices.txt', '/tmp/abnormal_devices_ray.txt')
# The Ray script saves to this path; check for alternative filename
import glob
for f in glob.glob('/tmp/*abnormal*') + glob.glob('/home/ubuntu/*abnormal*'):
    print(f'Found: {f}')
print('  Done.')
"
echo "  Ray complete."
RUN_RAY

# ---- Download results ----
echo ""
echo "Downloading results from OSS..."
LOCAL_OUT="$(dirname "$0")/../../outputs/ecs_${TIMESTAMP}"
mkdir -p "$LOCAL_OUT"

python3 -c "
import os, oss2
auth = oss2.Auth(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'],
                  os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])
bucket = oss2.Bucket(auth, 'oss-${REGION}.aliyuncs.com', '${BUCKET}')
local = '${LOCAL_OUT}'
os.makedirs(local, exist_ok=True)
for f in ['output/mr/output1.txt','output/mr/output2.txt','output/mr/output3.txt',
          'output/ray/abnormal_devices.txt']:
    try:
        bucket.get_object_to_file(f, os.path.join(local, os.path.basename(f)))
        print(f'  Downloaded {f}')
    except Exception as e:
        print(f'  Skip {f}: {e}')
"

# ---- Terminate ECS ----
echo ""
echo "Terminating ECS instance ${INSTANCE_ID}..."
aliyun ecs DeleteInstance --InstanceId "$INSTANCE_ID" --RegionId "$REGION" --Force true

echo ""
echo "=============================================="
echo " Pipeline complete!"
echo " Results: ${LOCAL_OUT}"
echo " OSS output: oss://${BUCKET}/output/"
echo "=============================================="
