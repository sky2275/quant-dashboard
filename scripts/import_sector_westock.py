#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 westock-mcp data_sector(mode=ranking,scope=sw1) 的返回转写为
cache/sector_raw_westock.json（refresh_sector_data.py 期望的 schema）。

输入：紧凑文本，每行一条，字段以 | 分隔
  code_suffix|name|zdf|cje|hsl|net|net5|net20|leader_code|leader_name|leader_zdf

输出 cache/sector_raw_westock.json：
  { updated_at, source, fundflow:{plate:{top:[...],bottom:[...]}}, rank:{plate:[...]} }
  · top    = 主力净流入 > 0 的板块（按净流入降序）
  · bottom = 主力净流入 <= 0 的板块（按净流入升序）
  · rank   = 全部板块趋势（bd_code/bd_zdf，5/20 日涨幅 westock 未给，置 null）
"""
from __future__ import annotations
import json
import os
import sys
import datetime as dt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sector_20260828.txt"
ASOF = sys.argv[2] if len(sys.argv) > 2 else "2026-08-28"
OUT = os.path.join(REPO, "cache", "sector_raw_westock.json")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    rows = []
    with open(SRC, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split("|")
            if len(p) < 11:
                print(f"[warn] 字段不足 11，跳过: {line[:60]}", file=sys.stderr)
                continue
            rows.append({
                "code": "pt" + p[0],
                "name": p[1],
                "zdf": f(p[2]),
                "cje": f(p[3]),
                "hsl": f(p[4]),
                "zljlr": f(p[5]),
                "zljlr_d5": f(p[6]),
                "zljlr_d20": f(p[7]),
                "lzg": {"code": p[8], "name": p[9], "zdf": f(p[10])},
            })

    if not rows:
        print("[err] 无有效数据", file=sys.stderr)
        return 2

    pos = sorted([r for r in rows if (r["zljlr"] or 0) > 0],
                 key=lambda r: r["zljlr"], reverse=True)
    neg = sorted([r for r in rows if (r["zljlr"] or 0) <= 0],
                 key=lambda r: r["zljlr"])

    rank = [{
        "bd_code": r["code"],
        "bd_name": r["name"],
        "bd_zdf": r["zdf"],
        "bd_zdf5": None,
        "bd_zdf20": None,
        "nzg_code": r["lzg"]["code"],
        "nzg_name": r["lzg"]["name"],
        "nzg_zdf": r["lzg"]["zdf"],
    } for r in sorted(rows, key=lambda r: r["zdf"] or 0, reverse=True)]

    payload = {
        "updated_at": f"{ASOF}T{dt.datetime.now().strftime('%H:%M:%S')}",
        "source": f"westock-mcp data_sector(mode=ranking,scope=sw1) asof={ASOF}",
        "fundflow": {"plate": {"top": pos, "bottom": neg}},
        "rank": {"plate": rank},
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"[import] {OUT}")
    print(f"  总板块 {len(rows)} | 净流入 {len(pos)} | 净流出 {len(neg)} | rank {len(rank)}")
    print("  涨幅TOP3:", ", ".join(f"{r['bd_name']}{r['bd_zdf']:+.2f}%" for r in rank[:3]))
    print("  跌幅TOP3:", ", ".join(f"{r['bd_name']}{r['bd_zdf']:+.2f}%" for r in rank[-3:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
