#!/usr/bin/env python3
"""
YMOS 统一价格数据路由器。

优先用 mx-finance-data（东方财富）；
备选方案：Finnhub（美股/港股）、Tushare（A 股）、Yahoo Finance。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
YMOS_ROOT = SCRIPTS_DIR.parent.parent

sys.path.insert(0, str(SCRIPTS_DIR))
from env_loader import load_dotenv
from runtime_paths import repo_paths

PATHS = repo_paths(YMOS_ROOT)


def is_trading_hours() -> bool:
    """判断当前是否在 A 股交易时段内"""
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute

    morning = (hour == 9 and minute >= 30) or (10 <= hour <= 11)
    afternoon = 13 <= hour < 15

    return morning or afternoon


def classify(symbol: str) -> str:
    """简单分类：tushare（A 股）、finnhub（港/美）"""
    if symbol.endswith((".SS", ".SZ")):
        return "tushare"
    if re.match(r"^\d{5}$", symbol):  # 港股五位数
        return "finnhub"
    if re.match(r"^\d{4}$", symbol):  # 港股四位数
        return "finnhub"
    return "finnhub"


def parse_symbols(s: str) -> list[str]:
    """解析逗号分隔的字符串为 ticker 列表"""
    return [x.strip().upper() for x in s.split(",") if x.strip()]


def try_mx_finance_data(symbols: list[str], output_dir: Path, date_tag: str, output_path: Path | None = None) -> tuple[bool, Path | None]:
    """
    尝试用 mx-finance-data 获取价格数据。
    返回 (success, output_path)
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
    mx_default_dir = YMOS_ROOT / "miaoxiang" / "mx_finance_data"

    # 分批处理，每批最多3个（避免批量查询时数据缺失）
    batch_size = 3
    all_results = []
    success = True
    temp_files = []  # 记录临时文件，最后清理

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        print(f" mx-finance-data 批次 {i//batch_size + 1}: {batch}")

        # 构建查询语句
        query_str = "查询" + "、".join(batch) + "的最新价、涨跌幅、成交量、最高价、最低价、开盘价"

        # Step 1: 调用 mx-finance-data 获取 xlsx
        cmd = [
            sys.executable, str(mx_script),
            "--query", query_str
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(YMOS_ROOT),
                capture_output=True,
                text=True,
                timeout=120
            )
        except subprocess.TimeoutExpired:
            print(" mx-finance-data 超时")
            success = False
            break

        if proc.returncode != 0:
            print(f" mx-finance-data 批次 {i//batch_size + 1} 失败")
            print(f"  stderr: {proc.stderr}")
            success = False
            break

        # Step 2: 查找刚生成的 xlsx 文件
        mx_default_dir.mkdir(parents=True, exist_ok=True)
        xlsx_files = sorted(mx_default_dir.glob("mx_finance_data_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)

        if not xlsx_files:
            print(f" mx-finance-data 未生成 xlsx 文件")
            success = False
            break

        mx_out = xlsx_files[0]
        print(f" 找到 mx-finance-data 输出: {mx_out}")
        temp_files.append(mx_out)

        # Step 3: 解析 xlsx 转换为 JSON（使用临时文件，完成后删除）
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            temp_json_out = Path(f.name)
        
        temp_files.append(temp_json_out)

        cmd_parse = [
            sys.executable,
            str(parse_script),
            "--input", str(mx_out),
            "--output", str(temp_json_out),
            "--symbols", ",".join(batch),
        ]

        code = subprocess.call(cmd_parse)
        if code != 0:
            print(f" 解析 mx-finance-data 批次 {i//batch_size + 1} 失败")
            success = False
            break

        # 读取解析结果
        if temp_json_out.exists():
            try:
                with open(temp_json_out, 'r', encoding='utf-8') as f:
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

    # 清理临时文件
    for temp_file in temp_files:
        try:
            if temp_file.exists():
                temp_file.unlink()
        except Exception as e:
            print(f"  清理临时文件失败 {temp_file}: {e}")

    if success and all_results:
        # 合并结果到主输出文件
        # 如果传入了完整路径则使用，否则自动生成
        final_output_path = output_path or (output_dir / f"price_scan_mx_{date_tag}.json")
        output = {
            "source": "mx-finance-data",
            "fetched_at": datetime.datetime.now().isoformat(),
            "data_type": "intraday" if is_trading_hours() else "close",
            "count": len([r for r in all_results if r.get("ok", False)]),
            "symbols": symbols,
            "data": all_results,
        }
        final_output_path.parent.mkdir(parents=True, exist_ok=True)
        final_output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f" mx-finance-data 成功，结果已保存到 {final_output_path}")
        return True, final_output_path

    return False, None


def try_finnhub(symbols: list[str], output_dir: Path, date_tag: str, token: str) -> tuple[bool, Path | None]:
    """备选：用 Finnhub 获取美股/港股价格"""
    if not token:
        return False, None

    from finnhub import Client
    finnhub = Client(api_key=token)

    results = []
    for symbol in symbols:
        try:
            quote = finnhub.quote(symbol=symbol)
            last = quote.get("c", 0)
            pct = quote.get("dp", 0)
            results.append({
                "symbol": symbol,
                "ok": last != 0,
                "last_close": last,
                "last_high": quote.get("h", 0),
                "last_low": quote.get("l", 0),
                "last_open": quote.get("o", 0),
                "last_volume": 0,
                "pct_chg": pct,
                "data_type": "intraday" if is_trading_hours() else "close"
            })
            time.sleep(0.1)
        except Exception as e:
            print(f"  Finnhub {symbol} 获取失败: {e}")
            results.append({
                "symbol": symbol,
                "ok": False,
                "last_close": 0,
                "last_high": 0,
                "last_low": 0,
                "last_open": 0,
                "last_volume": 0,
                "pct_chg": 0,
                "data_type": "intraday" if is_trading_hours() else "close"
            })

    if results:
        output_path = output_dir / f"price_scan_fh_{date_tag}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            "source": "finnhub",
            "fetched_at": datetime.datetime.now().isoformat(),
            "data_type": "intraday" if is_trading_hours() else "close",
            "count": len([r for r in results if r["ok"]]),
            "symbols": symbols,
            "data": results
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, output_path

    return False, None


def try_tushare(symbols: list[str], output_dir: Path, date_tag: str, token: str) -> tuple[bool, Path | None]:
    """备选：用 Tushare 获取 A 股价格（兼容老流程）"""
    if not token:
        return False, None

    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api()

    results = []

    for s in symbols:
        try:
            # 去掉后缀
            code = s.replace(".SZ", "").replace(".SS", "")
            # 用最简单的方式获取
            df = ts.get_realtime_quotes(code)
            if not df.empty:
                price = float(df["price"].iloc[0])
                pre_close = float(df["pre_close"].iloc[0])
                pct = ((price - pre_close) / pre_close) * 100 if pre_close else 0
                results.append({
                    "symbol": s,
                    "ok": True,
                    "last_close": price,
                    "last_high": float(df["high"].iloc[0]),
                    "last_low": float(df["low"].iloc[0]),
                    "last_open": float(df["open"].iloc[0]),
                    "last_volume": float(df["volume"].iloc[0]) / 100,
                    "pct_chg": round(pct, 2),
                    "data_type": "intraday" if is_trading_hours() else "close"
                })
            else:
                results.append({
                    "symbol": s,
                    "ok": False,
                    "last_close": 0,
                    "last_high": 0,
                    "last_low": 0,
                    "last_open": 0,
                    "last_volume": 0,
                    "pct_chg": 0,
                    "data_type": "intraday" if is_trading_hours() else "close"
                })
        except Exception as e:
            print(f"  Tushare {s} 获取失败: {e}")
            results.append({
                "symbol": s,
                "ok": False,
                "last_close": 0,
                "last_high": 0,
                "last_low": 0,
                "last_open": 0,
                "last_volume": 0,
                "pct_chg": 0,
                "data_type": "intraday" if is_trading_hours() else "close"
            })

    if results:
        output_path = output_dir / f"price_scan_ts_{date_tag}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            "source": "tushare",
            "fetched_at": datetime.datetime.now().isoformat(),
            "data_type": "intraday" if is_trading_hours() else "close",
            "count": len([r for r in results if r["ok"]]),
            "symbols": symbols,
            "data": results
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, output_path

    return False, None


def try_yahoo(symbols: list[str], output_dir: Path, date_tag: str) -> tuple[bool, Path | None]:
    """备选：用 Yahoo Finance 获取价格（通用兜底）"""
    try:
        import yfinance as yf
    except ImportError:
        print("⏭ 未安装 yfinance，跳过 Yahoo Finance")
        return False, None

    results = []

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                last = hist["Close"].iloc[-1]
                results.append({
                    "symbol": symbol,
                    "ok": True,
                    "last_close": float(last),
                    "last_high": float(hist["High"].iloc[-1]),
                    "last_low": float(hist["Low"].iloc[-1]),
                    "last_open": float(hist["Open"].iloc[-1]),
                    "last_volume": float(hist["Volume"].iloc[-1]),
                    "pct_chg": 0,
                    "data_type": "close"
                })
            else:
                results.append({
                    "symbol": symbol,
                    "ok": False,
                    "last_close": 0,
                    "last_high": 0,
                    "last_low": 0,
                    "last_open": 0,
                    "last_volume": 0,
                    "pct_chg": 0,
                    "data_type": "close"
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"  Yahoo {symbol} 获取失败: {e}")
            results.append({
                "symbol": symbol,
                "ok": False,
                "last_close": 0,
                "last_high": 0,
                "last_low": 0,
                "last_open": 0,
                "last_volume": 0,
                "pct_chg": 0,
                "data_type": "close"
            })

    if results:
        output_path = output_dir / f"price_scan_yf_{date_tag}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({
            "source": "yahoo",
            "fetched_at": datetime.datetime.now().isoformat(),
            "data_type": "intraday" if is_trading_hours() else "close",
            "count": len([r for r in results if r["ok"]]),
            "symbols": symbols,
            "data": results
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, output_path

    return False, None


def main() -> None:
    load_dotenv()

    p = argparse.ArgumentParser(description="YMOS 价格路由器（mx-finance-data 首选）")
    p.add_argument("--symbols", required=True,
                   help="逗号分隔，如 AAPL,NIO,688008.SS,0700.HK")
    p.add_argument("--output-dir", default="Report/投资雷达/Raw_Data", help="输出目录")
    p.add_argument("--output", default="", help="完整输出文件路径（优先于 --output-dir）")
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

    # ── 处理输出路径 ────────────────────────────────────────────────────────
    # 如果指定了完整输出路径，则提取目录和文件名
    final_output_path = Path(args.output).resolve() if args.output else None
    
    # ── 步骤1：首选 mx-finance-data ────────────────────────────────────────
    a股_symbols = [s for s in symbols if classify(s) == "tushare"]

    if a股_symbols:
        mx_success, mx_out = try_mx_finance_data(a股_symbols, out_dir, date_tag, final_output_path)
        if mx_success:
            print(f" 路由完成，数据保存到: {mx_out}")
            raise SystemExit(0)
        else:
            print(" mx-finance-data 失败，尝试备选方案")
            # 单独走 Tushare 备选
            ts_success, ts_out = try_tushare(a股_symbols, out_dir, date_tag, tushare_token)
            if ts_success and final_output_path:
                import shutil
                shutil.copy(ts_out, final_output_path)

    # ── 步骤2：备选 Finnhub / Yahoo ────────────────────────────────────────
    # 非 A 股用 Finnhub 或 Yahoo 兜底
    other_symbols = [s for s in symbols if classify(s) == "finnhub"]
    all_others_success = False
    all_others_path = None
    if other_symbols:
        # Finnhub
        fh_success, fh_out = try_finnhub(other_symbols, out_dir, date_tag, finnhub_key)
        if fh_success:
            all_others_success = True
            all_others_path = fh_out
        else:
            # Yahoo
            yf_success, yf_out = try_yahoo(other_symbols, out_dir, date_tag)
            if yf_success:
                all_others_success = True
                all_others_path = yf_out
    if final_output_path and all_others_path and not (a股_symbols and mx_success):
        import shutil
        shutil.copy(all_others_path, final_output_path)

    # ── 报告分流结果 ─────────────────────────────────────────────────────────
    print("\n 价格路由分流结果：")
    print(f"   mx-finance-data ({len(a股_symbols)}): {a股_symbols or '—'}")

    print("\n 价格路由分流结果：")
    print(f"   Finnhub  ({len(other_symbols)}): {other_symbols or '—'}")
    print(f"   Tushare  ({len(a股_symbols)}): {a股_symbols or '—'}")
    print(f"   Yahoo    ({len(other_symbols)}): {other_symbols or '—'}")

    print("\n 路由完成")


if __name__ == "__main__":
    main()
