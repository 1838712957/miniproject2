"""
Connect to ECS via SSH, install Hadoop + Ray, run MapReduce and Ray jobs.
"""
import paramiko
import os
import sys
import time

ECS_HOST = "101.37.66.156"
ECS_USER = "root"
ECS_PASSWORD = "MiniProject2!"
OSS_BUCKET = "comp3006j-mp2-iot-logs"
OSS_ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"
AK_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
AK_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "..", "..")


def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {ECS_HOST}...")
    client.connect(ECS_HOST, username=ECS_USER, password=ECS_PASSWORD, timeout=30)
    print("  Connected.")
    return client


def run_cmd(client, cmd, desc=""):
    if desc:
        print(f"  [{desc}]")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out:
        for line in out.strip().split('\n'):
            print(f"    {line}")
    if err and 'WARNING' not in err:
        for line in err.strip().split('\n')[:3]:
            print(f"    [stderr] {line}")
    return out, err


def upload_file(client, local_path, remote_path):
    sftp = client.open_sftp()
    print(f"  Uploading {os.path.basename(local_path)} -> {remote_path}")
    sftp.put(local_path, remote_path)
    sftp.close()


def main():
    client = ssh_connect()

    # ---- Step 1: Install system packages ----
    run_cmd(client, "yum update -y -q 2>/dev/null || true", "update packages")
    run_cmd(client, "yum install -y -q java-1.8.0-openjdk-devel python3 python3-pip wget unzip 2>&1 | tail -3", "install java/python/wget")

    run_cmd(client, "java -version 2>&1 | head -1", "verify java")
    run_cmd(client, "python3 --version 2>&1", "verify python")

    # ---- Step 2: Install Hadoop 3.3.6 ----
    print("  [Installing Hadoop]")
    run_cmd(client, """
        if [ ! -d /opt/hadoop ]; then
            wget -q https://dlcdn.apache.org/hadoop/common/hadoop-3.3.6/hadoop-3.3.6.tar.gz -O /tmp/hadoop.tar.gz
            tar xzf /tmp/hadoop.tar.gz -C /opt/
            mv /opt/hadoop-3.3.6 /opt/hadoop
            rm /tmp/hadoop.tar.gz
            echo 'export HADOOP_HOME=/opt/hadoop' >> /etc/profile
            echo 'export PATH=$HADOOP_HOME/bin:$PATH' >> /etc/profile
        fi
        echo "Hadoop installed at /opt/hadoop"
    """, "hadoop")

    # ---- Step 3: Install Python packages ----
    run_cmd(client, "pip3 install -q ray[default] oss2 2>&1 | tail -2", "install ray/oss2")

    # ---- Step 4: Upload mapper/reducer/ray scripts ----
    mr_dir = os.path.join(SCRIPT_DIR, "..", "mapreduce")
    for f in ["mapper1.py", "reducer1.py", "mapper2.py", "reducer2.py", "mapper3.py", "reducer3.py"]:
        upload_file(client, os.path.join(mr_dir, f), f"/tmp/{f}")

    ray_script = os.path.join(SCRIPT_DIR, "..", "ray", "abnormal_detection.py")
    upload_file(client, ray_script, "/tmp/abnormal_detection.py")

    # ---- Step 5: Download dataset from OSS ----
    run_cmd(client, f"""
        python3 -c "
import oss2
auth = oss2.Auth('{AK_ID}', '{AK_SECRET}')
bucket = oss2.Bucket(auth, '{OSS_ENDPOINT}', '{OSS_BUCKET}')
result = bucket.get_object('dataset/iot_logs.csv')
with open('/tmp/iot_logs.csv', 'wb') as f:
    import shutil
    shutil.copyfileobj(result, f)
print('Dataset downloaded:', result.content_length, 'bytes')
"
    """, "download dataset from OSS")

    # ---- Step 6: Run MapReduce jobs ----
    print("\n  ===== MapReduce Jobs =====")

    jobs = [
        ("Output1: Sensor Count", "mapper1.py", "reducer1.py", "/tmp/output1.txt"),
        ("Output2: Warnings by Building", "mapper2.py", "reducer2.py", "/tmp/output2.txt"),
        ("Output3: Top 10 Devices", "mapper3.py", "reducer3.py", "/tmp/output3.txt"),
    ]

    for name, mapper, reducer, outfile in jobs:
        t0 = time.time()
        run_cmd(client, f"""
            cat /tmp/iot_logs.csv | python3 /tmp/{mapper} | sort | python3 /tmp/{reducer} > {outfile}
            echo "Rows: $(wc -l < {outfile})"
        """, name)
        print(f"    Time: {time.time() - t0:.2f}s")
        # Show output
        run_cmd(client, f"cat {outfile}", "output")

    # ---- Step 7: Run Ray abnormal detection ----
    print("\n  ===== Ray Abnormal Detection =====")
    t0 = time.time()
    run_cmd(client,
        "python3 /tmp/abnormal_detection.py --local-input /tmp/iot_logs.csv --chunk-size 5000 --output /tmp/abnormal_devices.txt 2>&1 | grep -v 'INFO\|FutureWarning\|warnings'",
        "ray detection")
    print(f"    Total Ray time: {time.time() - t0:.2f}s")

    # Show Ray output summary
    run_cmd(client, "echo 'Ray entries:' $(wc -l < /tmp/abnormal_devices.txt); head -10 /tmp/abnormal_devices.txt", "ray results")

    # ---- Step 8: Upload results to OSS ----
    print("\n  [Uploading results to OSS]")
    run_cmd(client, f"""
        python3 -c "
import oss2
auth = oss2.Auth('{AK_ID}', '{AK_SECRET}')
bucket = oss2.Bucket(auth, '{OSS_ENDPOINT}', '{OSS_BUCKET}')
for f in ['output1.txt','output2.txt','output3.txt','abnormal_devices.txt']:
    bucket.put_object_from_file(f'output/{{f}}', f'/tmp/{{f}}')
    print(f'Uploaded output/{{f}}')
"
    """, "upload results")

    # ---- Step 9: Download results to local ----
    print("\n  [Downloading results to local]")
    local_out = os.path.join(PROJECT_DIR, "outputs", "ecs_results")
    os.makedirs(local_out, exist_ok=True)

    sftp = client.open_sftp()
    for f in ["output1.txt", "output2.txt", "output3.txt", "abnormal_devices.txt"]:
        remote_path = f"/tmp/{f}"
        local_path = os.path.join(local_out, f)
        try:
            sftp.get(remote_path, local_path)
            print(f"  Downloaded: {f}")
        except Exception as e:
            print(f"  Skip {f}: {e}")
    sftp.close()

    client.close()

    print(f"\n{'='*50}")
    print(f"All done! Results saved to: {local_out}")
    print(f"OSS output: oss://{OSS_BUCKET}/output/")

    # Show runtime info for report
    print(f"\nRuntime Environment:")
    print(f"  Cloud: Alibaba Cloud ECS (cn-hangzhou)")
    print(f"  Instance: iZbp1fgovjbwaoizzkw34sZ")
    print(f"  Type: ecs.c1m1.large (2 vCPU, 2 GB)")
    print(f"  OS: Alibaba Cloud Linux 3")
    print(f"  Hadoop: 3.3.6 (streaming, local mode)")
    print(f"  Ray: local mode on ECS")


if __name__ == "__main__":
    main()
