# 📊 市场洞察 SOP

> 暗号：`跑一下市场洞察`
> 模块：Eyes/（眼睛 — 盯市场）

---

## 一句话定位

市场洞察只回答一件事：**今天市场发生了什么，哪些方向值得进入下一步分析**

- 只处理事件 + 宏观信号
- **不负责价格扫描**（价格扫描在投资雷达里做）
- P14 板块猎手不是默认链路，有需要时再手动深挖

---

## 🔑 触发暗号

| 暗号 | 操作 |
|:---|:---|
| `跑一下市场洞察` | 完整流程（拉数据 → P13分析 → 保存） |
| `今天有什么新闻` | 快速浏览（拉1天数据 → 简要总结，不保存） |
| `抓 N 天数据` | 只抓数据不分析（运行脚本，存 Raw_Data） |

---

## ⚙️ 完整执行步骤

### Step 1：创建输出目录

**Linux / macOS (Bash)**：
```bash
mkdir -p "Eyes/市场洞察/Raw_Data/$(date +%Y-%m)"
mkdir -p "Eyes/市场洞察/$(date +%Y-%m)"
```

**Windows (PowerShell)**：
```powershell
$month = Get-Date -Format "yyyy-MM"
New-Item -ItemType Directory -Path "Eyes/市场洞察/Raw_Data/$month" -Force | Out-Null
New-Item -ItemType Directory -Path "Eyes/市场洞察/$month" -Force | Out-Null
```

### Step 2：拉取分析数据

#### Step 2.1：拉取 em A股持仓个股新闻

> **必须执行此步。**

**Linux / macOS (Bash)**：
```bash
python3 Eyes/scripts/fetch_em_news.py \
  --hours 24 \
  --output "Eyes/市场洞察/Raw_Data/$(date +%Y-%m)/em_news_$(date +%Y%m%d).json"
```

**Windows (PowerShell)**：
```powershell
$month = Get-Date -Format "yyyy-MM"
$date = Get-Date -Format "yyyyMMdd"
python Eyes/scripts/fetch_em_news.py `
  --hours 24 `
  --output "Eyes/市场洞察/Raw_Data/$month/em_news_$date.json"
```

**策略说明**：
- 只对【持仓状态机】中 A股 标的拉取 
- Watchlist 不拉个股新闻（节省 rate limit）
- 美股/港股 Ticker 不支持 em，自动过滤

#### Step 2.2：主 RSS 免费数据源

**Linux / macOS (Bash)**：
```bash
python3 Eyes/scripts/fetch_rss_byMiniflux.py 1 \
  --output "Eyes/市场洞察/Raw_Data/$(date +%Y-%m)/financial_data_$(date +%Y%m%d).json"
```

**Windows (PowerShell)**：
```powershell
$month = Get-Date -Format "yyyy-MM"
$date = Get-Date -Format "yyyyMMdd"
python Eyes/scripts/fetch_rss_byMiniflux.py 1 `
  --output "Eyes/市场洞察/Raw_Data/$month/financial_data_$date.json"
```

**Agent 执行规则**：
1. 用户指定天数时，把 `1` 替换为对应天数

#### Step 2.3：补充 RSS 免费数据源

**Linux / macOS (Bash)**：
```bash
python3 Eyes/scripts/fetch_rss_byMiniflux.py 1 \
  --config Eyes/scripts/rss_sources_custom.json \
  --output "Eyes/市场洞察/Raw_Data/$(date +%Y-%m)/supplementary_rss_$(date +%Y%m%d).json"
```

**Windows (PowerShell)**：
```powershell
$month = Get-Date -Format "yyyy-MM"
$date = Get-Date -Format "yyyyMMdd"
python Eyes/scripts/fetch_rss_byMiniflux.py 1 `
  --config Eyes/scripts/rss_sources_custom.json `
  --output "Eyes/市场洞察/Raw_Data/$month/supplementary_rss_$date.json"
```

**Agent 执行规则**：
1. 用户指定天数时，把 `1` 替换为对应天数
2. 根据运行平台自动选择对应的命令格式

---

### Step 2.4 & 2.5：CIO 半成品处理（子任务串行执行）

> ⚠️ **本步骤使用 `general_purpose_task` 子任务处理，避免大文件污染主会话上下文**

#### 子任务配置

| 任务 ID | 任务 | 输入 | 输出 |
|:---|:---|:---|:---|
| CIO-main | 主 RSS CIO 处理 | `financial_data_{YYYYMMDD}.json` | `cio_processed_{YYYYMMDD}.md` |
| CIO-supple | 补充 RSS CIO 处理 | `supplementary_rss_{YYYYMMDD}.json` | `cio_processed_custom_{YYYYMMDD}.md` |

#### 调用方式

**执行子任务 A (CIO-main)**：
```json
{
  "name": "auto-research-report-analyst",
  "parameters": {
    "description": "CIO主RSS处理",
    "query": "【使用 DS-V4-Flash 模型】读取文件 Eyes/市场洞察/Raw_Data/{YYYY-MM}/financial_data_{YYYYMMDD}.json，按照 Brain/references/cio-rss-processor.md 的规则处理（智能去重合并、噪音过滤、事件聚类、信号提取分类），输出格式化的半成品情报到 Eyes/市场洞察/Raw_Data/{YYYY-MM}/cio_processed_{YYYYMMDD}.md，处理完成后无需返回详细摘要",
    "response_language": "zh"
  }
}
```

**执行子任务 B (CIO-supple)**：
```json
{
  "name": "auto-research-report-analyst",
  "parameters": {
    "description": "CIO补充RSS处理",
    "query": "【使用 DS-V4-Flash 模型】读取文件 Eyes/市场洞察/Raw_Data/{YYYY-MM}/supplementary_rss_{YYYYMMDD}.json，按照 Brain/references/cio-rss-processor.md 的规则处理（智能去重合并、噪音过滤、事件聚类、信号提取分类），输出格式化的半成品情报到 Eyes/市场洞察/Raw_Data/{YYYY-MM}/cio_processed_custom_{YYYYMMDD}.md，处理完成后无需返回详细摘要",
    "response_language": "zh"
  }
}
```

#### 执行时序

- **Step 2.4** 与 **Step 2.5** 需**串行执行**（CIO-main 完成后再执行 CIO-supple）
- 两个子任务都完成后，进入 Step 3

---

### Step 3：调用 P13 分析

> ⚠️ **前置条件**：必须等待 Step 2.1 ~ Step 2.5 **全部完成**后才能执行此步骤

**执行方式**：
```json
{
  "name": "auto-research-report-analyst",
  "parameters": {
    "description": "P13市场洞察分析",
    "query": "【使用 DS-V4-Pro 模型】按优先级读取：
              1. **主输入**：`Eyes/市场洞察/Raw_Data/{YYYY-MM}/cio_processed_YYYYMMDD.md`
              2. **补充输入**：`Eyes/市场洞察/Raw_Data/{YYYY-MM}/finnhub_news_YYYYMMDD.json`
                 - `p15_trigger=true` 的条目 → P13 报告中标注「建议跑 P15」
              3. **补充输入**：`Eyes/市场洞察/Raw_Data/{YYYY-MM}/cio_processed_custom_{YYYYMMDD}.md`
              4. **P13 分析时，参考过去几天的历史洞察（如有）**：
                 - 路径：`Eyes/市场洞察/YYYY-MM/` 目录下最近几份报告
              5. 按照 Brain/references/p13-market-scanner.md 进行分析，严格按 p13-market-scanner.md `# Output Format` 区块 的格式输出报告到`Eyes/市场洞察/YYYY-MM/YYYY-MM-DD_市场洞察.md`，处理完成后无需返回详细摘要",
    "response_language": "zh"
  }
}
```
> ⚠️ **P14 不在默认链路内**：用户明确要做板块深挖时再手动触发 `Brain/references/p14-sector-hunter.md`

### Step 4 在对话中输出

直接在对话中输出完整 `Eyes/市场洞察/YYYY-MM/YYYY-MM-DD_市场洞察.md` 报告内容。

---

## 📦 产出物清单

| 文件 | 路径 | 命名规则 | 说明 |
|:---|:---|:---|:---|
| Raw Data（API/RSS） | `Eyes/市场洞察/Raw_Data/YYYY-MM/` | `financial_data_YYYYMMDD.json` | 必有 |
| CIO 半成品情报 | `Eyes/市场洞察/Raw_Data/YYYY-MM/` | `cio_processed_YYYYMMDD.md` | 仅 RSS 路径 |
| Finnhub News | `Eyes/市场洞察/Raw_Data/YYYY-MM/` | `finnhub_news_YYYYMMDD.json` | 有 key 才有 |
| 市场洞察报告 | `Eyes/市场洞察/YYYY-MM/` | `YYYY-MM-DD_市场洞察.md` | 必有 |

---

## 📤 下游分发规则

市场洞察本身不触发个股分析或策略制定，但它是投资雷达的核心输入：

- 生成的洞察报告会被 `跑一下投资雷达` 自动读取
- 洞察中出现的相关板块/事件信号，在投资雷达里会与持仓 + Watchlist 做关联匹配
- 重大事件在投资雷达报告的「下一步建议」中推荐对应的策略分析路由

---

## 📁 路径速查

| 内容 | 路径 |
|:---|:---|
| 市场数据脚本（API） | `Eyes/scripts/fetch_market_api.py` |
| 市场数据脚本（RSS） | `Eyes/scripts/fetch_rss_byMiniflux.py` |
| RSS 源配置 | `Eyes/scripts/rss_sources.json` |
| CIO 处理提示词 | `Brain/references/cio-rss-processor.md` |
| Finnhub News 脚本 | `Eyes/scripts/fetch_finnhub_news.py` |
| P13 提示词 | `Brain/references/p13-market-scanner.md` |
| P14 提示词（手动深挖） | `Brain/references/p14-sector-hunter.md` |
| 历史洞察报告归档 | `Eyes/市场洞察/YYYY-MM/` |
| Raw Data 归档 | `Eyes/市场洞察/Raw_Data/YYYY-MM/` |

---

## ⚠️ 边界

- 市场洞察**不看持仓**，不看价格
- 不自动更新状态机
- 不进入策略判断

---

*SOP 版本：2026-03-18 · YMOS V3 三模块制（Eyes / Brain / 持仓与关注）*
