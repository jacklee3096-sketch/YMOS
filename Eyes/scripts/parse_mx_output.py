#!/usr/bin/env python3
"""
mx-finance-data 输出解析器

功能：
  - 解析 mx-finance-data 返回的 xlsx 文件
  - 转换为统一的价格数据格式（与 Tushare/Yahoo 输出一致）
  - 支持盘中/盘后自动识别（最新价 vs 收盘价）

mx-finance-data 返回的 xlsx 格式：
  第一列：指标名称（成交量、最低价、最新价、最高价、涨跌幅、开盘价）
  后续列：各股票的数据（列名格式：股票名(代码.SZ)）

输出格式：
{
  "source": "mx-finance-data",
  "fetched_at": "2026-05-20T10:30:00+08:00",
  "data_type": "intraday" | "close",
  "count": 5,
  "symbols": ["002229.SZ", ...],
  "data": [
    {
      "symbol": "002229.SZ",
      "ok": true,
      "last_close": 16.75,
      "last_high": 16.98,
      "last_low": 16.20,
      "last_open": 16.50,
      "last_volume": 396900,
      "pct_chg": -1.23,
      "data_type": "intraday"
    }
  ]
}
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print(" 需要安装 pandas：pip install pandas openpyxl")
    sys.exit(1)


def is_trading_hours() -> bool:
    """判断当前是否在 A股交易时段内"""
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute
    
    morning = (hour == 9 and minute >= 30) or (10 <= hour <= 11)
    afternoon = 13 <= hour < 15
    
    return morning or afternoon


def parse_stock_code(col_name: str) -> str:
    """从列名中提取股票代码，如 '鸿博股份(002229.SZ)' -> '002229.SZ'"""
    match = re.search(r'\((\d{6}\.[SSZ]{2})\)', col_name)
    if match:
        return match.group(1)
    return col_name


def parse_mx_xlsx(xlsx_path: Path) -> list[dict]:
    """解析 mx-finance-data 返回的 xlsx 文件"""
    try:
        df = pd.read_excel(xlsx_path, engine="openpyxl", header=None)
    except Exception as e:
        print(f" 读取 xlsx 文件失败: {e}")
        return []
    
    results = []
    is_intraday = is_trading_hours()
    
    # 第一行是列名（时间、股票1、股票2...）
    # 后续行是指标数据
    if df.shape[0] < 2 or df.shape[1] < 2:
        print(" xlsx 数据格式不正确")
        return []
    
    # 获取股票列（从第二列开始）
    stock_cols = []
    for col in range(1, df.shape[1]):
        col_name = str(df.iloc[0, col])
        code = parse_stock_code(col_name)
        if code:
            stock_cols.append((col, code))
    
    # 提取指标数据
    # 指标行索引：成交量、最低价、最新价、最高价、涨跌幅、开盘价
    indicator_map = {}
    for row in range(1, df.shape[0]):
        indicator_name = str(df.iloc[row, 0]).strip()
        if indicator_name:
            indicator_map[indicator_name] = row
    
    # 为每个股票生成记录
    for col, symbol in stock_cols:
        record = {
            "symbol": symbol,
            "ok": True,
            "last_close": 0.0,
            "last_high": 0.0,
            "last_low": 0.0,
            "last_open": 0.0,
            "last_volume": 0.0,
            "pct_chg": 0.0,
            "data_type": "intraday" if is_intraday else "close",
        }
        
        # 提取各指标值
        if "最新价" in indicator_map:
            val = df.iloc[indicator_map["最新价"], col]
            record["last_close"] = float(val) if val else 0.0
        
        if "最高价" in indicator_map:
            val = df.iloc[indicator_map["最高价"], col]
            record["last_high"] = float(val) if val else 0.0
        
        if "最低价" in indicator_map:
            val = df.iloc[indicator_map["最低价"], col]
            record["last_low"] = float(val) if val else 0.0
        
        if "开盘价" in indicator_map:
            val = df.iloc[indicator_map["开盘价"], col]
            record["last_open"] = float(val) if val else 0.0
        
        if "成交量" in indicator_map:
            val = df.iloc[indicator_map["成交量"], col]
            record["last_volume"] = parse_volume(val)
        
        if "涨跌幅" in indicator_map:
            val = str(df.iloc[indicator_map["涨跌幅"], col]).replace('%', '')
            record["pct_chg"] = float(val) if val else 0.0
        
        results.append(record)
    
    return results


def parse_volume(val: any) -> float:
    """解析成交量，支持单位转换"""
    val = str(val).strip()
    if not val:
        return 0.0
    
    try:
        # 处理带单位的成交量
        if '亿' in val:
            return float(val.replace('亿', '')) * 100000000
        elif '万' in val:
            return float(val.replace('万', '')) * 10000
        else:
            return float(val)
    except:
        return 0.0


def main() -> None:
    p = argparse.ArgumentParser(description="mx-finance-data 输出解析器")
    p.add_argument("--input", required=True, help="输入 xlsx 文件路径")
    p.add_argument("--output", required=True, help="输出 json 文件路径")
    p.add_argument("--symbols", help="原始符号列表（逗号分隔）")
    args = p.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if not input_path.exists():
        print(f" 输入文件不存在: {input_path}")
        sys.exit(1)
    
    # 解析 xlsx
    data = parse_mx_xlsx(input_path)
    
    # 提取实际解析出的股票代码
    actual_symbols = [r["symbol"] for r in data if r["ok"]]
    
    # 构建输出
    output = {
        "source": "mx-finance-data",
        "fetched_at": datetime.datetime.now().isoformat(),
        "data_type": "intraday" if is_trading_hours() else "close",
        "count": len(data),
        "symbols": actual_symbols,
        "data": data,
    }
    
    # 写入输出文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f" 解析完成，输出到: {output_path}")
    print(f" 解析到 {len(data)} 条记录")
    print(f" 股票代码: {actual_symbols}")


if __name__ == "__main__":
    main()