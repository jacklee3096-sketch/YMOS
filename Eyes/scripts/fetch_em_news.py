#!/usr/bin/env python3
"""
东方财富妙想 A 股持仓个股新闻拉取脚本

策略说明（2026-04 新增）：
  仅对【持仓状态机】中的 A 股标的（.SZ/.SH）拉取新闻，精准匹配持仓。
  免费额度：100次/天，每次最多 20 只股票。

接口限制：
  - 免费用户 100次/天，连续活跃用户 300次/天
  - 单次查询最多 20 只股票
  - 查询时间范围不超过 1 年
  - Watchlist 不拉取（优先级低，节省额度）

用法：
  python3 Eyes/scripts/fetch_em_news.py \
    --hours 24 \
    --output "Eyes/市场洞察/Raw_Data/YYYY-MM/em_news_YYYYMMDD.json"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parents[1]  # Eyes/scripts → Eyes → YMOS

sys.path.insert(0, str(SCRIPTS_DIR))
from env_loader import load_dotenv

# 触发 P15 深度分析的关键词（中文）
P15_KEYWORDS = {
    # 财报相关
    "财报", "业绩", "营收", "利润", "指引", "盈利", "亏损", "同比增长", "环比增长",
    # 资本运作
    "并购", "收购", "重组", "定增", "配股", "发行", "上市",
    # 风险事件
    "退市", "ST", "处罚", "立案", "调查", "诉讼", "仲裁", "被执行",
    # 重大合作
    "合作", "签约", "中标", "战略", "合资",
    # 股权变动
    "增持", "减持", "回购", "股权激励", "限售股", "解禁",
    # 评级变动
    "评级", "上调", "下调", "买入", "卖出", "持有",
}


# ── Ticker 提取 ────────────────────────────────────────────────────────────

def extract_tickers_from_state_machine(filepath: Path, cn_only: bool = True) -> set[str]:
    """
    从 Markdown 状态机表格中提取 Ticker 列。
    cn_only=True 时只返回 A 股（.SH/.SZ 后缀）。
    """
    if not filepath.exists():
        return set()

    text = filepath.read_text(encoding="utf-8")
    tickers: set[str] = set()
    in_table = False
    ticker_col_idx = -1

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            in_table = False
            continue

        cols = [c.strip() for c in line.split("|") if c.strip()]

        if not in_table:
            for i, col in enumerate(cols):
                if col.lower() in ("ticker", "代码", "标的"):
                    ticker_col_idx = i
                    in_table = True
                    break
            continue

        if all(c.replace("-", "").replace(":", "") == "" for c in cols):
            continue

        if 0 <= ticker_col_idx < len(cols):
            val = cols[ticker_col_idx].strip().upper()
            if val and not val.startswith(":") and val != "---":
                if cn_only:
                    # A 股：.SZ 深圳、.SH 上海
                    if ".SZ" in val or ".SH" in val or ".SH" in val:
                        # 去掉后缀，只保留数字代码
                        ticker = val.replace(".SZ", "").replace(".SH", "").replace(".SH", "")
                        if ticker.isdigit() and len(ticker) == 6:
                            tickers.add(ticker)
                    elif val.isdigit() and len(val) == 6:
                        # 无后缀的直接数字代码
                        tickers.add(val)
                else:
                    tickers.add(val)

    return tickers


def load_holding_tickers_cn() -> list[str]:
    """仅从【持仓状态机】加载 A 股 Ticker（Watchlist 不拉个股新闻）。"""
    holding_path = ROOT / "持仓与关注" / "持仓_状态机.md"
    tickers = sorted(extract_tickers_from_state_machine(holding_path, cn_only=True))
    if tickers:
        print(f"[INFO] 持仓 A 股 ticker（将拉取个股新闻）: {', '.join(tickers)}")
    else:
        print(f"[WARN] 未从持仓状态机中找到 A 股 ticker，跳过个股新闻拉取。")
    return tickers


# ── API 请求 ───────────────────────────────────────────────────────────────

def fetch_em_news(api_key: str, stock_codes: list[str], hours: int = 24) -> list[dict]:
    """
    调用东方财富妙想 mx-finance-search API 获取个股新闻。
    stock_codes: 股票代码列表
    hours: 回溯小时数
    """
    if not stock_codes:
        return []

    import uuid

    # 新的正确 API 端点（mx-finance-search）
    url = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/searchNews"

    all_results = []

    # 每次查询一只股票
    for code in stock_codes:
        # 构造查询语句
        query = f"{code}"

        # 请求体（符合 mx-finance-search 接口规范）
        payload = {
            "query": query,
            "toolContext": {
                "callId": f"call_{uuid.uuid4().hex[:8]}"
            }
        }

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "em_api_key": api_key,  # 注意：小写
            "User-Agent": "YMOS/2.0"
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))

                # 解析新接口返回格式
                # {"data": {"llmSearchResponse": {"data": [...]}}}
                if result.get("code") == 200 or result.get("status") == 0:
                    llm_data = result.get("data", {}).get("llmSearchResponse", {})
                    items = llm_data.get("data", [])
                    for item in items:
                        # 标记所属股票
                        item["ticker"] = code
                    all_results.extend(items)
                else:
                    msg = result.get('message', result.get('msg', '未知错误'))
                    print(f"  [WARN] {code}: {msg}")

        except urllib.error.HTTPError as e:
            print(f"  [ERROR] HTTP {e.code}: {e.reason}")
        except Exception as e:
            print(f"  [ERROR] 请求失败: {e}")

        # 避免超过速率限制
        time.sleep(0.3)

    return all_results


# ── 处理与去重 ──────────────────────────────────────────────────────────

def enrich_article(item: dict, ticker: str, cutoff_ts: float) -> dict | None:
    """给单条新闻打标签，过滤掉超时间窗口的条目。"""
    # 新 API 返回的字段：title, content, date, source 等
    # date 格式如 "2026-04-08 16:44:13"
    date_str = item.get("date", "")
    ts = 0
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            ts = dt.timestamp()
        except:
            ts = 0

    if ts < cutoff_ts:
        return None

    headline = item.get("title", "")
    summary = item.get("content", "") or item.get("digest", "")
    text = (headline + " " + summary).lower()

    return {
        "ticker": ticker,
        "datetime_ts": ts,
        "datetime_readable": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else date_str,
        "source": item.get("source", "东方财富"),
        "headline": headline,
        "summary": summary[:500] if summary else "",
        "url": item.get("jumpUrl", item.get("url", "")),
        "p15_trigger": any(kw in text for kw in P15_KEYWORDS),
    }


def deduplicate(articles: list[dict]) -> list[dict]:
    """headline 前 40 字符相同视为重复，保留最早一条。"""
    seen: dict[str, dict] = {}
    for art in sorted(articles, key=lambda x: x.get("datetime_ts", 0)):
        key = re.sub(r"\s+", " ", art.get("headline", "")[:40].lower()).strip()
        if key and key not in seen:
            seen[key] = art
    return sorted(seen.values(), key=lambda x: x.get("datetime_ts", 0), reverse=True)


# ── 主函数 ─────────────────────────────────────────────────────────────────

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="东方财富妙想 A 股持仓个股新闻拉取"
    )
    parser.add_argument("--output", default="em_news.json", help="输出文件路径")
    parser.add_argument("--hours", type=int, default=24, help="回溯小时数，默认 24")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("EM_API_KEY", ""),
        help="东方财富妙想 API Key，也可通过环境变量 EM_API_KEY 传入",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("[WARN] 未提供东方财富妙想 API Key，跳过 A 股新闻拉取。")
        print("   如需启用，请在 .env 中配置 EM_API_KEY")
        sys.exit(0)

    holding_tickers = load_holding_tickers_cn()
    if not holding_tickers:
        print("[WARN] 无持仓 A 股标的，退出。")
        sys.exit(0)

    # API 限制：每次查询 1 只股票
    batch_size = 1
    ticker_batches = [
        holding_tickers[i:i + batch_size]
        for i in range(0, len(holding_tickers), batch_size)
    ]

    now_utc = datetime.now(timezone.utc)
    cutoff_ts = (now_utc - timedelta(hours=args.hours)).timestamp()

    print(f"[INFO] 拉取 A 股持仓新闻（过去 {args.hours}h）")
    print(f"   [WARN] 免费额度：100次/天，每次最多 20 只股票")
    print(f"   [INFO] 当前持仓 {len(holding_tickers)} 只，分 {len(ticker_batches)} 批请求")

    all_articles: list[dict] = []
    ticker_counts: dict[str, int] = {}

    for batch_idx, batch in enumerate(ticker_batches):
        print(f"  → 批次 {batch_idx + 1}/{len(ticker_batches)}: {', '.join(batch)}...", end=" ", flush=True)

        raw = fetch_em_news(args.api_key, batch, args.hours)
        enriched = []
        for item in raw:
            # 从 fetch_em_news 返回的数据中获取股票代码
            stock_code = item.get("ticker", "")
            if stock_code:
                enriched_item = enrich_article(item, stock_code, cutoff_ts)
                if enriched_item:
                    enriched.append(enriched_item)

        # 统计各股票的新闻数量
        for item in enriched:
            ticker = item.get("ticker", "")
            if ticker:
                if ticker not in ticker_counts:
                    ticker_counts[ticker] = 0
                ticker_counts[ticker] += 1

        all_articles.extend(enriched)
        print(f"{len(enriched)} 条")

        # 避免超过速率限制
        if batch_idx < len(ticker_batches) - 1:
            time.sleep(0.5)

    # 去重（跨标的同一事件只保留一条）
    deduped = deduplicate(all_articles)
    p15_count = sum(1 for a in deduped if a.get("p15_trigger"))

    # 统计各 ticker 的新闻数量
    ticker_news_counts: dict[str, int] = {}
    for art in deduped:
        t = art.get("ticker", "")
        ticker_news_counts[t] = ticker_news_counts.get(t, 0) + 1

    output = {
        "meta": {
            "source": "EastMoney EM API",
            "mode": "holdings_only",
            "hours_back": args.hours,
            "date_range": f"过去 {args.hours} 小时",
            "generated_at": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
            "holding_tickers": holding_tickers,
            "note": "Watchlist 不拉个股新闻（节省 API 额度）",
            "rate_limit_note": "免费用户 100次/天，每次最多 20 只",
            "counts": {
                "total_raw": sum(ticker_counts.values()) if ticker_counts else len(all_articles),
                "after_dedup": len(deduped),
                "p15_trigger": p15_count,
                "by_ticker": ticker_news_counts,
            },
        },
        "articles": deduped,
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVE] 已保存：{args.output}")
    print(f"   总计：{len(deduped)} 条（去重后）| 其中 p15_trigger={p15_count} 条建议深度分析")


if __name__ == "__main__":
    main()