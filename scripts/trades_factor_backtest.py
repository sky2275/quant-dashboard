#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trades_factor_backtest.py -- 历史交易记录（逐笔买卖点）接入因子回测体系

用户诉求：历史交易记录是否可作回测基础，从选股、历史买卖点做回测，
给出历史交易个股的分析报告 + 现势因子符合度。

三层分析：
  ① 选股层：每只近期交易股「首次买入时」在因子体系里的分位（当时该不该买）
  ② 买卖点层：每一笔买/卖之后 forward=5 日的收益（买卖点择时对不对）
  ③ 现势层：历史交易股「当前」的因子评分/排名/分位/档位（现在符不符合因子策略）

数据源：
  - cache/trades_history.json   逐笔买卖点（含已清仓股，ingest_statements.py 产出）
  - cache/backtest_klines.json  364 只 K 线池
  - cache/factor_ic.json        生效权重 + 翻转标记

输出：cache/trades_factor_backtest.json

⚠️ 简化假设：不计交易成本/涨跌停/T+1；forward 收益未剔除市场 beta（受大盘环境影响）。
   结果用于诊断「历史决策 vs 因子信号」的一致性与择时质量，非实盘收益复现。
"""
from __future__ import annotations

import json
import os
import sys
import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import factor_lib as flib  # noqa: E402
import factor_backtest as fbt  # noqa: E402

FORWARD = 5
STEP = 20
RECENT_THRESHOLD = "2025-08-01"  # 因子权重校准期内（2025-08 后活跃）


def quintile(pct_rank: float) -> str:
    if pct_rank >= 0.80:
        return "Q1 强"
    if pct_rank >= 0.60:
        return "Q2 偏强"
    if pct_rank >= 0.40:
        return "Q3 中性"
    if pct_rank >= 0.20:
        return "Q4 偏弱"
    return "Q5 弱"


def load_data():
    trades = json.load(open(os.path.join(CACHE_DIR, "trades_history.json"),
                           encoding="utf-8"))["trades"]
    kl = json.load(open(os.path.join(CACHE_DIR, "backtest_klines.json"),
                        encoding="utf-8"))
    stocks = kl.get("stocks", {})
    klines = {c: s["kline"] for c, s in stocks.items() if s.get("kline")}
    names = {c: s.get("name", c) for c, s in stocks.items()}
    ic = json.load(open(os.path.join(CACHE_DIR, "factor_ic.json"),
                        encoding="utf-8"))
    return trades, klines, names, ic["weights"], ic["flips"]


def fwd_return(kl, date, forward=FORWARD):
    """date 当日（或 ≤ date 最近交易日）收盘后 forward 日的收益。"""
    idx = None
    for i, k in enumerate(kl):
        if k[0] <= date:
            idx = i
        else:
            break
    if idx is None or idx + forward >= len(kl):
        return None
    return kl[idx + forward][2] / kl[idx][2] - 1.0


def main():
    t0 = datetime.datetime.now()
    print("=" * 88)
    print("历史交易记录 → 因子回测（选股 / 买卖点 / 现势 三层）")
    print("=" * 88)

    trades, klines, names, weights, flips = load_data()
    print(f"[1/5] 逐笔 {len(trades)} 笔｜K线池 {len(klines)} 只｜"
          f"翻转因子 {len(flips)} 个")

    # 按股票聚合：首次/最后交易、买卖笔数、逐笔明细
    by_code = {}
    for t in trades:
        c = t.get("code")
        if not c or c not in klines:
            continue
        b = by_code.setdefault(c, {
            "name": names.get(c, t.get("name", c)),
            "first_buy": None, "last": "", "buy_cnt": 0, "sell_cnt": 0,
            "buys": [], "sells": [],
        })
        d = t.get("date", "")
        b["last"] = max(b["last"], d)
        if t["side"] == "buy":
            b["buy_cnt"] += 1
            b["buys"].append(d)
            if b["first_buy"] is None or d < b["first_buy"]:
                b["first_buy"] = d
        elif t["side"] == "sell":
            b["sell_cnt"] += 1
            b["sells"].append(d)

    recent = {c: b for c, b in by_code.items() if b["last"] >= RECENT_THRESHOLD}
    early = {c: b for c, b in by_code.items() if b["last"] < RECENT_THRESHOLD}
    print(f"[2/5] 有K线可回测 {len(by_code)} 只（近期 {len(recent)} / 早期 {len(early)}）")

    # 构建滚动截面面板（无前视），并预计算每期评分排名
    print("[3/5] 构建滚动截面面板（约 19 期）...")
    panel = fbt.build_panel(klines, FORWARD, STEP)
    section_ranks = []  # [{date, rank_map: {code: (rank, n, score)}}]
    for sec in panel["panel"]:
        ranked = fbt.score_cross_section(sec["rows"], panel["names"],
                                         weights, flips)
        n = len(ranked)
        section_ranks.append({
            "date": sec["date"],
            "n": n,
            "rank_map": {c: (i + 1, n, s) for i, (c, s) in enumerate(ranked)},
        })
    print(f"    截面期数 {len(section_ranks)}，日期 "
          f"{section_ranks[0]['date']} ~ {section_ranks[-1]['date']}")

    def pct_at(date, code):
        """≤ date 的最近截面里 code 的分位（0-1），无则 None。"""
        for sec in reversed(section_ranks):
            if sec["date"] <= date:
                if code in sec["rank_map"]:
                    rk, n, _sc = sec["rank_map"][code]
                    return 1.0 - (rk - 1) / n
                return None
        return None

    # ---------- ① 选股层 ----------
    print("[4/5] ① 选股层：首次买入时的因子分位 ...")
    selection = []
    for c, b in recent.items():
        if not b["first_buy"]:
            continue
        p = pct_at(b["first_buy"], c)
        selection.append({
            "code": c, "name": b["name"], "first_buy": b["first_buy"],
            "buy_pct": round(p, 4) if p is not None else None,
        })
    scored_sel = [s for s in selection if s["buy_pct"] is not None]
    hit = sum(1 for s in scored_sel if s["buy_pct"] >= 0.5)
    print(f"    近期股可评分 {len(scored_sel)} 只，买入时分位≥50% 的 {hit} 只"
          f"（命中率 {hit/len(scored_sel)*100:.1f}%）")

    # ---------- ② 买卖点层 ----------
    print("[5/5] ② 买卖点层：每笔买卖 forward=5 收益 ...")
    buy_rets, sell_rets = [], []
    for c, b in recent.items():
        kl = klines[c]
        for d in b["buys"]:
            r = fwd_return(kl, d)
            if r is not None:
                buy_rets.append({"code": c, "name": b["name"], "date": d, "ret": round(r, 4)})
        for d in b["sells"]:
            r = fwd_return(kl, d)
            if r is not None:
                sell_rets.append({"code": c, "name": b["name"], "date": d, "ret": round(r, 4)})

    def stats(rets):
        if not rets:
            return {"n": 0, "win": None, "avg": None}
        n = len(rets)
        win = sum(1 for x in rets if x["ret"] > 0) / n
        avg = sum(x["ret"] for x in rets) / n
        return {"n": n, "win_rate": round(win, 4), "avg_ret": round(avg, 4)}

    buy_stat = stats(buy_rets)
    sell_stat = stats(sell_rets)
    print(f"    买入 {buy_stat['n']} 笔：胜率 {buy_stat['win_rate']*100:.1f}%"
          f"，平均 {buy_stat['avg_ret']*100:+.2f}%")
    print(f"    卖出 {sell_stat['n']} 笔：胜率 {sell_stat['win_rate']*100:.1f}%"
          f"，平均 {sell_stat['avg_ret']*100:+.2f}%"
          f"（卖后涨=卖早，卖后跌=卖对）")

    # ---------- ③ 现势层 ----------
    latest_sec = section_ranks[-1]
    current = []
    for c, b in sorted(recent.items(), key=lambda x: -(
            (latest_sec["rank_map"].get(x[0], (0, 1, 0))[2]))):
        if c in latest_sec["rank_map"]:
            rk, n, sc = latest_sec["rank_map"][c]
            pr = 1.0 - (rk - 1) / n
            current.append({
                "code": c, "name": b["name"], "score": round(sc, 1),
                "rank": rk, "pool_n": n, "pct_rank": round(pr, 4),
                "quintile": quintile(pr),
                "buy_cnt": b["buy_cnt"], "sell_cnt": b["sell_cnt"],
                "first_buy": b["first_buy"], "last": b["last"],
            })

    # 汇总输出
    out = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "asof": latest_sec["date"],
        "forward": FORWARD,
        "universe": {
            "pool": len(klines),
            "weights_source": "factor_ic.json",
            "traded_with_kline": len(by_code),
            "recent": len(recent),
            "early": len(early),
        },
        "layer1_selection": {
            "first_buys": selection,
            "scored": len(scored_sel),
            "hit_count": hit,
            "hit_rate": round(hit / len(scored_sel), 4) if scored_sel else None,
        },
        "layer2_timing": {
            "buy": {"stats": buy_stat, "trades": buy_rets},
            "sell": {"stats": sell_stat, "trades": sell_rets},
        },
        "layer3_current": current,
    }
    out_path = os.path.join(CACHE_DIR, "trades_factor_backtest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print("\n" + "=" * 88)
    print(f"③ 现势层：{len(current)} 只近期交易股当前因子状态（截至 {latest_sec['date']}）")
    print("=" * 88)
    print(f"{'代码':<8}{'名称':<10}{'综合分':>7}{'排名':>7}{'分位':>8}{'档位':>9}{'买卖':>8}")
    print("-" * 88)
    for h in current:
        print(f"{h['code']:<8}{h['name']:<10}{h['score']:>7.1f}"
              f"{h['rank']:>6}/{h['pool_n']}{h['pct_rank']*100:>7.1f}%"
              f"{h['quintile']:>9}{h['buy_cnt']}买{h['sell_cnt']}卖")

    # 现势分位分布
    strong = sum(1 for h in current if h["pct_rank"] >= 0.6)
    weak = sum(1 for h in current if h["pct_rank"] < 0.4)
    mid = len(current) - strong - weak
    print(f"\n现势分布：偏强(≥60%) {strong} 只｜中性 {mid} 只｜偏弱(<40%) {weak} 只")

    print("\n" + "=" * 88)
    print(f"完成，耗时 {(datetime.datetime.now() - t0).total_seconds():.1f}s → {out_path}")
    print("⚠️ 未计交易成本/涨跌停/T+1；forward 收益未剔除大盘 beta。")


if __name__ == "__main__":
    main()
