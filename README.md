# COMP3006J Mini-Project 2: Smart Campus IoT Log Analytics

Cloud-based IoT log analytics pipeline: **Alibaba Cloud OSS → ECS Hadoop MapReduce → ECS Ray**.

## Architecture

```
本地开发机                        阿里云
┌──────────┐    oss2 SDK      ┌──────────┐
│  Python  │ ────────────────>│   OSS    │
│  CLI     │                  │ (dataset)│
└──────────┘                  └────┬─────┘
                                   │ 读取数据
                            ┌──────▼──────────┐
                            │      ECS         │
                            │  ┌────────────┐  │
                            │  │  Hadoop    │  │
                            │  │ MapReduce  │  │
                            │  └─────┬──────┘  │
                            │        │         │
                            │  ┌─────▼──────┐  │
                            │  │    Ray     │  │
                            │  │ 异常检测   │  │
                            │  └────────────┘  │
                            └──────────────────┘
                                   │ 结果回传
                            ┌──────▼──────────┐
                            │   OSS output/   │
                            └─────────────────┘
```

## Project Structure

```
├── src/
│   ├── 00_local_test.py              # 本地验证脚本
│   ├── 01_upload_oss.py              # 上传数据集到 OSS
│   ├── 04_validate.py                # 云结果 vs ground truth 对比
│   ├── mapreduce/
│   │   ├── mapper1.py / reducer1.py  # Output 1: Sensor Type Count
│   │   ├── mapper2.py / reducer2.py  # Output 2: Warnings by Building
│   │   └── mapper3.py / reducer3.py  # Output 3: Top 10 Devices
│   ├── ray/
│   │   └── abnormal_detection.py     # Ray 两阶段并行检测
│   └── ecs/
│       └── setup_and_run.sh          # 启动 ECS → 装环境 → 运行 → 销毁
├── outputs/                          # 产出物
└── Comp3006J MiniProject 2 Dataset.csv
```

## Quick Start (Local Only)

```bash
# 1. Generate ground truth
python src/00_local_test.py

# 2. Test MapReduce pipes
cat "Comp3006J MiniProject 2 Dataset.csv" | python src/mapreduce/mapper1.py | sort | python src/mapreduce/reducer1.py

# 3. Test Ray locally
python src/ray/abnormal_detection.py

# 4. Validate
python src/04_validate.py --ray-output outputs/abnormal_devices_ray.txt
```

## Cloud Deployment

### Prerequisite: Alibaba Cloud Setup

1. **Create AccessKey**: Alibaba Cloud Console → 右上角头像 → AccessKey管理 → 创建 AccessKey → 保存
2. **Create Key Pair**: ECS 控制台 → 网络与安全 → 密钥对 → 创建密钥对 (comp3006j-key) → 下载 .pem
3. **Create Security Group**: ECS 控制台 → 安全组 → 创建安全组 → 添加规则允许 TCP 22 (SSH) from 0.0.0.0/0
4. **Create VSwitch**: VPC 控制台 → 交换机 → 记下 vsw-xxxxxxxx
5. **Install aliyun CLI**: `pip install aliyun-python-sdk-core aliyun-python-sdk-ecs oss2`
6. **Configure**:
   ```bash
   export ALIBABA_CLOUD_ACCESS_KEY_ID="your-key-id"
   export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-secret"
   ```

### Step 1: Upload dataset to OSS

```bash
python src/01_upload_oss.py
```

### Step 2: Run everything on ECS

```bash
export ALIBABA_KEY_NAME="comp3006j-key"
export ALIBABA_SG="sg-xxxxxxxxxxxx"
export ALIBABA_VSWITCH="vsw-xxxxxxxxxxxx"

bash src/ecs/setup_and_run.sh
```

This single script:
1. Uploads mapper/reducer scripts to OSS
2. Launches an ECS instance (2 vCPU, 4 GB, Ubuntu 22.04)
3. Installs Java 8 + Hadoop 3.3.6 + Python + Ray
4. Runs all 3 MapReduce jobs (Hadoop streaming, local mode)
5. Runs Ray abnormal device detection (2-phase parallel)
6. Uploads all results to OSS
7. Downloads results to local `outputs/ecs_<timestamp>/`
8. **Auto-terminates the ECS instance**

Total runtime: ~6-8 minutes, cost: ~￥0.5-1.

### Step 3: Validate

```bash
python src/04_validate.py \
    --mr-output1 outputs/ecs_xxx/output1.txt \
    --mr-output2 outputs/ecs_xxx/output2.txt \
    --mr-output3 outputs/ecs_xxx/output3.txt \
    --ray-output outputs/ecs_xxx/abnormal_devices.txt
```

## Results Summary

| Output | Method | Content |
|--------|--------|---------|
| Output 1 | MapReduce | 6 sensor types count |
| Output 2 | MapReduce | 6 buildings WARNING/ERROR count |
| Output 3 | MapReduce | Top 10 most active devices |
| Abnormal Devices | Ray (2-phase) | ~243 entries across all buildings |

## Ray Design

Two-phase approach ensures correctness across parallel chunks:

1. **Phase 1 (parallel)**: `@ray.remote` tasks process data chunks independently, aggregating per-device stats (error_count, high_temp_count, min_battery)
2. **Phase 2 (local merge)**: Combine partial stats, apply detection rules on complete per-device aggregates

Detection rules: battery < 20 / ≥3 ERROR records / ≥3 temperature > 32 records.
