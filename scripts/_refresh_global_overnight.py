#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环球隔夜缓存刷新（沿用现有 schema，只更新 asof/updated_at + 数据）。

⚠️ 结构：逻辑与内容分离 —— 全部文字/数值内容在 scripts/global_content.json，
   本文件只负责「拉实时行情 + 聚合 7 板块 + 写 5 个缓存」。
   每日更新只需改 JSON，不再改 Python 源码（规避历史反复出现的行号切片 / 括号匹配破坏语法事故）。
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
CONTENT_PATH = os.path.join(REPO, "scripts", "global_content.json")
sys.path.insert(0, os.path.join(REPO, "scripts"))

NOW = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

with open(CONTENT_PATH, encoding="utf-8") as _f:
    _C = json.load(_f)

ASOF_US = _C["asof_us"]
ASOF_CN = _C["asof_cn"]
ASOF_HK = _C["asof_hk"]
SRC = _C["source"]
HEADLINES = _C["headlines"]
ANALYSIS = _C["analysis"]
MACRO_ITEMS = _C["macro_items"]
A_NEWS = _C["a_news"]
FRESH_MEMBERS = {k: (v[0], v[1]) for k, v in _C["members"].items()}
STATIC_DEFAULTS = _C.get("static_defaults", {})
LIVE_NOTES = _C.get("live_notes", {})

KR_CODES = ["krKS11", "krKOSDAQ", "kr005930", "kr000660", "kr373220",
            "kr006400", "kr051910", "kr034220", "kr005380", "kr000270", "kr005490"]
JP_CODES = ["jpN225", "jpTOPIX"]
HK_CODES = ["hkHSI", "hkHSTECH", "hkHSCEI"]
US_IDX = ["IXIC", "DJI", "INX"]

US_SECTORS = {
    "半导体": ["SOXX", "SMH", "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ARM", "MRVL", "MPWR"],
    "存储": ["MU", "WDC", "STX", "SNDK"],
    "光模块": ["COHR", "LITE", "AAOI", "FN"],
    "物理AI": ["BOTZ", "ARKQ", "SYM", "ROK", "TSLA"],
    "科技巨头": ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"],
    "苹果供应链": ["AAPL", "QCOM", "SWKS", "CRUS", "AVGO"],
    "先进封装": ["AMAT", "LRCX", "KLAC", "ASML", "AMKR", "ONTO", "COHU", "TER"],
}


def _dump(name: str, obj: dict) -> None:
    p = os.path.join(CACHE, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[global] {name} 更新 -> {NOW}")


def refresh_global_news(sector_summary: dict | None = None) -> None:
    _dump("global_news_summary.json", {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC,
        "headlines": HEADLINES,
        "analysis": ANALYSIS,
        "us_sectors": sector_summary or {},
    })


def refresh_macro() -> None:
    _dump("macro_commodity.json", {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC,
        "items": MACRO_ITEMS,
    })


def refresh_a_news() -> None:
    _dump("a_news_summary.json", {
        "asof": ASOF_CN,
        "updated_at": NOW,
        "source": SRC,
        "news": A_NEWS,
        "members": FRESH_MEMBERS,
    })


def refresh_sector_contrib() -> None:
    _dump("sector_contrib_mx.json", {
        "asof": ASOF_CN,
        "updated_at": NOW,
        "source": SRC,
        "sectors": [
            {"name": n, "change_pct": p, "code": c}
            for (c, (n, p)) in FRESH_MEMBERS.items()
        ],
    })


def refresh_global_quotes(fetch_live: bool = True) -> dict:
    kr, jp, hk, us, sec_raw = {}, {}, {}, {}, {}
    if fetch_live:
        try:
            import feed  # noqa: E402
            raw = feed.tencent_quotes(KR_CODES + JP_CODES + HK_CODES)
            for k, v in raw.items():
                short = k[2:] if k[:2] in ("kr", "jp", "hk") else k
                tgt = kr if k.startswith("kr") else jp if k.startswith("jp") else hk
                if v.get("price"):
                    tgt[short] = {"symbol": short, "name": v.get("name", short),
                                  "price": v.get("price"), "change_pct": v.get("change_pct"),
                                  "time": v.get("time", "")}
            for s in US_IDX:
                r = feed.get_us_stock(s)
                if r and r.get("price"):
                    us[s] = {"symbol": s, "name": r.get("name", s),
                             "price": r.get("price"), "change_pct": r.get("change_pct")}
            for sec, syms in US_SECTORS.items():
                for s in syms:
                    if s in sec_raw:
                        continue
                    r = feed.get_us_stock(s)
                    if r and r.get("price"):
                        sec_raw[s] = {"symbol": s, "name": r.get("name", s),
                                      "price": r.get("price"), "change_pct": r.get("change_pct")}
        except Exception as e:  # pragma: no cover
            print("[global] 实时行情拉取失败：", e)

    # 腾讯不返回韩国/日本指数 → 用已核实的收盘快照补齐（内容见 global_content.json）
    for grp, tgt in (("kr", kr), ("jp", jp), ("hk", hk)):
        for code, item in (STATIC_DEFAULTS.get(grp) or {}).items():
            tgt.setdefault(code, {"symbol": code, "name": item["name"],
                                  "price": item["price"], "change_pct": item["change_pct"],
                                  "note": item["note"]})

    # 已取到实时值的条目，用 update 覆盖 note，确保注释是当天的
    for grp, tgt in (("kr", kr), ("jp", jp), ("hk", hk)):
        for code, note in (LIVE_NOTES.get(grp) or {}).items():
            if code in tgt:
                tgt[code]["note"] = note

    sectors = {}
    for sec, syms in US_SECTORS.items():
        vals = [sec_raw[s]["change_pct"] for s in syms
                if s in sec_raw and sec_raw[s].get("change_pct") is not None]
        if vals:
            sectors[sec] = {
                "avg_change_pct": round(sum(vals) / len(vals), 2),
                "n": len(vals),
                "members": {s: sec_raw[s] for s in syms if s in sec_raw},
            }
    print("[global] 7大板块聚合：",
          {k: v["avg_change_pct"] for k, v in sectors.items()})

    _dump("global_quotes.json", {
        "asof": ASOF_US,
        "updated_at": NOW,
        "source": SRC + " | 腾讯 qt.gtimg.cn（" + _C.get("quotes_source_note", "") + "）",
        "kr": kr, "jp": jp, "hk": hk, "us": us, "us_sectors": sectors,
        "korea_watch": {
            "三星电子": {"code": "kr005930", "change_pct": (kr.get("005930") or {}).get("change_pct")},
            "SK海力士": {"code": "kr000660", "change_pct": (kr.get("000660") or {}).get("change_pct")},
            "LG新能源": {"code": "kr373220", "change_pct": (kr.get("373220") or {}).get("change_pct")},
        },
    })
    return sectors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-live", action="store_true", help="不拉实时行情")
    args = ap.parse_args()
    live = not args.no_live
    sectors = refresh_global_quotes(fetch_live=live)
    refresh_global_news(sector_summary=sectors or None)
    refresh_macro()
    refresh_a_news()
    refresh_sector_contrib()
    print("[global] 全部环球缓存刷新完成")


if __name__ == "__main__":
    main()
