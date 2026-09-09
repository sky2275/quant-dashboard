#!/usr/bin/env python3
"""
对 9 只持仓股做"实际持仓 vs 三仓策略"对比回测。

输入：
  - cache/holdings.json（最新持仓）
  - cache/holdings_kline_20260908.json（9 只股 181 根 K 线）
  - cache/factor_ic.json（因子 IC 状态 → 权重）

输出：
  - cache/holdings_backtest_20260908.json
    {
      "summary": {"total_mv":..., "total_cost":..., "actual_pnl":..., "discipline_pnl":..., "discipline_save":...},
      "positions": [
        {
          "code":..., "name":..., "account":..., "bucket":..., "cost":..., "qty":..., "cur_price":...,
          "max_high":..., "max_drawdown_pct":...,
          "factor_score_now":..., "factor_pct_rank_now":...,  # 当前综合分与分位
          "first_buy_factor_score":...,  # 历史首买因子分位（若有）
          "actual_pnl":..., "actual_pnl_pct":...,
          "stop_price":..., "would_have_stopped":bool, "stop_date":..., "discipline_pnl":..., "discipline_diff":...
        }
      ]
    }
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from factor_lib import compute_raw, score_stock_raw, base_weights, adjust_weights, FACTORS

ROOT = Path("/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard")
HOLD = ROOT / "cache" / "holdings.json"
KL = ROOT / "cache" / "holdings_kline_20260908.json"
IC = ROOT / "cache" / "factor_ic.json"
OUT = ROOT / "cache" / "holdings_backtest_20260908.json"

def calc_max_drawdown(kline):
    """从 K 线算期间最大回撤（峰值到谷底）。"""
    if not kline: return 0, 0, ""
    high_so_far = kline[0]["close"]
    high_idx = 0
    max_dd = 0
    dd_low_idx = 0
    for i, k in enumerate(kline):
        c = k["close"]
        if c > high_so_far:
            high_so_far = c
            high_idx = i
        dd = (c - high_so_far) / high_so_far
        if dd < max_dd:
            max_dd = dd
            dd_low_idx = i
    return max_dd, high_so_far, kline[dd_low_idx]["date"]

def to_kl_list(k_dict_list):
    """dict 列表 → factor_lib 要求的 [date, open, close, high, low, volume] 列表。"""
    return [[r["date"], r["open"], r["close"], r["high"], r["low"], r["volume"]] for r in k_dict_list]

def calc_factor_now(kl, weights, flips):
    """当前因子综合分（按 IC 状态加权）。"""
    if len(kl) < 60: return None
    raws = compute_raw(to_kl_list(kl), code=None)
    valid = {k: v for k, v in raws.items() if v is not None}
    if not valid: return None
    scored = score_stock_raw(raws, weights, flips)
    return scored

def calc_factor_history(kl, step, weights, flips):
    """历史因子综合分曲线（每 step 日取一个分位）。"""
    series = []
    if len(kl) < 60: return series
    for end in range(60, len(kl)+1, step):
        sub = kl[:end]
        if len(sub) < 60: continue
        raws = compute_raw(to_kl_list(sub), code=None)
        sc = score_stock_raw(raws, weights, flips)
        if sc is not None:
            series.append({"date": sub[-1]["date"], "score": sc})
    return series

def main():
    with open(HOLD) as f: h = json.load(f)
    with open(KL) as f: kd = json.load(f)
    with open(IC) as f: ic = json.load(f)

    # 因子权重（base + IC 状态调整 + flips）
    bw = base_weights()
    factor_status = {f: ic.get("factors", {}).get(f, {}).get("status", "insufficient") for f in FACTORS}
    flips = {f: ic.get("factors", {}).get(f, {}).get("flip", False) for f in FACTORS}
    weights = adjust_weights(bw, factor_status)
    print(f"权重: {len(weights)} 因子, 总和 {sum(weights.values()):.3f}, flips {sum(flips.values())}")

    positions = h["positions"]
    summary = {
        "actual_total_pnl": 0,
        "discipline_total_pnl": 0,
        "stop_triggered_count": 0,
        "long_count": 0,
        "short_count": 0,
    }

    out_positions = []
    for p in positions:
        code = p["code"]; name = p["name"]; account = p["account"]
        bucket = p.get("bucket", "short"); stop_pct = p.get("stop_loss_pct", 0.08)
        cost = p["avg_cost"]; qty = p["quantity"]

        k = kd["codes"].get(code, {}).get("kline", [])
        if not k:
            print(f"⚠️ {code} {name} 无 K 线，跳过")
            continue

        # 当前价（9/8 收盘）
        cur = k[-1]["close"]

        # 回测只看最近 90 个交易日（约 4 个月），避免回测起点极低价干扰
        LOOKBACK = 90
        recent_k = k[-LOOKBACK:] if len(k) > LOOKBACK else k
        max_high = max(r["high"] for r in recent_k)
        max_dd, peak, dd_date = calc_max_drawdown(recent_k)
        stop_price = cost * (1 - stop_pct)

        # 实际盈亏（按 9/8 收盘）
        actual_pnl = (cur - cost) * qty
        actual_pnl_pct = (cur / cost - 1) * 100

        # 期间是否触及止损线？（只看最近 90 个交易日）
        would_have_stopped = False
        stop_date = ""
        stop_price_actual = cost
        for i, bar in enumerate(recent_k):
            lo = bar["low"]
            if lo <= stop_price:
                # 模拟次日开盘止损（用次日开盘价近似）
                if i + 1 < len(k):
                    exit_px = k[i+1]["open"]
                else:
                    exit_px = stop_price  # 当日即止损
                would_have_stopped = True
                stop_date = bar["date"]
                stop_price_actual = exit_px
                break

        if would_have_stopped:
            discipline_pnl = (stop_price_actual - cost) * qty
            summary["stop_triggered_count"] += 1
        else:
            discipline_pnl = actual_pnl  # 仍持有到最后

        # 因子分位
        try:
            fac_now = calc_factor_now(k, weights, flips)
            factor_score_now = fac_now.get("total_score") if isinstance(fac_now, dict) else None
        except Exception as e:
            factor_score_now = None
            print(f"  ⚠️ {code} factor 计算失败: {e}")

        # 历史因子分位曲线（每月 1 个采样）
        fac_history = calc_factor_history(k, step=20, weights=weights, flips=flips)

        # 仓位档位计数
        if bucket == "long": summary["long_count"] += 1
        else: summary["short_count"] += 1

        summary["actual_total_pnl"] += actual_pnl
        summary["discipline_total_pnl"] += discipline_pnl

        out_positions.append({
            "code": code, "name": name, "account": account,
            "bucket": bucket, "stop_pct": stop_pct,
            "cost": cost, "qty": qty, "cur_price": cur,
            "market_value": round(cur*qty, 2),
            "max_high": round(max_high, 2),
            "max_drawdown_pct": round(max_dd*100, 2),
            "max_drawdown_date": dd_date,
            "stop_price": round(stop_price, 3),
            "would_have_stopped": would_have_stopped,
            "stop_date": stop_date,
            "stop_exit_price": round(stop_price_actual, 3) if would_have_stopped else None,
            "actual_pnl": round(actual_pnl, 2),
            "actual_pnl_pct": round(actual_pnl_pct, 2),
            "discipline_pnl": round(discipline_pnl, 2),
            "discipline_diff": round(discipline_pnl - actual_pnl, 2),  # 正=止损更划算
            "factor_score_now": round(factor_score_now, 1) if factor_score_now else None,
            "factor_score_history_sample": fac_history[-6:] if fac_history else [],
        })

    # 排序：discipline_diff 降序（最该止损的排前）
    out_positions.sort(key=lambda x: -x["discipline_diff"])

    # 总结
    summary["actual_total_pnl"] = round(summary["actual_total_pnl"], 2)
    summary["discipline_total_pnl"] = round(summary["discipline_total_pnl"], 2)
    summary["discipline_save"] = round(summary["discipline_total_pnl"] - summary["actual_total_pnl"], 2)

    out = {
        "asof": "2026-09-08",
        "summary": summary,
        "positions": out_positions,
        "method": "三仓策略对比回测：每只股检查 K 线最低价是否触及止损线，模拟次日开盘价止损卖出；与持有到 9/8 的实际盈亏对比。",
        "factor_score_note": "factor_score_now 用 factor_lib 31 因子 IC 加权综合分（0-100）；factor_score_history_sample 取近 6 次月度采样。",
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"\n=== 三仓策略 vs 实际持仓 对比 ===")
    print(f"实际持仓盈亏:  {summary['actual_total_pnl']:>+12,.0f} 元")
    print(f"按纪律止损盈亏: {summary['discipline_total_pnl']:>+12,.0f} 元")
    print(f"止损纪律相对实际节省/损失: {summary['discipline_save']:>+12,.0f} 元（正=止损更划算）")
    print(f"止损触发: {summary['stop_triggered_count']} / 10 仓位")
    print()
    print(f"{'代码':<8}{'名称':<8}{'账户':<10}{'档位':<6}{'成本':<8}{'现价':<8}{'实际%':<8}{'止损':<6}{'应止损':<8}{'纪律差':<10}")
    for p in out_positions:
        print(f"{p['code']:<8}{p['name']:<8}{p['account']:<10}{p['bucket']:<6}{p['cost']:<8.2f}{p['cur_price']:<8.2f}{p['actual_pnl_pct']:>+6.1f}%  {p['stop_pct']*100:>4.0f}%  {'✅ '+p['stop_date'] if p['would_have_stopped'] else '—':<8}{p['discipline_diff']:>+8,.0f}")
    print(f"\n✅ 落盘 {OUT}")

if __name__ == "__main__":
    main()