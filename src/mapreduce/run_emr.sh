#!/bin/bash
# ============================================================================
# EMR Hadoop Streaming launcher for Mini-Project 2
# ============================================================================
# Prerequisites:
#   - AWS CLI installed and configured (aws configure)
#   - Default EC2 key pair created in the target region
#   - Python mapper/reducer scripts uploaded to S3 alongside this script
#
# This script:
#   1. Creates an EMR cluster with Hadoop
#   2. Uploads mapper/reducer scripts to S3
#   3. Submits 3 Hadoop Streaming jobs (one per output)
#   4. Downloads results from S3
#   5. Terminates the cluster
# ============================================================================

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="comp3006j-miniproject2-iot-logs"
CLUSTER_NAME="comp3006j-mp2-cluster"
KEY_NAME="${AWS_KEY_NAME:-}"                    # set your EC2 key pair name
LOG_URI="s3://${BUCKET}/emr-logs/"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "=== Mini-Project 2: EMR MapReduce Pipeline ==="
echo "Region:  $REGION"
echo "Bucket:  $BUCKET"
echo ""

# ---- Step 0: Upload scripts to S3 ----
echo "[0/4] Uploading mapper/reducer scripts to S3..."
aws s3 sync "${SCRIPT_DIR}" "s3://${BUCKET}/scripts/" \
    --exclude "*" \
    --include "mapper*.py" \
    --include "reducer*.py" \
    --region "${REGION}"
echo "  Done."

# ---- Step 1: Create EMR cluster ----
echo "[1/4] Creating EMR cluster..."
CLUSTER_ID=$(aws emr create-cluster \
    --region "${REGION}" \
    --name "${CLUSTER_NAME}-${TIMESTAMP}" \
    --release-label emr-7.1.0 \
    --instance-groups '[
        {"InstanceRole":"MASTER","InstanceType":"m5.xlarge","InstanceCount":1},
        {"InstanceRole":"CORE","InstanceType":"m5.xlarge","InstanceCount":2}
    ]' \
    --applications Name=Hadoop \
    --log-uri "${LOG_URI}" \
    --service-role EMR_DefaultRole \
    --ec2-attributes "{\"KeyName\":\"${KEY_NAME}\",\"InstanceProfile\":\"EMR_EC2_DefaultRole\"}" \
    --auto-terminate \
    --query 'ClusterId' \
    --output text)

echo "  Cluster ID: ${CLUSTER_ID}"

# ---- Step 2: Wait for cluster to be ready ----
echo "[2/4] Waiting for cluster to be ready (this may take 3-5 minutes)..."
aws emr wait cluster-running --cluster-id "${CLUSTER_ID}" --region "${REGION}"
MASTER_DNS=$(aws emr describe-cluster --cluster-id "${CLUSTER_ID}" --region "${REGION}" \
    --query 'Cluster.MasterPublicDnsName' --output text)
echo "  Master DNS: ${MASTER_DNS}"

# ---- Step 3: Submit Hadoop Streaming jobs ----
echo "[3/4] Submitting Hadoop Streaming jobs..."

# Common Hadoop streaming arguments
STREAMING_JAR="command-runner.jar"
INPUT="s3://${BUCKET}/dataset/iot_logs.csv"

submit_job() {
    local job_name="$1"
    local mapper="$2"
    local reducer="$3"
    local output="$4"

    echo "  Submitting: ${job_name}..."

    STEP_ID=$(aws emr add-steps \
        --region "${REGION}" \
        --cluster-id "${CLUSTER_ID}" \
        --steps "[
            {
                \"Name\": \"${job_name}\",
                \"Type\": \"CUSTOM_JAR\",
                \"Jar\": \"${STREAMING_JAR}\",
                \"ActionOnFailure\": \"CONTINUE\",
                \"Args\": [
                    \"hadoop-streaming\",
                    \"-files\", \"s3://${BUCKET}/scripts/${mapper},s3://${BUCKET}/scripts/${reducer}\",
                    \"-input\", \"${INPUT}\",
                    \"-output\", \"${output}\",
                    \"-mapper\", \"python3 ${mapper}\",
                    \"-reducer\", \"python3 ${reducer}\",
                    \"-inputformat\", \"org.apache.hadoop.mapred.lib.NLineInputFormat\"
                ]
            }
        ]" \
        --query 'StepIds[0]' \
        --output text)

    echo "    Step ID: ${STEP_ID}"

    # Wait for step to complete
    echo "    Waiting for step to finish..."
    aws emr wait step-complete --cluster-id "${CLUSTER_ID}" --step-id "${STEP_ID}" --region "${REGION}"
    echo "    Done: ${job_name}"
}

# Job 1: Event Count by Sensor Type
submit_job \
    "EventCountBySensorType" \
    "mapper1.py" \
    "reducer1.py" \
    "s3://${BUCKET}/output/mr_output1/"

# Job 2: Warning/Error Count by Building
submit_job \
    "WarningErrorByBuilding" \
    "mapper2.py" \
    "reducer2.py" \
    "s3://${BUCKET}/output/mr_output2/"

# Job 3: Top 10 Most Active Devices
submit_job \
    "Top10ActiveDevices" \
    "mapper3.py" \
    "reducer3.py" \
    "s3://${BUCKET}/output/mr_output3/"

# ---- Step 4: Download results ----
echo "[4/4] Downloading results..."
OUTPUT_DIR="${SCRIPT_DIR}/../../outputs/emr_${TIMESTAMP}"
mkdir -p "${OUTPUT_DIR}"

aws s3 cp "s3://${BUCKET}/output/mr_output1/part-00000" "${OUTPUT_DIR}/output1_sensor_count.txt" --region "${REGION}" 2>/dev/null || echo "  Warning: output1 not found"
aws s3 cp "s3://${BUCKET}/output/mr_output2/part-00000" "${OUTPUT_DIR}/output2_warning_error.txt" --region "${REGION}" 2>/dev/null || echo "  Warning: output2 not found"
aws s3 cp "s3://${BUCKET}/output/mr_output3/part-00000" "${OUTPUT_DIR}/output3_top10_devices.txt" --region "${REGION}" 2>/dev/null || echo "  Warning: output3 not found"

echo ""
echo "=== Pipeline complete ==="
echo "Results downloaded to: ${OUTPUT_DIR}"
echo "S3 output: s3://${BUCKET}/output/"
echo ""
echo "Cluster ${CLUSTER_ID} will auto-terminate."
