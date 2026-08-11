#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性拉取 8/11 持仓股前复权日K，写入 cache/backtest_klines.json（仅持仓股，不含扫描池）。"""
import os
import sys
import json
import time
import datetime as dt
import urllib.request
import urllib.error

ROOT = "/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard"
CACHE_DIR = os.path.join(ROOT, "cache")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _full(code):
    s = code.strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.startswith("6"):
        return f"sh{s}"
    return f"sz{s}"


# code(无前缀) -> name
TARGETS = {
    "002747": "埃斯顿",
    "300223": "北京君正",
    "600721": "百花医药",
    "600664": "哈药股份",
    "300285": "国瓷材料",
    "003033": "征和工业",
    "003032": "传智教育",
    "000636": "风华高科",
}

DAYS = 500


def fetch_kline(full_code, days=DAYS):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,,,{days},qfq"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        arr = data.get("data", {}).get(full_code, {}).get("qfqday", [])
        out = []
        for row in arr:
            if len(row) >= 6:
                out.append([row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
        return out
    except Exception as e:
        print(f"[kline] {full_code} 失败: {e}")
        return []


def main():
    out = {"updated_at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S") + "+08:00", "days": DAYS, "stocks": {}}
    for code, name in TARGETS.items():
        full = _full(code)
        kline = fetch_kline(full, DAYS)
        if kline:
            out["stocks"][code] = {"name": name, "full_code": full, "kline": kline}
            print(f"[kline] {code} {name}: {len(kline)} 天")
        else:
            print(f"[kline] {code} {name}: 无数据")
        time.sleep(0.15)
    out["count"] = len(out["stocks"])
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[kline] 已保存 {path}，共 {out['count']} 只")


if __name__ == "__main__":
    main()
