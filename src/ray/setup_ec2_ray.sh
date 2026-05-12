#!/bin/bash
# ============================================================================
# EC2 Ray setup & run script for Mini-Project 2
# ============================================================================
# This script launches an EC2 instance, installs Ray, runs the abnormal device
# detection, uploads results to S3, and terminates the instance.
#
# Prerequisites:
#   - AWS CLI installed and configured
#   - EC2 key pair created
#   - Security group with SSH (22) access
# ============================================================================

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
KEY_NAME="${AWS_KEY_NAME:-}"                       # your EC2 key pair name
SECURITY_GROUP="${AWS_SG:-}"                       # your security group ID
BUCKET="comp3006j-miniproject2-iot-logs"
AMI_ID="ami-0c7217cddeea7ec7a"                     # Ubuntu 24.04 LTS us-east-1 (adjust for your region)
INSTANCE_TYPE="t3.medium"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "=== Mini-Project 2: EC2 + Ray Pipeline ==="
echo "Region: $REGION"
echo ""

# ---- Step 0: Upload Ray script to S3 ----
echo "[0/3] Uploading Ray script to S3..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
aws s3 cp "${SCRIPT_DIR}/abnormal_detection.py" \
    "s3://${BUCKET}/scripts/abnormal_detection.py" \
    --region "${REGION}"

# ---- Step 1: Launch EC2 instance ----
echo "[1/3] Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --region "${REGION}" \
    --image-id "${AMI_ID}" \
    --instance-type "${INSTANCE_TYPE}" \
    --key-name "${KEY_NAME}" \
    --security-group-ids "${SECURITY_GROUP}" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=comp3006j-ray-${TIMESTAMP}}]" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20}}]' \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "  Instance ID: ${INSTANCE_ID}"

# Wait for running
echo "  Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "${INSTANCE_ID}" --region "${REGION}"

PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "${INSTANCE_ID}" \
    --region "${REGION}" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "  Public IP: ${PUBLIC_IP}"

# Wait for SSH to be available
echo "  Waiting for SSH..."
sleep 30

# ---- Step 2: Setup Ray on EC2 and run detection ----
echo "[2/3] Setting up Ray and running detection..."

ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 "ubuntu@${PUBLIC_IP}" << 'EC2SETUP'
    set -e
    echo "Updating packages..."
    sudo apt-get update -qq

    echo "Installing Python and pip..."
    sudo apt-get install -y -qq python3 python3-pip python3-venv awscli

    echo "Setting up virtual environment..."
    python3 -m venv ray_env
    source ray_env/bin/activate

    echo "Installing Ray and boto3..."
    pip install -U pip -q
    pip install ray[default] boto3 -q

    echo "Downloading Ray script from S3..."
    BUCKET="comp3006j-miniproject2-iot-logs"
    aws s3 cp "s3://${BUCKET}/scripts/abnormal_detection.py" . --region "${REGION}"

    echo "Running Ray abnormal detection..."
    python abnormal_detection.py \
        --s3-input "s3://${BUCKET}/dataset/iot_logs.csv" \
        --chunk-size 5000

    echo "Uploading results to S3..."
    aws s3 cp ../outputs/abnormal_devices_ray.txt \
        "s3://${BUCKET}/output/ray_abnormal_devices.txt" \
        --region "${REGION}"
    aws s3 cp ../outputs/runtime_ray.json \
        "s3://${BUCKET}/output/ray_runtime.json" \
        --region "${REGION}"

    echo "Ray pipeline complete."
EC2SETUP

# ---- Step 3: Download results and terminate ----
echo "[3/3] Downloading results and terminating instance..."
OUTPUT_DIR="${SCRIPT_DIR}/../../outputs/ec2_ray_${TIMESTAMP}"
mkdir -p "${OUTPUT_DIR}"

aws s3 cp "s3://${BUCKET}/output/ray_abnormal_devices.txt" \
    "${OUTPUT_DIR}/abnormal_devices.txt" --region "${REGION}" 2>/dev/null || true
aws s3 cp "s3://${BUCKET}/output/ray_runtime.json" \
    "${OUTPUT_DIR}/runtime.json" --region "${REGION}" 2>/dev/null || true

echo "Terminating EC2 instance..."
aws ec2 terminate-instances --instance-ids "${INSTANCE_ID}" --region "${REGION}"

echo ""
echo "=== EC2 + Ray pipeline complete ==="
echo "Results: ${OUTPUT_DIR}"
