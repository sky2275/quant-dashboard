#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块数据降级通道：腾讯 proxy.finance.qq.com 行业排行 -> cache/sector_raw_westock.json

为什么需要：westock-mcp / eastmoney 在沙箱内被网络屏蔽（push2.eastmoney.com 连接被拒），
而 proxy.finance.qq.com 可直连（与 feed.py 首选数据源同一供应商口径）。
字段与 import_sector_westock.py 的输出 schema 完全一致，refresh_sector_data.py 可直接消费。

用法：
    python3 scripts/_import_sector_tencent.py            # 现拉现写（默认 hy2，120 个行业）
    python3 scripts/_import_sector_tencent.py /tmp/x.json 2026-08-31   # 用已有原始 JSON
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "cache", "sector_raw_westock.json")
API = ("https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"
       "?board_type=hy2&sort_type=price&direct=down&offset=0&count=120")
# 注意：该接口 sort_type 枚举只接受 "price"（zdf/zljlr/cje/hsl 均报 sort_type error），
# 排序一律在客户端做。


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch() -> list:
    raw = subprocess.run(["curl", "-s", "-m", "20", API],
                         capture_output=True, text=True).stdout
    d = json.loads(raw)
    if d.get("code") != 0:
        raise RuntimeError(f"腾讯接口返回异常: {d.get('msg')}")
    return d["data"]["rank_list"]


def build(rows_raw: list) -> dict:
    rows = [{
        "code": r.get("code"),
        "name": r.get("name"),
        "zdf": f(r.get("zdf")),
        "cje": f(r.get("turnover")),
        "hsl": f(r.get("hsl")),
        "zljlr": f(r.get("zljlr")),
        "zljlr_d5": f(r.get("zljlr_d5")),
        "zljlr_d20": f(r.get("zljlr_d20")),
        "lzg": {"code": (r.get("lzg") or {}).get("code"),
                "name": (r.get("lzg") or {}).get("name"),
                "zdf": f((r.get("lzg") or {}).get("zdf"))},
    } for r in rows_raw if r.get("name")]

    pos = sorted([r for r in rows if (r["zljlr"] or 0) > 0],
                 key=lambda r: r["zljlr"], reverse=True)
    neg = sorted([r for r in rows if (r["zljlr"] or 0) <= 0],
                 key=lambda r: r["zljlr"])
    rank = [{
        "bd_code": r["code"], "bd_name": r["name"], "bd_zdf": r["zdf"],
        "bd_zdf5": f(x.get("zdf_d5")) if isinstance(x, dict) else None,
        "bd_zdf20": f(x.get("zdf_d20")) if isinstance(x, dict) else None,
        "nzg_code": r["lzg"]["code"], "nzg_name": r["lzg"]["name"],
        "nzg_zdf": r["lzg"]["zdf"],
    } for r, x in zip(sorted(rows, key=lambda r: r["zdf"] or 0, reverse=True),
                      sorted(rows_raw, key=lambda r: f(r.get("zdf")) or 0, reverse=True))]

    return rows, pos, neg, rank


def main() -> int:
    asof = dt.date.today().isoformat()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        rows_raw = json.load(open(sys.argv[1], encoding="utf-8"))["data"]["rank_list"]
        if len(sys.argv) > 2:
            asof = sys.argv[2]
    else:
        rows_raw = fetch()

    rows, pos, neg, rank = build(rows_raw)
    payload = {
        "updated_at": f"{asof}T{dt.datetime.now().strftime('%H:%M:%S')}",
        "source": f"腾讯 proxy.finance.qq.com 行业排行(hy2) asof={asof} "
                  f"[westock-mcp 不可用时的降级通道]",
        "fundflow": {"plate": {"top": pos, "bottom": neg}},
        "rank": {"plate": rank},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"[import-tencent] {OUT}")
    print(f"  总板块 {len(rows)} | 净流入 {len(pos)} | 净流出 {len(neg)} | rank {len(rank)}")
    print("  涨幅TOP3:", ", ".join(f"{r['bd_name']}{r['bd_zdf']:+.2f}%" for r in rank[:3]))
    print("  跌幅TOP3:", ", ".join(f"{r['bd_name']}{r['bd_zdf']:+.2f}%" for r in rank[-3:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
