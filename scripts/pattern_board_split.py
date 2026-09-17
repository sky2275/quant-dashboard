#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pattern_board_split.py — 按板块（主板/创业板科创板/北交所）拆分形态有效性
==========================================================================
背景：北交所（920/8/4开头）涨跌幅 30%、需 50 万门槛，散户通常无法参与。
      若不拆分，北交所的高波动会污染统计、给出不切实际的推荐。

输出：cache/pattern_board_split.json
"""
import os
import sys
import json

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
DAILY = os.path.join(CACHE, "allmarket_daily.parquet")
BASIC = os.path.join(CACHE, "allmarket_basic.parquet")
STATS = os.path.join(CACHE, "pattern_t1_stats.json")
OUT = os.path.join(CACHE, "pattern_board_split.json")

MIN_BARS = 60
sys.path.insert(0, os.path.join(REPO, "scripts"))
from scan_pattern_t1 import build_patterns, limit_pct  # noqa: E402

# 板块分类
def board_of(code6: str) -> str:
    if code6.startswith(("920", "8", "4")):
        return "北交所"
    if code6.startswith(("300", "301", "688", "689")):
        return "创业科创板"   # 20% 涨跌幅
    return "主板"            # 10% 涨跌幅


def main():
    stats = json.load(open(STATS, encoding="utf-8"))
    base = stats["baseline"]
    winners = [s["pattern"] for s in stats["patterns"]
               if s["stable"] and s["t_stat"] > 4 and s["excess_ret"] > 0.3]
    print(f"[形态] {winners}")

    df = pd.read_parquet(DAILY)
    name_map = {}
    if os.path.exists(BASIC):
        b = pd.read_parquet(BASIC)
        name_map = dict(zip(b["ts_code"], b["name"]))
    df["_nm"] = df["ts_code"].map(name_map)
    df = df[~df["_nm"].fillna("").str.contains("ST|退", regex=True)]

    # agg[pattern][board] = list of (cc, gap, amt)
    agg = {w: {b: [] for b in ("主板", "创业科创板", "北交所")} for w in winners}

    for code, g in df.groupby("ts_code", sort=False):
        g = g.sort_values("trade_date")
        if len(g) < MIN_BARS + 2:
            continue
        o = g["open"].values.astype(float)
        h = g["high"].values.astype(float)
        l = g["low"].values.astype(float)
        c = g["close"].values.astype(float)
        v = g["vol"].values.astype(float)
        pct = g["pct_chg"].values.astype(float)
        n = len(c)
        if np.isnan(c).any() or np.isnan(o).any():
            continue
        bd = board_of(str(code)[:6])
        if bd not in agg[winners[0]]:
            continue

        ret_cc = np.full(n, np.nan); ret_cc[:-1] = c[1:] / c[:-1] - 1
        gap = np.full(n, np.nan); gap[:-1] = o[1:] / c[:-1] - 1
        try:
            P = build_patterns(o, h, l, c, v, pct, limit_pct(code))
        except Exception:
            continue
        tradable = ~np.isnan(ret_cc) & (gap < 0.09) & (gap > -0.11)

        for w in winners:
            m = P.get(w)
            if m is None:
                continue
            idx = np.where(m & tradable)[0]
            for i in idx:
                if np.isnan(ret_cc[i]):
                    continue
                agg[w][bd].append((float(ret_cc[i]), float(gap[i])))

    out = {"baseline": base, "boards": {}}
    print(f"\n{'板块':<12}{'样本':>8}{'胜率':>8}{'超额胜率':>9}{'均收益':>9}{'超额':>8}{'跳空均值':>9}")
    print("-" * 66)
    for w in winners:
        out["boards"][w] = {}
        for bd in ("主板", "创业科创板", "北交所"):
            a = agg[w][bd]
            if len(a) < 100:
                continue
            cc = np.array([x[0] for x in a]) * 100
            gp = np.array([x[1] for x in a]) * 100
            rec = {
                "n": len(cc),
                "win_rate": float((cc > 0).mean() * 100),
                "excess_win": float((cc > 0).mean() * 100 - base["win_rate_cc"]),
                "mean": float(cc.mean()),
                "excess_mean": float(cc.mean() - base["mean_cc"]),
                "median": float(np.median(cc)),
                "gap_mean": float(gp.mean()),
                "std": float(cc.std(ddof=1)),
                "prob_loss_gt5": float((cc < -5).mean() * 100),
            }
            out["boards"][w][bd] = rec
            print(f"{w:<8}{bd:<10}{rec['n']:>7}{rec['win_rate']:>7.1f}%"
                  f"{rec['excess_win']:>+8.1f}%{rec['mean']:>+8.2f}%"
                  f"{rec['excess_mean']:>+7.2f}%{rec['gap_mean']:>+8.2f}%")
        print()

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[OK] → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
