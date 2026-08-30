#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补齐历史交易股缺失的 K 线 → 合并进 cache/backtest_klines.json

背景：用户历史交割单涉及 185 只股票，但 K 线池（backtest_klines.json）只覆盖 35 只，
缺 150 只。本脚本用腾讯 fqkline 接口补抓「近期交易股」（2025-08 后仍活跃）的 500 根
前复权日 K，并同步提取腾讯权威证券名称（规避券商交割单名称列错位问题）。

用法：
    python scripts/fetch_missing_klines.py            # 补抓近期股
    python scripts/fetch_missing_klines.py --all      # 补抓全部缺失（含早期股）
"""
import os
import sys
import json
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402

REPO_ROOT = feed.REPO_ROOT
CACHE_DIR = feed.CACHE_DIR
KLINES_PATH = os.path.join(CACHE_DIR, "backtest_klines.json")
TRADES_PATH = os.path.join(CACHE_DIR, "trades_history.json")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _market_prefix(code):
    """证券代码 → 腾讯 market 前缀。"""
    if code.startswith("6"):
        return "sh"
    if code.startswith(("8", "4", "43", "92")):
        return "bj"   # 北交所(8/92) / 老三板(4/43)
    return "sz"       # 深市主板(0/2) + 创业板(3，含 300/301/302)


def fetch_kline(code, retries=3):
    """抓单只股票 500 根前复权日 K，返回 (kline, name)。失败返回 (None, None)。"""
    full = _market_prefix(code) + code
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={full},day,,,500,qfq")
    for attempt in range(retries):
        try:
            r = __import__("requests").get(url, headers=UA, timeout=30)
            d = r.json()
            node = d.get("data", {}).get(full, {}) or d.get("data", {})
            arr = node.get("qfqday", []) or node.get("day", [])
            if not arr:
                return None, None
            kline = [[row[0], float(row[1]), float(row[2]),
                      float(row[3]), float(row[4]), float(row[5])]
                     for row in arr if len(row) >= 6]
            name = ""
            qt = node.get("qt", {})
            qv = qt.get(full) or qt.get(code)
            if isinstance(qv, (list, tuple)) and len(qv) > 1:
                name = str(qv[1])
            if not kline:
                return None, None
            return kline, name
        except Exception as e:
            if attempt == retries - 1:
                print(f"  [{code}] 抓取失败: {e}")
            time.sleep(0.8)
    return None, None


def main():
    do_all = "--all" in sys.argv

    trades = json.load(open(TRADES_PATH, encoding="utf-8"))["trades"]
    kl = json.load(open(KLINES_PATH, encoding="utf-8"))
    stocks = kl.get("stocks", {})

    # 统计每只股票的最后交易日期
    last_date = {}
    name_from_broker = {}
    for t in trades:
        c = t.get("code")
        if not c:
            continue
        d = t.get("date", "")
        if d and (c not in last_date or d > last_date[c]):
            last_date[c] = d
        if c not in name_from_broker and t.get("name"):
            name_from_broker[c] = t["name"]

    # 缺失清单：全部历史股 - 已有池
    missing = [c for c in last_date if c not in stocks]
    if not do_all:
        missing = [c for c in missing if last_date.get(c, "") >= "2025-08-01"]

    print(f"待补抓 {len(missing)} 只缺失股票（{'全部' if do_all else '近期股'}）...")

    ok, fail = 0, 0
    for i, code in enumerate(sorted(missing), 1):
        kline, name = fetch_kline(code)
        if kline:
            stocks[code] = {
                "name": name or name_from_broker.get(code, code),
                "full_code": _market_prefix(code) + code,
                "kline": kline,
                "signals": {},
            }
            ok += 1
            print(f"  [{i}/{len(missing)}] {code} {stocks[code]['name']} "
                  f"{len(kline)}根 末={kline[-1][0]}")
        else:
            fail += 1
        time.sleep(0.15)  # 温和限速

    # 写回
    kl["stocks"] = stocks
    kl["count"] = len(stocks)
    kl["updated_at"] = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M:%S")
    with open(KLINES_PATH, "w", encoding="utf-8") as f:
        json.dump(kl, f, ensure_ascii=False)
    print(f"\n完成：成功 {ok} / 失败 {fail}，K 线池现有 {len(stocks)} 只")


if __name__ == "__main__":
    main()
