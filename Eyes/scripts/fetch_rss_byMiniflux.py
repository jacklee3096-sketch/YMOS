#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YMOS RSS 数据获取工具（Miniflux 版）

【核心逻辑】
- 优先通过 Miniflux API 获取数据（当源配置了 miniflux_feed_id 时）
- 无 Miniflux feed_id 时，回退到原生 RSS 抓取
- 原生 RSS 抓取：由于 RSS 协议不支持时间范围参数，仍需本地过滤
- Miniflux API 支持 since 参数，可在服务端过滤

【数据源配置】
- 优先从 scripts/rss_sources.json 加载
- 次选 scripts/rss_sources_custom.json
- JSON 不存在时回退到内置默认源

【Miniflux 配置】
- 通过环境变量或配置文件设置：
  - MINIFLUX_BASE_URL: API 基础地址（如 http://localhost:8080，不含 /v1）
  - MINIFLUX_API_TOKEN: API Token
"""

import sys
import io
# 修复 Windows 控制台编码问题（安全重包装，避免 AttributeError）
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer is not None:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'buffer') and sys.stderr.buffer is not None:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except (AttributeError, TypeError):
        pass  # 某些环境（重定向管道、子进程）不支持重包装，静默跳过

import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import argparse
import json
import ssl
import sys
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ============================================================
# Miniflux 配置（可通过环境变量或 .env 文件覆盖）
# ============================================================
# 尝试从 .env 文件读取配置
# .env 文件位于项目根目录（F:\projects\YMOS-main\.env）
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts -> Eyes -> 项目根目录
ENV_FILE = PROJECT_ROOT / ".env"

def load_env_file():
    """从 .env 文件加载配置"""
    env_config = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_config[key.strip()] = value.strip()
    return env_config

# 加载 .env 配置
ENV_CONFIG = load_env_file()

# 优先级：命令行参数 > 环境变量 > .env 文件 > 默认值
# 注意：BASE_URL 是裸地址（不含 /v1），API 路径统一在代码内拼接
MINIFLUX_BASE_URL = os.environ.get("MINIFLUX_BASE_URL", "http://localhost:8080")
MINIFLUX_API_TOKEN = os.environ.get("MINIFLUX_API_TOKEN", ENV_CONFIG.get("MINIfLUX_API_Token", ""))

# ============================================================
# 内置默认源（当配置文件不存在时使用）
# ============================================================
FALLBACK_SOURCES = [
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "category": "美股", "priority": "high", "miniflux_feed_id": 15},
    {"name": "Bloomberg Tech", "url": "https://feeds.bloomberg.com/technology/news.rss", "category": "科技", "priority": "high", "miniflux_feed_id": 3},
    {"name": "CNBC Markets", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", "category": "美股", "priority": "high", "miniflux_feed_id": 21},
    {"name": "CNBC Finance", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "category": "宏观", "priority": "medium", "miniflux_feed_id": 11},
    {"name": "Seeking Alpha Picks", "url": "https://seekingalpha.com/tag/editors-picks.xml", "category": "深度洞察", "priority": "high", "miniflux_feed_id": 6},
    {"name": "Stratechery", "url": "https://stratechery.com/feed/", "category": "深度洞察", "priority": "high", "miniflux_feed_id": 2},
]


def load_sources(category_filter=None, config_path=None):
    """加载 RSS 源配置。
    
    Args:
        category_filter: 按分类过滤（如 "科技"）
        config_path: 指定配置文件路径（绝对路径或相对于 scripts/）
                       当指定时只加载该文件，不加载默认配置
    """
    script_dir = Path(__file__).resolve().parent
    sources = []

    # ===== 核心修复：config_path 优先只加载指定文件 =====
    if config_path:
        # 指定了配置文件路径，只加载该文件
        config_file = Path(config_path)
        # 转换为绝对路径（如果是相对路径则以 script_dir 为基准）
        if not config_file.is_absolute():
            config_file = script_dir / config_file
        
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                sources = config.get("sources", [])
                print(f"📂 从指定配置 [{config_file.name}] 加载 {len(sources)} 个源")
            except Exception as e:
                print(f"⚠️ 读取指定配置失败: {e}")
        else:
            print(f"⚠️ 指定配置文件不存在: {config_file}")
        
        # 指定配置时不再加载默认配置，直接返回
        if category_filter:
            sources = [s for s in sources if s.get("category") == category_filter]
            print(f"🔍 按分类 [{category_filter}] 过滤后: {len(sources)} 个源")
        return sources

    # ===== 未指定 config_path 时：只加载 rss_sources.json =====
    json_path = script_dir / "rss_sources.json"
    
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            sources = config.get("sources", [])
            print(f"📂 从 rss_sources.json 加载 {len(sources)} 个源")
        except Exception as e:
            print(f"⚠️ 读取 rss_sources.json 失败: {e}")
            sources = []

    # 回退到内置源
    if not sources:
        print("📂 无配置文件，使用内置源（6 个）")
        sources = FALLBACK_SOURCES

    if category_filter:
        sources = [s for s in sources if s.get("category") == category_filter]
        print(f"🔍 按分类 [{category_filter}] 过滤后: {len(sources)} 个源")

    return sources


def fetch_from_miniflux(feed_id, days=1, limit=50):
    """从 Miniflux API 获取数据"""
    # 计算时间过滤参数（Unix时间戳，秒）
    since = int(time.time() - days * 86400)
    
    # 统一拼接 /v1 路径，不用关心 BASE_URL 是否自带 /v1
    api_base = MINIFLUX_BASE_URL.rstrip("/")
    url = f"{api_base}/v1/feeds/{feed_id}/entries?published_after={since}&limit={limit}"
    
    headers = {
        "X-Auth-Token": MINIFLUX_API_TOKEN,
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"   ⚠️ Miniflux 权限不足 (403)")
        else:
            print(f"   ❌ HTTP 错误: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"   ❌ 网络错误: {e.reason}")
        return None
    except Exception as e:
        print(f"   ❌ 未知错误: {e}")
        return None

    items = []
    entries = data.get("entries", [])
    
    for entry in entries:
        # Miniflux 条目结构映射
        title = entry.get("title", "").strip() if entry.get("title") else ""
        url = entry.get("url", "").strip() if entry.get("url") else ""
        # 发布时间
        published_at = entry.get("published_at", "")
        
        # 内容摘要（content/summary 可能是字符串或字典）
        summary = ""
        content_obj = entry.get("content")
        summary_obj = entry.get("summary")
        
        if isinstance(content_obj, dict):
            summary = content_obj.get("value", "") or ""
        elif isinstance(content_obj, str):
            summary = content_obj
        
        if not summary and isinstance(summary_obj, dict):
            summary = summary_obj.get("value", "") or ""
        elif not summary and isinstance(summary_obj, str):
            summary = summary_obj
        
        # Tags（可能是字符串列表或字典列表）
        tags = entry.get("tags", [])
        categories = []
        if tags:
            if isinstance(tags, list) and len(tags) > 0:
                if isinstance(tags[0], dict):
                    categories = [tag.get("label", "") for tag in tags if tag.get("label")]
                elif isinstance(tags[0], str):
                    categories = [str(tag) for tag in tags]
        
        items.append({
            "title": title,
            "link": url,
            "pub_date": published_at,
            "description": summary[:500] if summary else "",  # 截断避免过长
        })

    return items


def fetch_rss_native(url, days=1):
    """从单个 RSS 源获取数据（原生方式，本地时间过滤）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }

    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            # 从 HTTP 响应头检测编码，回退到 utf-8
            content_type = response.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            raw_data = response.read()
            try:
                xml_content = raw_data.decode(charset)
            except (UnicodeDecodeError, LookupError):
                # 编码检测失败时尝试常见备用编码
                for fallback in ["utf-8", "gbk", "gb2312", "iso-8859-1", "latin-1"]:
                    try:
                        xml_content = raw_data.decode(fallback)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    print(f"   ❌ 无法解码 RSS 响应内容（尝试了多种编码）")
                    return None
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"   ⚠️ 源站限制 (403)，跳过")
            return "BLOCKED_403"
        else:
            print(f"   ❌ HTTP 错误: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"   ❌ 网络错误: {e.reason}")
        return None
    except Exception as e:
        print(f"   ❌ 未知错误 ({type(e).__name__}): {e}")
        return None

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        print(f"   ❌ XML 解析错误: {e}")
        return None

    channel = root.find("channel")
    if channel is None:
        # 尝试 Atom 格式
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            print("   ❌ 未找到 RSS channel 或 Atom entries")
            return None
        # Atom 格式解析
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        items = []
        for entry in entries:
            title = (entry.findtext("atom:title", "", ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            pub_date = (entry.findtext("atom:published", "", ns) or
                        entry.findtext("atom:updated", "", ns) or "").strip()
            summary = (entry.findtext("atom:summary", "", ns) or
                       entry.findtext("atom:content", "", ns) or "").strip()
            # 时间过滤（简单 ISO 解析）
            if pub_date:
                try:
                    parsed_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    if parsed_date < cutoff_time:
                        continue
                except ValueError:
                    pass
            categories = [cat.get("term", "") for cat in entry.findall("atom:category", ns) if cat.get("term")]
            items.append({
                "title": title, "link": link, "pub_date": pub_date,
                "description": summary,
            })
        return items

    # RSS 2.0 格式解析
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    for item in channel.findall("item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        description = item.findtext("description", "").strip()

        content = ""
        for child in item:
            if "encoded" in child.tag:
                content = (child.text or "").strip()
                break

        parsed_date = None
        if pub_date:
            try:
                parsed_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
            except ValueError:
                try:
                    parsed_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

        if parsed_date and parsed_date < cutoff_time:
            continue

        categories = [cat.text for cat in item.findall("category") if cat.text]
        items.append({
            "title": title, "link": link, "pub_date": pub_date,
            "description": description,
        })

    return items


def fetch_from_source(source, days=1):
    """从单个源获取数据（智能选择 Miniflux 或原生）"""
    feed_id = source.get("miniflux_feed_id")
    
    # 优先尝试 Miniflux
    if feed_id and feed_id != "null" and feed_id is not None:
        # 确保 feed_id 是整数
        try:
            feed_id = int(feed_id)
        except (ValueError, TypeError):
            pass
        else:
            items = fetch_from_miniflux(feed_id, days)
            if items is not None:
                return items, "miniflux"
    
    # 回退到原生 RSS
    url = source.get("url")
    if url:
        items = fetch_rss_native(url, days)
        return items, "native"
    
    return None, "none"


def fetch_all_sources(sources, days=1):
    """从所有配置的 RSS 源获取数据"""
    all_items = []
    success_count = 0
    fail_count = 0
    blocked_sources = []
    miniflux_count = 0
    native_count = 0

    for src in sources:
        name = src["name"]
        url = src["url"]
        category = src.get("category", "未分类")
        priority = src.get("priority", "medium")
        feed_id = src.get("miniflux_feed_id")

        # 显示数据来源
        if feed_id and feed_id != "null" and feed_id is not None:
            print(f"\n📡 [{name}] ({category}) [Miniflux #{feed_id}]")
        else:
            print(f"\n📡 [{name}] ({category}) [原生 RSS]")

        items, source_type = fetch_from_source(src, days)

        if items == "BLOCKED_403":
            blocked_sources.append(name)
            fail_count += 1
        elif items:
            for item in items:
                item["source_name"] = name
                item["source_category"] = category
                item["source_priority"] = priority
            all_items.extend(items)
            print(f"   ✅ 获取 {len(items)} 条 [{source_type}]")
            success_count += 1
            if source_type == "miniflux":
                miniflux_count += 1
            else:
                native_count += 1
        else:
            print(f"   ⚠️ 未获取到数据")
            fail_count += 1

    # 403 汇总提示
    if blocked_sources:
        print(f"\nℹ️ 本次被源站限制 (403) 的源: {len(blocked_sources)} 个")
        for name in blocked_sources:
            print(f"   - {name}")

    # 分类统计
    categories_summary = {}
    for item in all_items:
        cat = item.get("source_category", "未分类")
        categories_summary[cat] = categories_summary.get(cat, 0) + 1

    source_names = [s["name"] for s in sources]

    return {
        "sources": source_names,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "time_range_days": days,
        "count": len(all_items),
        "sources_ok": success_count,
        "sources_fail": fail_count,
        "sources_blocked_403": len(blocked_sources),
        "sources_via_miniflux": miniflux_count,
        "sources_via_native": native_count,
        "categories_summary": categories_summary,
        "data": all_items,
    }


def main():
    parser = argparse.ArgumentParser(
        description="YMOS RSS 数据获取工具 (Miniflux 版) - 优先通过 Miniflux API 获取"
    )
    parser.add_argument(
        "days", type=float, nargs="?", default=1,
        help="获取最近 N 天的数据（默认: 1）",
    )
    parser.add_argument(
        "--url", default=None,
        help="指定单个 RSS 源 URL（不指定则使用全部配置源）",
    )
    parser.add_argument(
        "--category", default=None,
        help="按分类过滤源（美股/宏观/科技/Crypto/深度洞察）",
    )
    parser.add_argument(
        "--config", default=None,
        help="自定义 RSS 配置文件路径（默认使用 rss_sources.json）",
    )
    parser.add_argument(
        "--output", default="financial_data.json",
        help="输出文件路径（默认: financial_data.json）",
    )
    parser.add_argument(
        "--miniflux-url", default=None,
        help="Miniflux API 基础地址（如 http://localhost:8080，不含 /v1，覆盖环境变量）",
    )
    parser.add_argument(
        "--miniflux-token", default=None,
        help="Miniflux API Token（覆盖环境变量）",
    )

    args = parser.parse_args()

    # 覆盖默认配置（BASE_URL 保持裸地址，不含 /v1）
    global MINIFLUX_BASE_URL, MINIFLUX_API_TOKEN
    if args.miniflux_url:
        MINIFLUX_BASE_URL = args.miniflux_url.rstrip("/")
    if args.miniflux_token:
        MINIFLUX_API_TOKEN = args.miniflux_token

    print("=" * 50)
    print("YMOS RSS 数据获取工具 (Miniflux 版)")
    print("=" * 50)
    print(f"📡 Miniflux: {MINIFLUX_BASE_URL}/v1")

    if args.url:
        # 单源模式（不支持 Miniflux，直接用原生）
        print(f"\n🚀 单源模式: {args.url}")
        items = fetch_rss_native(args.url, args.days)
        if items:
            result = {
                "source": args.url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "time_range_days": args.days,
                "count": len(items),
                "data": items,
            }
        else:
            result = None
    else:
        # 全源模式（支持分类过滤）
        sources = load_sources(category_filter=args.category, config_path=args.config)
        if not sources:
            print("❌ 无可用源")
            sys.exit(1)
        result = fetch_all_sources(sources, args.days)

    if result and result.get("count", 0) > 0:
        # 确保输出目录存在
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n💾 数据已保存: {args.output}")
        print(f"✅ 共获取 {result['count']} 条数据")

        # 来源统计
        miniflux_cnt = result.get("sources_via_miniflux", 0)
        native_cnt = result.get("sources_via_native", 0)
        if miniflux_cnt or native_cnt:
            print(f"📊 数据来源: Miniflux {miniflux_cnt} 个源, 原生 RSS {native_cnt} 个源")

        # 分类统计
        cat_summary = result.get("categories_summary", {})
        if cat_summary:
            print(f"\n📁 分类统计:")
            for cat, num in sorted(cat_summary.items()):
                print(f"   {cat}: {num} 条")
    else:
        print("\n⚠️ 未获取到数据，请检查网络连接和 RSS 源地址")
        sys.exit(1)


if __name__ == "__main__":
    main()