---
name: mx-macro-data
description: 基于东方财富数据库，支持自然语言查询全球宏观经济数据，涵盖国民经济核算、价格指数、货币金融、财政收支、对外贸易、就业民生、产业运行等多个领域，适配各类宏观经济研究、市场分析、政策解读等多元专业场景需求。返回结果包含数据说明及csv文件。
allowed-tools:
  - Bash(python:*)
  - Read
---

# 宏观经济数据查询

通过**文本输入**查询宏观经济数据，接口返回 JSON 后会自动转换为 **CSV** 并生成对应的**内容描述 txt** 文件。

## 密钥来源与安全说明

- 本技能仅使用一个环境变量：`EM_API_KEY`。
- `EM_API_KEY` 由东方财富妙想服务（`https://ai.eastmoney.com/mxClaw`）签发，用于其接口鉴权。
- 在提供密钥前，请先确认密钥来源、可用范围、有效期及是否支持重置/撤销。
- 禁止在代码、提示词、日志或输出文件中硬编码/明文暴露密钥。

## 核心输入约束

- **时间维度**：支持相对时间表述（如"今年"、"过去三年"、"上月"）。
- **地域维度**：支持宏观地区表述（如"中国"、"美国"、"欧元区"、"华东地区"、"中国各省"），无需拆解为具体省市列表。

### 禁止模糊商品类别
- **禁止输入**：大类统称（如"稀土金属"、"有色金属"、"农产品"、"能源"、"科技股"）。
- **要求**：必须解包为具体的**交易品种名称或代码**。

### 禁止宏观泛指指标
- **禁止输入**：宽泛的经济概念而无具体指标（如"中国经济"、"美国制造业状况"、"全球通胀情况"）。
- **要求**：必须指定具体的**指标名称**（如 GDP、CPI、PMI、失业率、工业增加值等）。

### 时间与地域的灵活性
- **时间**：无需绝对日期。
  - ✅ 允许："查询中国过去五年的M2增速"、"查询上个月美国的非农数据"、"查询黄金今日价格"。
  - ✅ 允许（缺省）："查询德国失业率" 。
- **地域**：无需拆解为子集列表。
  - ✅ 允许："查询华东地区GDP"、"查询中国各省GDP"。

## 功能范围

### 基础查询能力

- **经济指标**：GDP、CPI、PPI、PMI、失业率、工业增加值等（支持指定国家/地区及具体指标名）。
- **货币金融**：M1/M2 货币供应量、社融规模、国债利率、汇率（支持指定币种对）。
- **商品价格**：黄金、白银、原油、铜、特定稀土氧化物等（**必须**指定具体品种）。
- **时间频率**：自动识别相对时间（年、季、月、周、日）并匹配对应频率数据；若未指定，返回最新数据。

### 查询示例对照表

| 类型     | ❌ 禁止的模糊查询 (指标/品种不明)      | ✅ 允许的明确查询 (时间/地区可灵活)             |
|----------|--------------------------------------|------------------------------------------------|
| 国内经济 | 查询华东地区GDP                        | 查询华东地区 GDP                              |
| 货币供应 | 查询主要新兴市场货币供应                | 查询中国、印度、巴西的 M2 货币供应量             |
| 商品价格 | 查询稀土和有色金属价格                 | 查询氧化镨钕、铜、铝的现货价格走势                |
| 全球宏观 | 查询 Top 3 经济体非农数据              | 查询美国、中国、德国的非农就业数据                |
| 时间灵活 | (无)                                  | 查询美国过去十年的失业率趋势                    |
| 默认时间 | (无)                                  | 查询日本最新的核心 CPI 数据                     |

## 前提条件

### 1. 注册东方财富妙想账号

访问 https://ai.eastmoney.com/mxClaw 注册账号并获取API_KEY。

### 2. 配置 Token

```bash
# macOS 添加到 ~/.zshrc，Linux 添加到 ~/.bashrc
export EM_API_KEY="your_api_key_here"
```

然后根据系统执行对应的命令：

**macOS：**
```bash
source ~/.zshrc
```

**Linux：**
```bash
source ~/.bashrc
```

### 3. 安装依赖

```bash
pip3 install httpx --user
```

## 快速开始

### 1. 命令行调用

在项目根目录或配置的工作目录下执行：

```bash
python3 {baseDir}/scripts/get_data.py --query 中国GDP
```

**参数说明：**

| 参数            | 说明             | 必填 |
| --------------- | ---------------- | ---- |
| `--query`       | 自然语言查询条件 | ✅    |

### 2. 代码调用

```python
import asyncio
from pathlib import Path
from scripts.get_data import query_mx_macro_data

async def main():
    result = await query_mx_macro_data(
        query="中国近五年GDP",
        output_dir=Path("workspace/mx_macro_data"),
    )
    if "error" in result:
        print(result["error"])
    else:
        print(f"CSV: {r['csv_paths']}")
        print(f"描述: {r['description_path']}")
        print(f"行数: {r['row_counts']}")

asyncio.run(main())
```

输出示例：
```
CSV: /path/to/workspace/mx_macro_data/mx_macro_data_4591GG28_yearly.csv
CSV: /path/to/workspace/mx_macro_data/mx_macro_data_4591GG28_quarterly.csv
CSV: /path/to/workspace/mx_macro_data/mx_macro_data_4591GG28_monthly.csv
描述:/path/to/workspace/mx_macro_data/mx_macro_data_4591GG28_description.txt
行数: 年: 10行, 季: 20行, 月: 40行
```

## 输出文件说明

| 文件 | 说明 |
|------|------|
| `mx_macro_data_<查询ID>_<频率>.csv` | 按频率分组的宏观数据表，UTF-8 编码，可直接用 Excel 或 pandas 打开。 |
| `mx_macro_data_<查询ID>_description.txt` | 说明文件，含各频率数据统计、数据来源和单位等信息。 |

## 环境变量

| 变量                      | 说明                                  | 默认                     |
| ------------------------- | ------------------------------------- | ------------------------ |
| `MX_MACRO_DATA_OUTPUT_DIR` | CSV 与描述文件的输出目录（可选）      | `miaoxiang/mx_macro_data` |
| `EM_API_KEY`              | 东方财富宏观查数工具 API 密钥（必备） | 无                       |

## 常见问题

**Q: 提示"请设置 EM_API_KEY 环境变量"怎么办？**

A: 按以下步骤配置 API 密钥：
1. 访问 [东方财富宏观查数工具](https://ai.eastmoney.com/mxClaw) 注册并获取 `API_KEY`。
2. 配置环境变量：
   ```bash
   # macOS/Linux
   export EM_API_KEY="your_api_key_here"
   
   # Windows PowerShell
   $env:EM_API_KEY="your_api_key_here"
   ```

**Q: 如何指定输出目录？**

A: 通过设置 `MX_MACRO_DATA_OUTPUT_DIR` 环境变量：
```bash
export MX_MACRO_DATA_OUTPUT_DIR="/path/to/output"
python3 scripts/get_data.py --query "查询内容"
```
