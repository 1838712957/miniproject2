"""
Task 1: Upload the IoT dataset to AWS S3.
Usage: python 01_upload_s3.py
Requires: aws configure with valid credentials, boto3 installed.
"""
import boto3
import os
import sys

DATASET = os.path.join(os.path.dirname(__file__), '..', 'Comp3006J MiniProject 2 Dataset.csv')
BUCKET_NAME = 'comp3006j-miniproject2-iot-logs'
S3_KEY = 'dataset/iot_logs.csv'


def main():
    if not os.path.exists(DATASET):
        print(f'ERROR: Dataset not found at {DATASET}')
        sys.exit(1)

    s3 = boto3.client('s3')

    # Create bucket (region-agnostic: LocationConstraint needed outside us-east-1)
    region = s3.meta.region_name
    print(f'Creating bucket s3://{BUCKET_NAME} in {region} ...')
    try:
        if region == 'us-east-1':
            s3.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=BUCKET_NAME,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f'  Bucket already exists, continuing...')

    # Upload dataset
    print(f'Uploading {DATASET} -> s3://{BUCKET_NAME}/{S3_KEY} ...')
    s3.upload_file(DATASET, BUCKET_NAME, S3_KEY)
    print('  Upload complete.')

    # Verify
    print('Verifying...')
    response = s3.head_object(Bucket=BUCKET_NAME, Key=S3_KEY)
    size_mb = response['ContentLength'] / (1024 * 1024)
    print(f'  Object size: {size_mb:.2f} MB')
    print(f'  Last modified: {response["LastModified"]}')
    print(f'\nDataset stored at: s3://{BUCKET_NAME}/{S3_KEY}')


if __name__ == '__main__':
    main()
