---
name: tushare-finance
description: 获取中国金融市场数据（A股、港股、美股、基金、期货、债券）。支持220+个Tushare Pro接口：股票行情、财务报表、宏观经济指标。当用户请求股价数据、财务分析、指数行情、GDP/CPI等宏观数据时使用。
allowed-tools:
  - Bash(python:*)
  - Read
---

# Tushare 金融数据 Skill

本 skill 通过 Tushare Pro API 获取中国金融市场数据，支持 220+ 个数据接口。

## 快速开始

### 1. Token 配置

**询问用户**：是否已配置 Tushare Token？

如未配置，引导用户：
1. 访问 https://tushare.pro 注册
2. 获取 Token
3. 配置环境变量：`export TUSHARE_TOKEN="your_token"`

### 2. 验证依赖

检查 Python 环境：
```bash
python -c "import tushare, pandas; print('OK')"
```

如报错，安装依赖：
```bash
pip install tushare pandas
```

## 常用接口速查

**⚠️ 120积分用户可用接口（推荐）：**

| 数据类型 | 接口方法 | 说明 |
|---------|---------|------|
| 日线行情 | `pro.daily()` | 获取日线行情数据（120积分） |
| IPO新股列表 | `pro.new_share()` | 新股申购数据（120积分） |
| 每日涨跌停 | `pro.stk_limit()` | 部分可用（120积分起） |
| LPR利率 | `pro.shibor_lpr()` | 贷款市场报价利率（120积分） |
| LIBOR利率 | `pro.libor()` | 伦敦银行间拆借利率（120积分） |
| HIBOR利率 | `pro.hibor()` | 香港银行间拆借利率（120积分） |

**❌ 需要2000+积分的接口（当前不可用）：**
- `pro.stock_basic()` - 股票列表
- `pro.fina_indicator()` - 财务指标
- `pro.income()` - 利润表
- `pro.balancesheet()` - 资产负债表
- `pro.cashflow()` - 现金流量表
- `pro.index_daily()` - 指数日线
- `pro.fund_nav()` - 基金净值
- `pro.gdp()` - GDP数据
- `pro.cpi()` - CPI数据

**完整接口列表**：查看 [接口文档索引](https://clawhub.ai/api/v1/skills/tushare-finance/file?path=reference%2FREADME.md)

## 数据获取流程

1. **查找接口**：根据需求在 [接口索引](https://clawhub.ai/api/v1/skills/tushare-finance/file?path=reference%2FREADME.md) 找到对应接口
2. **阅读文档**：查看 [接口文档](https://clawhub.ai/api/v1/skills/tushare-finance/file?path=reference%2F接口文档%2F) 了解参数
3. **编写代码**：
   ```python
   from scripts.api_client import TushareAPI
   
   api = TushareAPI()
   
   # 日线行情（120积分，可用）
   df = api.get_stock_daily('600519.SH', '20241201', '20241231')
   
   # IPO新股列表（120积分，可用）
   df = api.pro.new_share()
   ```
4. **返回结果**：DataFrame 格式

## 参数格式说明

- **日期**：YYYYMMDD（如 20241231）
- **股票代码**：ts_code 格式（如 000001.SZ, 600000.SH）
- **返回格式**：pandas DataFrame

## 接口文档参考

**接口索引**：[接口文档索引](https://clawhub.ai/api/v1/skills/tushare-finance/file?path=reference%2FREADME.md)

接口文档按类别组织：
- 股票数据（39 个接口）
- 指数数据（18 个接口）
- 基金数据（11 个接口）
- 期货期权（16 个接口）
- 宏观经济（10 个接口）
- 港股美股（23 个接口）
- 债券数据（16 个接口）

## 接口权限与调用限制

### 积分制度说明

Tushare Pro 采用积分制度来管理 API 调用权限，只有达到或超过接口最低分值要求才能调取数据。积分越多，调用频次（每分钟调取API的次数）越高。

**⚠️ 当前账户积分**：120 分

### 120积分用户可用接口

| 数据类型 | 接口方法 | 最低积分 | 说明 |
|---------|---------|---------|------|
| 日线行情 | `pro.daily()` | 120 | 获取日线行情数据（最常用） |
| IPO新股列表 | `pro.new_share()` | 120 | 新股申购数据 |
| 每日涨跌停 | `pro.stk_limit()` | 120 | 每日涨跌停价格 |
| LPR利率 | `pro.shibor_lpr()` | 120 | 贷款市场报价利率 |
| LIBOR利率 | `pro.libor()` | 120 | 伦敦银行间拆借利率 |
| HIBOR利率 | `pro.hibor()` | 120 | 香港银行间拆借利率 |

### 常见接口积分要求（供参考）

| 数据类型 | 接口方法 | 最低积分 | 调用限制 |
|---------|---------|---------|---------|
| 股票列表 | `pro.stock_basic()` | 2000 | 1次/小时 |
| 日线行情 | `pro.daily()` | 120 | 500次/分钟 |
| 周线行情 | `pro.weekly()` | 2000 | - |
| 月线行情 | `pro.monthly()` | 2000 | - |
| 财务指标 | `pro.fina_indicator()` | 2000 | - |
| 利润表 | `pro.income()` | 2000 | - |
| 资产负债表 | `pro.balancesheet()` | 2000 | - |
| 现金流量表 | `pro.cashflow()` | 2000 | - |
| 指数日线 | `pro.index_daily()` | 2000 | - |
| 指数成分 | `pro.index_weight()` | 2000 | - |
| 基金净值 | `pro.fund_nav()` | 2000 | - |
| GDP数据 | `pro.gdp()` | 2000 | - |
| CPI数据 | `pro.cpi()` | 2000 | - |
| Shibor | `pro.shibor()` | 2000 | - |

### 常见错误提示

| 错误信息 | 原因 | 解决方法 |
|---------|------|---------|
| `抱歉，您访问接口(xxx)频率超限` | 调用次数超过限制 | 等待一段时间后重试 |
| `抱歉，您没有访问该接口的权限` | 积分不足 | 提升积分或更换低积分要求的接口 |
| `抱歉，您的积分不足` | 积分不够调用该接口 | 提升积分 |

### 积分获取方式

1. **完善个人资料**：+200 分
2. **每日登录**：+1 分/天
3. **分享邀请**：+100 分/人
4. **贡献文档**：+100-500 分/篇
5. **社区活跃**：发帖、回答问题等

### 调用建议

1. **免费用户**：优先使用 `pro.daily()` 等低积分接口
2. **避免高频调用**：注意各接口的调用频次限制
3. **批量查询**：使用 `ts_code` 参数一次查询多只股票，减少调用次数
4. **缓存数据**：对不常变动的数据（如股票基本信息）进行本地缓存

## 参考资源

- **Tushare 官方文档**：https://tushare.pro/document/2
- **API 测试工具**：https://tushare.pro/document/1
- **积分与权限关系**：https://tushare.pro/document/1?doc_id=108
- **积分获取办法**：https://tushare.pro/document/1?doc_id=13
