"""
Task 1: Upload the IoT dataset to Alibaba Cloud OSS.
Usage: python 01_upload_oss.py
Requires: aliyun CLI configured, oss2 installed (pip install oss2)
"""
import os
import sys
import oss2

DATASET = os.path.join(os.path.dirname(__file__), '..', 'Comp3006J MiniProject 2 Dataset.csv')
BUCKET_NAME = 'comp3006j-mp2-iot-logs'
OSS_KEY = 'dataset/iot_logs.csv'
REGION = 'cn-hangzhou'

# OSS endpoints: https://help.aliyun.com/document_detail/31837.html
ENDPOINT = f'oss-{REGION}.aliyuncs.com'


def main():
    if not os.path.exists(DATASET):
        print(f'ERROR: Dataset not found at {DATASET}')
        sys.exit(1)

    # Read credentials from environment (set by aliyun CLI or manual export)
    access_key_id = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID')
    access_key_secret = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET')

    if not access_key_id or not access_key_secret:
        print('ERROR: Set environment variables first:')
        print('  export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"')
        print('  export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"')
        sys.exit(1)

    # Create auth and bucket objects
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, ENDPOINT, BUCKET_NAME)

    # Create bucket if not exists
    print(f'Ensuring bucket oss://{BUCKET_NAME} exists in {REGION} ...')
    try:
        bucket.create_bucket(oss2.BUCKET_ACL_PRIVATE)
        print('  Bucket created.')
    except oss2.exceptions.ServerError as e:
        if 'BucketAlreadyExists' in str(e):
            print('  Bucket already exists, continuing...')
        elif 'AccessDenied' in str(e):
            print('  Bucket name may be taken globally. Try a unique name.')
            sys.exit(1)
        else:
            raise

    # Upload dataset
    print(f'Uploading {DATASET} -> oss://{BUCKET_NAME}/{OSS_KEY} ...')
    with open(DATASET, 'rb') as f:
        result = bucket.put_object(OSS_KEY, f)
    print(f'  Upload complete. Status: {result.status}')

    # Verify
    print('Verifying...')
    object_info = bucket.get_object_meta(OSS_KEY)
    size_mb = object_info.content_length / (1024 * 1024)
    print(f'  Object size: {size_mb:.2f} MB')
    print(f'  Last modified: {object_info.headers.get("Last-Modified")}')
    print(f'\nDataset stored at: oss://{BUCKET_NAME}/{OSS_KEY}')
    print(f'Endpoint: {ENDPOINT}')


if __name__ == '__main__':
    main()
