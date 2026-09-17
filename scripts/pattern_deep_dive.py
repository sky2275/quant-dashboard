#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pattern_deep_dive.py — 有效形态的深度解剖 + 最新交易日实盘扫描
================================================================
在 scan_pattern_t1.py 得出「哪些形态有效」之后，回答三个实操问题：

  Q1 收益从哪来？  隔夜跳空(gap) vs 次日日内(oc) —— 决定该尾盘买还是次日开盘买
  Q2 风险有多大？  收益分位数、最大亏损、暴跌(< -5%)概率 —— 决定仓位
  Q3 现在买什么？  用最新交易日全市场扫描，输出符合有效形态的个股清单

输出：
  cache/pattern_deep.json    （Q1/Q2 答案）
  cache/pattern_picks.json   （Q3 个股清单）
"""
import os
import sys
import json
import math

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
DAILY = os.path.join(CACHE, "allmarket_daily.parquet")
BASIC = os.path.join(CACHE, "allmarket_basic.parquet")
STATS = os.path.join(CACHE, "pattern_t1_stats.json")
OUT_DEEP = os.path.join(CACHE, "pattern_deep.json")
OUT_PICKS = os.path.join(CACHE, "pattern_picks.json")

MIN_BARS = 60

sys.path.insert(0, os.path.join(REPO, "scripts"))
from scan_pattern_t1 import build_patterns, shift, limit_pct  # noqa: E402


def pct(a, q):
    return float(np.percentile(a, q))


def main():
    if not os.path.exists(STATS):
        print("[ERR] 先跑 scan_pattern_t1.py")
        return 1

    stats = json.load(open(STATS, encoding="utf-8"))
    base = stats["baseline"]

    # 入选标准：样本外两半都跑赢基准 + t>4 + 超额收益>0.3%
    winners = [s for s in stats["patterns"]
               if s["stable"] and s["t_stat"] > 4 and s["excess_ret"] > 0.3]
    win_names = [s["pattern"] for s in winners]
    print(f"[入选形态] {win_names}")

    df = pd.read_parquet(DAILY)
    name_map, ind_map = {}, {}
    if os.path.exists(BASIC):
        b = pd.read_parquet(BASIC)
        name_map = dict(zip(b["ts_code"], b["name"]))
        ind_map = dict(zip(b["ts_code"], b.get("industry", b["name"])))
    df["_nm"] = df["ts_code"].map(name_map)
    df = df[~df["_nm"].fillna("").str.contains("ST|退", regex=True)]

    # ── 收集入选形态的全部样本（含 gap / oc / 分位）──────────
    print("[1/3] 重扫样本（含跳空/日内分解）...")
    agg = {w: {"cc": [], "oc": [], "gap": [], "date": [], "code": [], "px": [], "amt": []}
           for w in win_names}

    for code, g in df.groupby("ts_code", sort=False):
        g = g.sort_values("trade_date")
        if len(g) < MIN_BARS + 2:
            continue
        o = g["open"].values.astype(float)
        h = g["high"].values.astype(float)
        l = g["low"].values.astype(float)
        c = g["close"].values.astype(float)
        v = g["vol"].values.astype(float)
        pct_chg = g["pct_chg"].values.astype(float)
        amt = g["amount"].values.astype(float) if "amount" in g else np.zeros(len(c))
        dates = g["trade_date"].values
        n = len(c)
        if np.isnan(c).any() or np.isnan(o).any():
            continue

        ret_cc = np.full(n, np.nan); ret_cc[:-1] = c[1:] / c[:-1] - 1
        ret_oc = np.full(n, np.nan)
        ret_oc[:-1] = c[1:] / np.where(o[1:] > 0, o[1:], np.nan) - 1
        gap = np.full(n, np.nan); gap[:-1] = o[1:] / c[:-1] - 1

        try:
            P = build_patterns(o, h, l, c, v, pct_chg, limit_pct(code))
        except Exception:
            continue

        tradable = ~np.isnan(ret_cc) & (gap < 0.09) & (gap > -0.11)

        for w in win_names:
            idx = np.where(P.get(w, np.zeros(n, bool)) & tradable)[0]
            if not len(idx):
                continue
            a = agg[w]
            for i in idx:
                if np.isnan(ret_cc[i]) or np.isnan(gap[i]):
                    continue
                a["cc"].append(float(ret_cc[i]))
                a["oc"].append(float(ret_oc[i]))
                a["gap"].append(float(gap[i]))
                a["date"].append(str(dates[i]))
                a["code"].append(str(code))
                a["px"].append(float(c[i]))
                a["amt"].append(float(amt[i]) if not np.isnan(amt[i]) else 0.0)

    # ── Q1 + Q2：解剖 ────────────────────────────────────
    print("[2/3] 解剖收益来源与风险 ...")
    deep = []
    for w in win_names:
        a = agg[w]
        cc = np.array(a["cc"]) * 100
        oc = np.array(a["oc"]) * 100
        gp = np.array(a["gap"]) * 100
        N = len(cc)
        if N < 200:
            continue
        # 收益分解：cc ≈ gap + oc（近似，误差来自复利）
        deep.append({
            "pattern": w,
            "n": N,
            # 三种卖出方式
            "close_buy_close_sell": {   # T日收盘买 → T+1收盘卖
                "mean": float(cc.mean()), "median": float(np.median(cc)),
                "win_rate": float((cc > 0).mean() * 100),
                "excess_mean": float(cc.mean() - base["mean_cc"]),
            },
            "close_buy_open_sell": {    # T日收盘买 → T+1开盘卖（只吃跳空）
                "mean": float(gp.mean()), "median": float(np.median(gp)),
                "win_rate": float((gp > 0).mean() * 100),
            },
            "open_buy_close_sell": {    # T+1开盘买 → T+1收盘卖（日内）
                "mean": float(oc.mean()), "median": float(np.median(oc)),
                "win_rate": float((oc > 0).mean() * 100),
            },
            # 风险
            "risk": {
                "p05": pct(cc, 5), "p25": pct(cc, 25), "p75": pct(cc, 75), "p95": pct(cc, 95),
                "std": float(cc.std(ddof=1)),
                "prob_loss_gt3": float((cc < -3).mean() * 100),
                "prob_loss_gt5": float((cc < -5).mean() * 100),
                "prob_gain_gt5": float((cc > 5).mean() * 100),
                "prob_gain_gt9": float((cc > 9).mean() * 100),
                "worst": float(cc.min()), "best": float(cc.max()),
            },
            "gap_mean": float(gp.mean()),
            "sample_dates": [min(a["date"]), max(a["date"])],
        })

    with open(OUT_DEEP, "w", encoding="utf-8") as f:
        json.dump({"baseline": base, "patterns": deep}, f, ensure_ascii=False, indent=1)

    # ── Q3：最新交易日实盘扫描 ────────────────────────────
    print("[3/3] 扫描最新交易日符合形态的个股 ...")
    last_date = str(df["trade_date"].max())
    picks = {w: [] for w in win_names}

    for code, g in df.groupby("ts_code", sort=False):
        g = g.sort_values("trade_date")
        if len(g) < MIN_BARS + 1:
            continue
        o = g["open"].values.astype(float)
        h = g["high"].values.astype(float)
        l = g["low"].values.astype(float)
        c = g["close"].values.astype(float)
        v = g["vol"].values.astype(float)
        pct_chg = g["pct_chg"].values.astype(float)
        amt = g["amount"].values.astype(float) if "amount" in g else np.zeros(len(c))
        n = len(c)
        if str(g["trade_date"].iloc[-1]) != last_date or np.isnan(c).any():
            continue
        try:
            P = build_patterns(o, h, l, c, v, pct_chg, limit_pct(code))
        except Exception:
            continue
        i = n - 1
        for w in win_names:
            m = P.get(w)
            if m is None or not bool(m[i]):
                continue
            picks[w].append({
                "code": str(code)[:6],
                "name": name_map.get(str(code), str(code)),
                "industry": ind_map.get(str(code), ""),
                "close": round(float(c[i]), 2),
                "pct_chg": round(float(pct_chg[i]), 2),
                "amount_yi": round(float(amt[i]) / 100000.0, 2) if amt[i] else 0.0,  # 成交额(亿)
                "date": last_date,
            })

    for w in picks:
        picks[w].sort(key=lambda x: -x["amount_yi"])

    with open(OUT_PICKS, "w", encoding="utf-8") as f:
        json.dump({"asof": last_date, "picks": picks}, f, ensure_ascii=False, indent=1)

    # ── 打印 ────────────────────────────────────────────
    print(f"\n{'='*76}\n基准：胜率 {base['win_rate_cc']:.2f}%  平均 {base['mean_cc']:+.3f}%\n{'='*76}")
    for d in deep:
        print(f"\n【{d['pattern']}】 N={d['n']:,}  样本期 {d['sample_dates'][0]}~{d['sample_dates'][1]}")
        for k, label in [("close_buy_close_sell", "尾盘买→次日收盘卖"),
                         ("close_buy_open_sell", "尾盘买→次日开盘卖(只吃跳空)"),
                         ("open_buy_close_sell", "次日开盘买→收盘卖(日内)")]:
            s = d[k]
            print(f"    {label:<26} 均值{s['mean']:+.2f}%  中位{s['median']:+.2f}%  胜率{s['win_rate']:.1f}%")
        r = d["risk"]
        print(f"    风险: 5%分位{r['p05']:+.2f}%  95%分位{r['p95']:+.2f}%  标准差{r['std']:.2f}%")
        print(f"          亏>3%概率{r['prob_loss_gt3']:.1f}%  亏>5%概率{r['prob_loss_gt5']:.1f}%"
              f"  赚>5%概率{r['prob_gain_gt5']:.1f}%  赚>9%概率{r['prob_gain_gt9']:.1f}%")

    print(f"\n{'='*76}\n最新交易日 {last_date} 符合形态个股：\n{'='*76}")
    for w in win_names:
        lst = picks[w][:12]
        print(f"\n【{w}】 {len(picks[w])} 只，按成交额排序 Top{len(lst)}:")
        for p in lst:
            print(f"    {p['code']} {p['name']:<8} {p['industry'] or '-':<8} "
                  f"收{p['close']:>7.2f}  {p['pct_chg']:+.2f}%  成交{p['amount_yi']:.1f}亿")
    print(f"\n[OK] → {OUT_DEEP}\n[OK] → {OUT_PICKS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
