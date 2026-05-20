#!/usr/bin/env python3
"""
价格路由器（三源分流版 + mx-finance-data 首选）

路由规则（优先级顺序）：
  所有市场（优先 A股）
    ├─ 首选：mx-finance-data（东方财富，需 EM_API_KEY）
    │     └─ 失败/受限 → 回退到备选
    ├─ 备选：Tushare（A股专用，需 TUSHARE_TOKEN）
    │     └─ 失败/无KEY → 回退到兜底
    ├─ Finnhub（美股/Crypto，需 FINNHUB_API_KEY）
    │     └─ 失败/无KEY → 回退到兜底
    └─ 兜底：Yahoo（所有市场，无需 Key）

设计原则：
  - mx-finance-data 优先，获取最新价/收盘价（根据交易时段自动选择）
  - Yahoo 是零配置开箱即用的兜底，任何市场在 Key 缺失时都回退到 Yahoo
  - 有对应的 Key/Token 就走专用源，精度和稳定性更高
  - mx-finance-data 单次最多5个标的，超过时自动分批

2026-05-20 重构：新增 mx-finance-data 作为首选数据源
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
YMOS_ROOT = SCRIPTS_DIR.parents[1]   # Eyes/scripts → Eyes → YMOS
ROOT = SCRIPTS_DIR.parents[2]        # parent of YMOS（subprocess cwd）

sys.path.insert(0, str(SCRIPTS_DIR))
from env_loader import load_dotenv


# ── Crypto 符号归一化 ──────────────────────────────────────────────────────
# 状态机中统一写裸符号（BTC / ETH），路由器在调用数据源前自动转换
# - Finnhub crypto endpoint 需要交易所前缀（BINANCE:BTCUSDT）
# - Yahoo 需要 -USD 后缀（BTC-USD）
CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "DOT"}

CRYPTO_MAP_FINNHUB = {
    "BTC": "BINANCE:BTCUSDT",
    "ETH": "BINANCE:ETHUSDT",
    "SOL": "BINANCE:SOLUSDT",
    "DOGE": "BINANCE:DOGEUSDT",
    "XRP": "BINANCE:XRPUSDT",
    "ADA": "BINANCE:ADAUSDT",
    "AVAX": "BINANCE:AVAXUSDT",
    "DOT": "BINANCE:DOTUSDT",
}

CRYPTO_MAP_YAHOO = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "DOGE": "DOGE-USD",
    "XRP": "XRP-USD",
    "ADA": "ADA-USD",
    "AVAX": "AVAX-USD",
    "DOT": "DOT-USD",
}


def is_crypto(symbol: str) -> bool:
    return symbol.upper() in CRYPTO_SYMBOLS


def normalize_for_source(symbol: str, source: str) -> str:
    """将状态机中的 crypto 裸符号转换为数据源需要的格式。非 crypto 原样返回。"""
    upper = symbol.upper()
    if upper not in CRYPTO_SYMBOLS:
        return symbol
    if source == "finnhub":
        return CRYPTO_MAP_FINNHUB.get(upper, f"BINANCE:{upper}USDT")
    if source == "yahoo":
        return CRYPTO_MAP_YAHOO.get(upper, f"{upper}-USD")
    return symbol


def parse_symbols(raw: str) -> list[str]:
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def classify(symbol: str) -> str:
    """
    返回该 Ticker 优先走哪个数据源（不考虑 Key 是否存在）。
      'tushare' → A股（上交所 .SS / 深交所 .SZ）
      'finnhub' → 美股 / Crypto
      'yahoo'   → 港股（.HK），以及所有市场的兜底
    """
    if symbol.endswith((".SS", ".SZ", ".SH")):
        return "tushare"
    if symbol.endswith(".HK"):
        return "yahoo"
    # BTC/ETH 等 Crypto 及纯字母美股
    return "finnhub"


def run(cmd: list[str]) -> int:
    return subprocess.call(cmd, cwd=str(ROOT))


def is_trading_hours() -> bool:
    """判断当前是否在 A股交易时段内"""
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute
    
    # 上午：9:30-11:30
    morning = (hour == 9 and minute >= 30) or (10 <= hour <= 11)
    
    # 下午：13:00-15:00
    afternoon = 13 <= hour < 15
    
    return morning or afternoon


def try_mx_finance_data(symbols: list[str], output_dir: Path, date_tag: str) -> tuple[bool, Path | None]:
    """
    尝试用 mx-finance-data 获取价格数据。
    返回 (success, output_path)
    
    流程：
      1. 调用 mx-finance-data 获取 xlsx（输出到默认目录）
      2. 查找自动生成的 xlsx 文件
      3. 使用 parse_mx_output.py 解析 xlsx
      4. 合并结果并输出统一格式 JSON
    """
    mx_script = YMOS_ROOT / ".trae" / "skills" / "mx-finance-data" / "scripts" / "get_data.py"
    parse_script = SCRIPTS_DIR / "parse_mx_output.py"
    
    if not mx_script.exists():
        print("⏭ mx-finance-data 脚本不存在，跳过")
        return False, None
    
    em_key = os.getenv("EM_API_KEY", "")
    if not em_key:
        print("⏭ 未配置 EM_API_KEY，跳过 mx-finance-data")
        return False, None
    
    # mx-finance-data 默认输出目录
    mx_default_dir = ROOT / "miaoxiang" / "mx_finance_data"
    
    # 分批处理，每批最多5个
    batch_size = 5
    all_results = []
    success = True
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        print(f" mx-finance-data 批次 {i//batch_size + 1}: {batch}")
        
        # 构建查询语句
        query_str = "查询" + "、".join(batch) + "的最新价、涨跌幅、成交量、最高价、最低价、开盘价"
        
        # 解析后输出 json
        json_out = output_dir / f"price_scan_mx_batch{i//batch_size}_{date_tag}.json"
        
        # Step 1: 调用 mx-finance-data 获取 xlsx
        # mx-finance-data 会输出到默认目录，文件名格式为 mx_finance_data_{uuid}.xlsx
        cmd_get = [
            sys.executable,
            str(mx_script),
            query_str,
        ]
        
        code = run(cmd_get)
        if code != 0:
            print(f" mx-finance-data 批次 {i//batch_size + 1} 失败")
            success = False
            break
        
        # Step 2: 查找刚生成的 xlsx 文件
        mx_default_dir.mkdir(parents=True, exist_ok=True)
        xlsx_files = sorted(mx_default_dir.glob("mx_finance_data_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not xlsx_files:
            print(f" mx-finance-data 未生成 xlsx 文件")
            success = False
            break
        
        mx_out = xlsx_files[0]  # 取最新的文件
        print(f" 找到 mx-finance-data 输出: {mx_out}")
        
        # Step 3: 解析 xlsx 转换为 JSON
        cmd_parse = [
            sys.executable,
            str(parse_script),
            "--input", str(mx_out),
            "--output", str(json_out),
            "--symbols", ",".join(batch),
        ]
        
        code = run(cmd_parse)
        if code != 0:
            print(f" 解析 mx-finance-data 批次 {i//batch_size + 1} 失败")
            success = False
            break
        
        # 读取解析结果
        if json_out.exists():
            try:
                with open(json_out, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    all_results.extend(data.get("data", []))
            except Exception as e:
                print(f" 读取解析结果失败: {e}")
                success = False
                break
        else:
            print(f" 解析器未生成输出文件")
            success = False
            break
    
    if success and all_results:
        # 合并结果到主输出文件
        output_path = output_dir / f"price_scan_mx_{date_tag}.json"
        output = {
            "source": "mx-finance-data",
            "fetched_at": datetime.datetime.now().isoformat(),
            "data_type": "intraday" if is_trading_hours() else "close",
            "count": len(all_results),
            "symbols": symbols,
            "data": all_results,
        }
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f" mx-finance-data 成功，结果已保存到 {output_path}")
        return True, output_path
    
    return False, None


def main() -> None:
    load_dotenv()

    p = argparse.ArgumentParser(description="YMOS 价格路由器（mx-finance-data 首选）")
    p.add_argument("--symbols", required=True,
                   help="逗号分隔，如 AAPL,NIO,688008.SS,0700.HK")
    p.add_argument("--output-dir", default="Report/投资雷达/Raw_Data", help="输出目录")
    p.add_argument("--date-tag", default="", help="日期标签，如 20260316")
    p.add_argument("--finnhub-token", default="",
                   help="Finnhub Key（可选，也可通过 FINNHUB_API_KEY 环境变量传入）")
    p.add_argument("--tushare-token", default="",
                   help="Tushare Token（可选，也可通过 TUSHARE_TOKEN 环境变量传入）")
    args = p.parse_args()

    symbols = parse_symbols(args.symbols)
    if not symbols:
        raise SystemExit("symbols 不能为空")

    finnhub_key   = args.finnhub_token  or os.getenv("FINNHUB_API_KEY", "")
    tushare_token = args.tushare_token  or os.getenv("TUSHARE_TOKEN", "")

    # ── 分流 ────────────────────────────────────────────────────────────────
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = args.date_tag or datetime.datetime.now().strftime("%Y%m%d")

    # ── 步骤1：首选 mx-finance-data ────────────────────────────────────────
    a股_symbols = [s for s in symbols if classify(s) == "tushare"]
    
    if a股_symbols:
        mx_success, mx_output = try_mx_finance_data(a股_symbols, out_dir, date_tag)
        if mx_success:
            # mx-finance-data 成功，过滤掉已获取的 A股标的
            remaining_symbols = [s for s in symbols if s not in a股_symbols]
            a股_fetched = a股_symbols
        else:
            # mx-finance-data 失败，继续原有路由
            remaining_symbols = symbols
            a股_fetched = []
    else:
        remaining_symbols = symbols
        a股_fetched = []

    print(f"\n 价格路由分流结果：")
    print(f"   mx-finance-data ({len(a股_fetched)}): {a股_fetched or '—'}")

    # ── 步骤2：原有路由逻辑（备选 + 兜底）─────────────────────────────────
    
    finnhub_syms: list[str] = []
    tushare_syms: list[str] = []
    yahoo_syms:   list[str] = []

    for s in remaining_symbols:
        bucket = classify(s)
        if bucket == "finnhub":
            if finnhub_key:
                finnhub_syms.append(s)
            else:
                yahoo_syms.append(s)          # 无 Key → Yahoo 兜底
        elif bucket == "tushare":
            if tushare_token:
                tushare_syms.append(s)
            else:
                yahoo_syms.append(s)          # 无 Token → Yahoo 兜底
        else:  # "yahoo"
            yahoo_syms.append(s)

    out_dir = Path(args.output_dir).resolve()   # 转绝对路径，避免子进程 CWD 不一致
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = args.date_tag or "latest"

    print(f" 价格路由分流结果：")
    print(f"   Finnhub  ({len(finnhub_syms)}): {finnhub_syms or '—'}")
    print(f"   Tushare  ({len(tushare_syms)}): {tushare_syms or '—'}")
    print(f"   Yahoo    ({len(yahoo_syms)}): {yahoo_syms or '—'}")
    print()

    # ── Crypto 归一化：裸符号 → 数据源专用格式 ────────────────────────────
    finnhub_syms_norm = [normalize_for_source(s, "finnhub") for s in finnhub_syms]
    yahoo_syms_norm   = [normalize_for_source(s, "yahoo")   for s in yahoo_syms]

    if finnhub_syms_norm != finnhub_syms or yahoo_syms_norm != yahoo_syms:
        print(f" Crypto 归一化：")
        if finnhub_syms_norm != finnhub_syms:
            print(f"   Finnhub: {finnhub_syms} → {finnhub_syms_norm}")
        if yahoo_syms_norm != yahoo_syms:
            print(f"   Yahoo:   {yahoo_syms} → {yahoo_syms_norm}")
        print()

    # ── Finnhub ─────────────────────────────────────────────────────────
    if finnhub_syms_norm:
        out = out_dir / f"price_scan_finnhub_{date_tag}.json"
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "fetch_price_api.py"),
            "--quotes-only",
            "--symbols", ",".join(finnhub_syms_norm),
            "--output", str(out),
            "--token", finnhub_key,
        ]
        code = run(cmd)
        if code != 0:
            print(f" Finnhub 调用失败（exit {code}），对应 ticker 可能无价格数据")

    # ── Tushare（A股，mx-finance-data 失败时使用）───────────────────────
    if tushare_syms:
        out = out_dir / f"price_scan_tushare_{date_tag}.json"
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "fetch_price_tushare.py"),
            "--symbols", ",".join(tushare_syms),
            "--token", tushare_token,
            "--output", str(out),
        ]
        code = run(cmd)
        if code != 0:
            print(f" Tushare 调用失败（exit {code}）")

    # ── Yahoo（港股 + 兜底）─────────────────────────────────────────────
    if yahoo_syms_norm:
        out = out_dir / f"price_scan_yahoo_{date_tag}.json"
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "fetch_price_yahoo.py"),
            "--symbols", ",".join(yahoo_syms_norm),
            "--output", str(out),
        ]
        code = run(cmd)
        if code != 0:
            print(f" Yahoo 调用失败（exit {code}），对应 ticker 可能无价格数据")

    print(" 路由完成")


if __name__ == "__main__":
    main()