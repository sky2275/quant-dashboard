#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""westock data_sector(mode=ranking, scope=sw1, limit=30) 原始返回 → cache/sector_raw_westock.json
将单一 ranking 行集转写为 refresh_sector_data.py 期望的 schema：
  fundflow.plate.top   = 主力净流入为正 的板块（资金流入方向）
  fundflow.plate.bottom = 主力净流入为负 的板块（资金流出方向）
  rank.plate           = 主力净流入为正 的板块（趋势补充，供 chg/leader 映射）
字段映射：zdf=changePct, cje=turnover(万元), hsl=turnoverRate,
  zljlr=mainNetInflow, zljlr_d5=mainNetInflow5d, zljlr_d20=mainNetInflow20d,
  lzg={code,name,zdf:leader.changePct}
"""
import json, os, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "cache", "_westock_rank_raw.json")
OUT = os.path.join(REPO, "cache", "sector_raw_westock.json")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_fundflow(r):
    ld = r.get("leader") or {}
    return {
        "code": r["code"],
        "name": r["name"],
        "zdf": f(r.get("changePct")),
        "cje": f(r.get("turnover")),            # 成交额(万元)
        "hsl": f(r.get("turnoverRate")),        # 换手率(%)
        "zljlr": f(r.get("mainNetInflow")),     # 主力净流入(万元)
        "zljlr_d5": f(r.get("mainNetInflow5d")),
        "zljlr_d20": f(r.get("mainNetInflow20d")),
        "lzg": {
            "code": ld.get("code"),
            "name": ld.get("name"),
            "zdf": f(ld.get("changePct")),
        },
    }


def to_rank(r):
    ld = r.get("leader") or {}
    return {
        "bd_code": r["code"],
        "bd_name": r["name"],
        "bd_zdf": f(r.get("changePct")),
        "bd_zdf5": None,                        # westock ranking 不返回 5/20 日价格涨幅
        "bd_zdf20": None,
        "nzg_code": ld.get("code"),
        "nzg_name": ld.get("name"),
        "nzg_zdf": f(ld.get("changePct")),
    }


def main():
    raw = json.load(open(RAW, encoding="utf-8"))
    rows = (raw.get("data") or {}).get("rows") or []
    rows.sort(key=lambda r: f(r.get("mainNetInflow")) or 0, reverse=True)

    # 按净流入裁剪成可读 TOP（原始 westock 返回全量 124 行业，看板以 TOP30 展示）
    pos = sorted([r for r in rows if (f(r.get("mainNetInflow")) or 0) > 0],
                 key=lambda r: f(r.get("mainNetInflow")) or 0, reverse=True)
    neg = sorted([r for r in rows if (f(r.get("mainNetInflow")) or 0) <= 0],
                 key=lambda r: f(r.get("mainNetInflow")) or 0)
    top = [to_fundflow(r) for r in pos[:30]]
    bottom = [to_fundflow(r) for r in neg[:20]]
    rank = [to_rank(r) for r in pos[:30]]

    data = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "westock-mcp data_sector(mode=ranking,scope=sw1,limit=30)",
        "fundflow": {"plate": {"top": top, "bottom": bottom}},
        "rank": {"plate": rank},
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    print(f"[transcribe] written {OUT}")
    print(f"  top(净流入>0)={len(top)} bottom(净流出)={len(bottom)} rank={len(rank)}")
    print("  净流入TOP5:", ", ".join(f"{x['name']}({x['zdf']:+.2f}%,主净{x['zljlr']/1e4:+.2f}亿)"
          for x in top[:5]))
    print("  净流出TOP5:", ", ".join(f"{x['name']}({x['zdf']:+.2f}%,主净{x['zljlr']/1e4:+.2f}亿)"
          for x in bottom[:5]))


if __name__ == "__main__":
    main()
