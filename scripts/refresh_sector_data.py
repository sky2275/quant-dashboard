#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_sector_data.py — 用 westock-mcp 实时板块资金流/趋势刷新板块数据。

数据来源（实时，腾讯自选股）：
  westock-mcp: data_sector(mode=ranking, scope=sw1) 返回的
    - fundflow.plate.top/bottom : 行业板块主力净流入/流出排行
        zdf=涨跌幅, cje=成交额(万元), hsl=换手率, zljlr=主力净流入(万元),
        zljlr_d5/d20=5/20日主力净流入, lzg=领涨股{code,name,zdf}
    - rank.plate : 行业板块趋势（bd_zdf/bd_zdf5/bd_zdf20=今/5/20日涨幅, nzg=领涨股）

本脚本消费「已落盘的 westock 原始 JSON」(cache/sector_raw_westock.json)，
由自动化/人工先调用 westock-mcp 抓取并写入该原始文件，再运行本脚本完成映射：
    1) 合并 fundflow.plate.top(含资金流) + rank.plate(趋势) → top_inflow（资金流入方向）
    2) fundflow.plate.bottom → top_outflow（资金流出方向）
    3) 复用旧文件 astocks 全A个股宇宙（名称/代码不常变），更新 updated_at
    4) 写出 sector_leader_data.json（schema 与原 Excel 导出兼容）

刷新方式（自动化）：
  调用 mcp__westock-mcp__data_sector(mode=ranking, scope=sw1, limit=30)
  → 将返回的 data.fundflow + data.rank 整理为 cache/sector_raw_westock.json
  → python3 scripts/refresh_sector_data.py
  → python3 scripts/build_dashboard.py
  → git add -A && git commit && git push
"""
from __future__ import annotations
import json
import os
import sys
import datetime as dt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "cache", "sector_raw_westock.json")
OUT = os.path.join(REPO, "cache", "sector_leader_data.json")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build(raw: dict) -> dict:
    ff = (raw.get("fundflow") or {}).get("plate") or {}
    rank = (raw.get("rank") or {}).get("plate") or []

    # 趋势表按板块码建索引，供资金流板补 5/20 日涨幅、领涨股
    trend = {b.get("bd_code"): b for b in rank if b.get("bd_code")}

    def map_plate(p, with_fund=True):
        code = p.get("code") or p.get("bd_code")
        t = trend.get(code, {})
        chg = _f(p.get("zdf")) if "zdf" in p else _f(p.get("bd_zdf"))
        main_fund = _f(p.get("zljlr"))
        cje = _f(p.get("cje"))
        lzg = p.get("lzg") or {}
        nzg = t.get("nzg_name")
        nzg_code = t.get("nzg_code")
        leader = lzg.get("name") or nzg
        leader_code = lzg.get("code") or nzg_code
        leader_chg = _f(lzg.get("zdf")) if lzg.get("zdf") is not None else _f(t.get("nzg_zdf"))
        return {
            "name": p.get("name") or t.get("bd_name"),
            "chg": chg,
            "main_amount": (cje * 1e4) if cje is not None else None,   # 成交额(元)
            "main_fund": (main_fund * 1e4) if main_fund is not None else None,  # 主力净流入(元)
            "limit_up": 0,            # westock 未给涨停家数，建仓建议以趋势/资金为主
            "up_count": None,
            "down_count": None,
            "leader": leader,
            "chg5d": _f(t.get("bd_zdf5")) if t else None,
            "chg10d": _f(t.get("bd_zdf20")) if t else None,
            "vol_ratio": _f(p.get("hsl")),
            "float_cap": None,
            "total_cap": None,
            "concept": "--",
            "leader_code": leader_code,
            "leader_price": None,
            "leader_chg": leader_chg,
        }

    top = [map_plate(x) for x in (ff.get("top") or [])]
    bottom = [map_plate(x) for x in (ff.get("bottom") or [])]

    # 用趋势板补充 top_inflow（避免只有 3 只资金流板太单薄）：取 rank 中未出现的
    top_codes = {t.get("name") for t in top}
    for b in rank:
        if b.get("bd_name") in top_codes:
            continue
        if len(top) >= 30:
            break
        top.append(map_plate(b))
    # 排序：有主力净流入的（资金流板）排在前面，其余按当日涨幅
    top.sort(key=lambda r: (r["main_fund"] is not None and r["main_fund"] > 0, r["chg"] or 0),
             reverse=True)
    bottom.sort(key=lambda r: r["main_fund"] or 0)

    # 复用旧文件全A个股宇宙
    astocks = []
    astock_count = 0
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
            astocks = old.get("astocks") or []
            astock_count = old.get("astock_count") or len(astocks)
        except Exception:
            pass

    return {
        "updated_at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "westock-mcp 实时板块资金流/趋势（腾讯自选股）",
        "sector_count": len(top) + len(bottom),
        "astock_count": astock_count,
        "top_inflow": top,
        "top_outflow": bottom,
        "astocks": astocks,
    }


def main():
    if not os.path.exists(RAW):
        print(f"[refresh_sector_data] 缺少原始文件 {RAW}，请先调用 westock-mcp 抓取并写入",
              file=sys.stderr)
        return 2
    raw = json.load(open(RAW, encoding="utf-8"))
    out = _build(raw)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[refresh_sector_data] 已写出 {OUT}")
    print(f"  top_inflow={len(out['top_inflow'])} top_outflow={len(out['top_outflow'])} "
          f"astocks={out['astock_count']} updated_at={out['updated_at']}")
    print("  流入TOP3:", ", ".join(f"{x['name']}({x['chg']:+.2f}%,主净"
          f"{(x['main_fund'] or 0)/1e8:+.1f}亿)" for x in out['top_inflow'][:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
