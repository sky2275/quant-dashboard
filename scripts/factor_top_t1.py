#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
factor_top_t1.py — 量化雷达 Top10 进攻池 T+1 回测验证

================================================================================
背景
================================================================================
signal.py 的 factor_top（28 因子新体系全池排名 Top10）是「当天快照」，每次刷新
都会覆盖，没有历史记录，无法回答「这个进攻池到底选得准不准」。

本脚本做两件事：
  1. 无前视回溯验证：对最近 N 个交易日 D，用「截至 D 收盘」的 28 因子重算 Top10，
     然后用 D 的下一个交易日（T+1）的真实收盘价验证涨跌幅，汇总命中率 + 超额收益。
  2. 最新快照：把最新一个交易日（尚无次日数据）的 Top10 名单 + 入场价列出，
     标注「待结算」，等次日收盘后自动进入回溯验证。

================================================================================
无前视保证（关键）
================================================================================
- 对信号日 D，只把「date <= D」的 K 线喂给 multi_factor.score_stock。
- factor_lib.compute_raw(code=) 会按 K 线切片里的日期对齐注入资金流/基本面/估值，
  因此天然只用到「截至 D」的外部数据，不存在用未来数据选股的偷看。
- 市场基准 market_ctx 用全量日K构建、按日期切片对齐（与 rank_stocks 一致，无前视）。

================================================================================
口径
================================================================================
- c2c（收盘→收盘）：(D+1 收盘 - D 收盘) / D 收盘 × 100 —— 主口径，等价「D 收盘选股、
  D+1 全天持有」。
- o2c（开盘→收盘）：(D+1 收盘 - D+1 开盘) / D+1 开盘 × 100 —— 实战口径（D+1 开盘买入）。
- baseline_c2c：全池 297 只等权 D→D+1 平均涨跌幅，用于算超额收益 excess = avg_c2c - baseline。

================================================================================
数据源 / 输出
================================================================================
数据源：cache/backtest_klines.json（297 池前复权日K，格式 [date, open, close, high, low, volume]）
输出：cache/factor_top_t1.json

用法：
  python3 scripts/factor_top_t1.py [--days 10] [--top 10]
"""
import json
import os
import sys
import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
sys.path.insert(0, os.path.join(REPO, "scripts"))

import factor_lib as flib   # noqa: E402
import multi_factor as mf    # noqa: E402


def _load_pool() -> dict:
    """读 297 池，返回 {code: {name, kline}}；文件缺失返回空。"""
    path = os.path.join(CACHE, "backtest_klines.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("stocks") or {}
    except Exception:
        return {}


def _all_trade_dates(stocks: dict) -> list:
    """全池所有交易日并集，升序。"""
    ds = set()
    for s in stocks.values():
        for k in s.get("kline", []):
            ds.add(str(k[0]))
    return sorted(ds)


def _rank_at(stocks: dict, asof_date: str, mkt_ctx: dict, top_n: int) -> list:
    """用「截至 asof_date」的 K 线评分，返回 Top K（含 asof 当日收盘价）。"""
    results = []
    for code, s in stocks.items():
        klines = s.get("kline") or []
        sliced = [k for k in klines if str(k[0]) <= asof_date]
        if len(sliced) < 20:
            continue
        dates = [str(k[0]) for k in sliced[-flib.MAX_LOOKBACK:]]
        ctx = flib.slice_market_ctx(mkt_ctx, dates)
        try:
            r = mf.score_stock(sliced, ctx, code=code)
        except Exception:
            continue
        r["code"] = code
        r["name"] = s.get("name", code)
        r["asof_close"] = float(sliced[-1][2])
        results.append(r)
    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results[:top_n]


def _next_date_map(dates: list) -> dict:
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _backtest(stocks: dict, dates: list, nxt: dict, mkt_ctx: dict,
              days: int, top_n: int) -> list:
    """对最近 days 个「有次日」的信号日做回溯验证。"""
    signal_dates = dates[-(days + 1):-1]  # 最近的 days 个有 T+1 的交易日
    history = []
    for D in signal_dates:
        D1 = nxt[D]
        top = _rank_at(stocks, D, mkt_ctx, top_n)
        picks = []
        win = 0
        settled = 0
        c2c_sum = 0.0
        o2c_sum = 0.0
        for r in top:
            kl = stocks[r["code"]]["kline"]
            d1 = next((k for k in kl if str(k[0]) == D1), None)
            entry = r["asof_close"]
            if not d1 or not entry:
                picks.append({
                    "code": r["code"], "name": r["name"],
                    "score": r["total_score"], "entry": entry,
                    "c2c": None, "o2c": None,
                })
                continue
            d1_open = float(d1[1])
            d1_close = float(d1[2])
            c2c = (d1_close - entry) / entry * 100
            o2c = (d1_close - d1_open) / d1_open * 100 if d1_open else None
            settled += 1
            if c2c > 0:
                win += 1
            c2c_sum += c2c
            o2c_sum += (o2c or 0)
            picks.append({
                "code": r["code"], "name": r["name"],
                "score": r["total_score"], "entry": entry,
                "t1_close": d1_close,
                "c2c": round(c2c, 2), "o2c": round(o2c, 2) if o2c is not None else None,
            })
        # 全池等权基准（D -> D+1）
        base_sum = 0.0
        base_n = 0
        for code, s in stocks.items():
            kl = s.get("kline") or []
            d_c = next((float(k[2]) for k in kl if str(k[0]) == D), None)
            d1_c = next((float(k[2]) for k in kl if str(k[0]) == D1), None)
            if d_c and d1_c:
                base_sum += (d1_c - d_c) / d_c * 100
                base_n += 1
        baseline = round(base_sum / base_n, 2) if base_n else None
        avg_c2c = round(c2c_sum / settled, 2) if settled else None
        avg_o2c = round(o2c_sum / settled, 2) if settled else None
        history.append({
            "signal_date": D, "t1_date": D1,
            "win": win, "n": settled,
            "avg_c2c": avg_c2c, "avg_o2c": avg_o2c,
            "baseline_c2c": baseline,
            "excess_c2c": round(avg_c2c - baseline, 2) if (avg_c2c is not None and baseline is not None) else None,
            "top": picks,
        })
    return history


def _latest(stocks: dict, dates: list, nxt: dict, mkt_ctx: dict, top_n: int) -> dict:
    """最新交易日（尚无次日）的 Top10 快照，标注待结算。"""
    if not dates:
        return {"signal_date": None, "t1_date": None, "status": "no_data", "top": []}
    D = dates[-1]
    D1 = nxt.get(D)  # 通常为 None（尚未到下一交易日）
    top = _rank_at(stocks, D, mkt_ctx, top_n)
    return {
        "signal_date": D,
        "t1_date": D1,
        "status": "pending" if D1 is None else "settled",
        "top": [
            {"code": r["code"], "name": r["name"], "score": r["total_score"],
             "entry_close": r["asof_close"]}
            for r in top
        ],
    }


def _summarize(history: list) -> dict:
    if not history:
        return {"days": 0}
    total_picks = sum(h["n"] for h in history)
    total_win = sum(h["win"] for h in history)
    c2c_vals = [h["avg_c2c"] for h in history if h["avg_c2c"] is not None]
    o2c_vals = [h["avg_o2c"] for h in history if h["avg_o2c"] is not None]
    excess_vals = [h["excess_c2c"] for h in history if h["excess_c2c"] is not None]
    beat_days = sum(1 for h in history if h["excess_c2c"] is not None and h["excess_c2c"] > 0)
    return {
        "days": len(history),
        "total_picks": total_picks,
        "win_rate_c2c": round(total_win / total_picks, 3) if total_picks else None,
        "avg_c2c": round(sum(c2c_vals) / len(c2c_vals), 2) if c2c_vals else None,
        "avg_o2c": round(sum(o2c_vals) / len(o2c_vals), 2) if o2c_vals else None,
        "avg_excess_c2c": round(sum(excess_vals) / len(excess_vals), 2) if excess_vals else None,
        "beat_market_days": beat_days,
        "beat_market_total": len(excess_vals),
    }


def main():
    days = 10
    top_n = 10
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--days" and i + 1 < len(argv):
            days = int(argv[i + 1])
        if a == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])

    stocks = _load_pool()
    if not stocks:
        print("[factor_top_t1] backtest_klines.json 缺失或为空，退出")
        return

    dates = _all_trade_dates(stocks)
    nxt = _next_date_map(dates)
    all_kl = {c: s.get("kline", []) for c, s in stocks.items() if s.get("kline")}
    mkt_ctx = flib.build_market_ctx(all_kl) if all_kl else {}

    history = _backtest(stocks, dates, nxt, mkt_ctx, days, top_n)
    latest = _latest(stocks, dates, nxt, mkt_ctx, top_n)

    out = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "asof": dates[-1] if dates else None,
        "params": {"days": days, "top_n": top_n},
        "summary": _summarize(history),
        "history": history,
        "latest": latest,
    }
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "factor_top_t1.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    s = out["summary"]
    print(f"[factor_top_t1] 回溯 {s['days']} 天，共 {s['total_picks']} 次选股")
    if s.get("win_rate_c2c") is not None:
        print(f"  命中率(c2c) {s['win_rate_c2c']*100:.1f}%  平均收益 {s['avg_c2c']:+.2f}%  "
              f"超额 {s['avg_excess_c2c']:+.2f}%  跑赢市场 {s['beat_market_days']}/{s['beat_market_total']} 天")
    print(f"  最新快照 {latest['signal_date']} → {latest.get('t1_date') or '待结算'}（{latest['status']}）")


if __name__ == "__main__":
    main()
