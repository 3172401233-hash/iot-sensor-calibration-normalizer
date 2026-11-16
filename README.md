# iot-sensor-calibration-normalizer

物联网传感器读数归一化组件（纯 Python 标准库，无第三方依赖）。解决多厂商
设备在温度单位、时间精度、时钟漂移和校准系数上的差异，并在校准版本迟到时
对历史读数生成可追溯的更正批次，而不覆盖已经下发的原始证据。

## 基准约定

- **基准温度单位：摄氏度（`celsius`）**。支持的输入单位与别名：
  - 摄氏度：`celsius`、`C`、`°C`、`degC`
  - 华氏度：`fahrenheit`、`F`、`°F`、`degF`
  - 开尔文：`kelvin`、`K`、`degK`
- **基准时间：带时区的 UTC `datetime`**（`tzinfo=timezone.utc`）。
  支持的设备时间戳：带时区/naive 的 `datetime`、epoch 秒（`int`/`float`）、
  ISO 8601 字符串（含 `Z` 后缀）。naive 时间按设备元数据的 `timezone`
  （IANA 名称如 `Asia/Shanghai`，或固定偏移如 `+08:00`）解释。
- **时间精度**：按输入推断为 `seconds` / `milliseconds` / `microseconds`，
  随归一化结果一起输出，报表可据此决定聚合粒度。
- **校准模型**：线性修正 `calibrated = raw_celsius * slope + intercept`，
  生效区间为左闭右开 `[effective_from, effective_to)`；同一时刻命中多个
  版本时取版本号最大者（同版本取 `received_at` 更晚者）。

## 质量模型

厂商质量码通过 `DeviceMetadata.quality_map` 映射为三种标准状态：

| 状态 | 含义 | 温度输出 |
| --- | --- | --- |
| `GOOD` | 读数可信 | 校准后温度 |
| `UNCERTAIN` | 可用但存疑（无匹配校准、时钟偏差超阈等） | 校准后温度或原始换算值 |
| `BAD` | 无效读数 | `None` |

附加质量标记 `quality_flags` 可并存：`UNCALIBRATED`、`CLOCK_SKEW`、
`INVALID_QUALITY_CODE`、`DUPLICATE`、`CORRECTED`。未知质量码不会被静默
当作正常值，一律判为 `BAD` 并附加 `INVALID_QUALITY_CODE`。

## 迟到校准与更正批次

1. 原始读数写入时即计算 SHA-256 并作为 `RawEvidence` 落库，**只追加、
   不可修改或删除**；同一 `reading_id` 写入不同内容会抛出
   `DuplicateConflictError`。
2. 校准迟到（`received_at` 晚于读数接收时间，但其生效区间覆盖该读数）时，
   `register_calibration` 自动生成 `CorrectionBatch`：
   - 旧归一化读数不删除，通过 `superseded_by` 指向新版本的 checksum；
   - 新版本 `revision` 递增并带 `CORRECTED` 标记；
   - 批次记录受影响读数范围（`affected_from`/`affected_to`）、被替换与
     新读数的 checksum 列表，以及批次自身的 SHA-256。
3. 所有写操作按 `reading_id` / `calibration_id` 幂等：重复上报同一读数
   返回已有结果且标记 `duplicate=True`；重复注册同一校准返回已有批次，
   不产生重复修订。

## 快速上手

```python
from datetime import datetime, timezone
from sensor_normalizer import (
    Calibration, DeviceMetadata, Normalizer, RawReading,
)

normalizer = Normalizer()
normalizer.register_device(DeviceMetadata(
    device_id="dev-1",
    temperature_unit="fahrenheit",
    timezone="Asia/Shanghai",
    clock_offset_seconds=5.0,
    quality_map={"OK": "GOOD", "FAIL": "BAD"},
))
normalizer.register_calibration(Calibration(
    calibration_id="cal-1", device_id="dev-1", version=1,
    effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    effective_to=None, slope=1.0, intercept=0.0,
    received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
))

result = normalizer.ingest(RawReading(
    reading_id="r-1", device_id="dev-1", value=50.0,
    device_timestamp="2026-01-05T08:00:00+08:00",
    quality_code="OK",
    ingested_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
))
print(result.normalized.temperature_celsius)  # 10.0（摄氏度，UTC 时间）

# 迟到的新校准：自动对历史读数生成更正批次
batch = normalizer.register_calibration(Calibration(
    calibration_id="cal-2", device_id="dev-1", version=2,
    effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    effective_to=None, slope=1.0, intercept=0.5,
    received_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
))
print(batch.affected_reading_ids)
```

## 无法自动修正、需要人工介入的情况

- **无任何覆盖该时刻的校准版本**：输出 `UNCERTAIN/UNCALIBRATED`，温度仅
  保留单位换算后的原始值，不猜测系数。
- **厂商质量码未知或映射为 `BAD`**：读数判废，`temperature_celsius=None`，
  即使后续校准到达也不会补造温度，只会生成带 `CORRECTED` 标记的废读数修订。
- **时间戳无法解析或类型不受支持**：直接抛出 `InvalidReadingError`，
  组件不做时间猜测；naive 时间且设备未配置时区时按 UTC 处理（应通过设备
  元数据显式配置时区避免歧义）。
- **设备时钟行为不符合“固定偏差 + 线性漂移”模型**（如随机跳变、夏令时
  处理错误、NTP 校时未上报）：线性模型无法还原真实时间，超阈时仅打
  `CLOCK_SKEW` 标记，需结合设备日志人工核对。
- **同一 `reading_id` 的原始内容与已存证据不一致**：拒绝写入
  （`DuplicateConflictError`），原始证据不可覆盖，需人工排查链路重复或
  篡改。
- **不支持的温度单位**（如兰氏度）：注册/写入时抛出 `UnknownUnitError`，
  需先扩展 `sensor_normalizer/units.py`。
- **校准记录本身非法**（区间倒置、版本号非正整数、时间不带时区）：
  抛出 `CalibrationError`，不会静默生效。

## 代码结构

```
sensor_normalizer/
├── models.py        # 设备、校准、原始读数、归一化读数、更正批次模型
├── units.py         # 温度单位换算（基准：摄氏度）
├── timeutils.py     # 时间戳解析、精度识别、时区与时钟漂移修正
├── quality.py       # 厂商质量码 -> GOOD/UNCERTAIN/BAD
├── calibration.py   # 校准区间选择与线性修正
├── checksum.py      # 规范化 JSON + SHA-256
├── store.py         # append-only 证据存储（内存实现，可替换接口）
└── normalizer.py    # 归一化入口、迟到校准更正批次与幂等控制
```

## 运行测试

```bash
python -m unittest
```

测试覆盖：单位换算、校准左闭右开边界与版本交叠、时钟偏差/漂移修正、
时间精度识别、重复读数幂等、无效质量码、多次修订、checksum 防篡改、
更正批次范围与幂等性。
