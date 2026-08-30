"""
factor_holdings_backtest.py -- 实际持仓数据接入因子回测体系

任务（用户诉求：把实际持仓数据用在因子回测上，输出回测结果）：
  1. 确保 6 只实际持仓股全部进入回测池（缺失的现场抓取腾讯前复权日K补齐）
  2. 复用 factor_ic.json 最新生效权重 + 翻转标记，对全池最新截面（截至最新交易日）评分
  3. 输出 6 只持仓股：综合评分、池内排名、分位、Q1~Q5 档位、有效因子明细
  4. 输出 6 只持仓股历史排名分位走势（滚动无前视截面，复用 build_panel）
  5. 附全池滚动分层回测对照（A新体系 / B旧体系 / C等权，复用 factor_backtest.json）

输出：cache/factor_holdings_backtest.json

⚠️ 回测含简化假设（不计交易成本/涨跌停/T+1），结果用于诊断
   "持仓股在因子体系里的相对强弱"，不是实盘收益预测。
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

# 实际持仓（来自 cache/holdings.json 的 positions，含三券商）
HOLDINGS = [
    ("002156", "通富微电"),
    ("300223", "君正股份"),
    ("003033", "征和工业"),
    ("300499", "高澜股份"),
    ("300579", "数字认证"),
    ("600487", "亨通光电"),
]

# 关键因子（已验证有效 + 当前权重靠前），用于明细表
KEY_FACTORS = [
    "mom_120_20",   # 120→20日中期动量（双验证有效）
    "ma_slope60",   # MA60斜率（胜率79%）
    "macd_hist",    # MACD柱
    "rev_5d",       # 短期反转（IC 0.44）
    "mom_20d",      # 20日涨幅（已翻转→短期反转）
    "trend_ma20",   # 均线位置（已翻转）
    "mf_main_ratio",# 主力净流入占比（IC_IR 0.65 全表第一）
    "profit_yoy",   # 净利润同比（IC_IR 0.48）
    "roe",          # ROE（弱信号）
]

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _full_code(code: str) -> str:
    s = str(code).strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.startswith("6"):
        return f"sh{s}"
    if s[:2] in ("00", "30", "39"):
        return f"sz{s}"
    if s[:1] in ("8", "4"):
        return f"bj{s}"
    return f"sh{s}"


def fetch_kline(code: str, days: int = 500) -> list:
    """腾讯前复权日K → [[date,open,close,high,low,volume],...] 旧→新。"""
    full = _full_code(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={full},day,,,{days},qfq")
    try:
        import requests
        r = requests.get(url, headers=UA, timeout=25)
        arr = r.json().get("data", {}).get(full, {}).get("qfqday", [])
        out = []
        for row in arr:
            if len(row) >= 6:
                out.append([row[0], float(row[1]), float(row[2]),
                            float(row[3]), float(row[4]), float(row[5])])
        return out
    except Exception as e:
        print(f"  [kline] {code} 抓取失败: {e}")
        return []


def load_pool() -> tuple[dict, dict]:
    """加载回测池 {code: kline} + {code: name}，并补齐缺失持仓股（幂等写回）。"""
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    stocks = data.get("stocks", {})
    klines: dict[str, list] = {}
    names: dict[str, str] = {}
    for code, st in stocks.items():
        kl = st.get("kline") or []
        if kl:
            klines[code] = kl
            names[code] = st.get("name", code)

    missing = [c for c, _ in HOLDINGS if c not in klines or len(klines[c]) < 60]
    if missing:
        print(f"[holdings_bt] 补齐缺失持仓股K线：{missing}")
        for code in missing:
            kl = fetch_kline(code, 500)
            if kl:
                klines[code] = kl
                name = dict(HOLDINGS)[code]
                names[code] = name
                stocks[code] = {
                    "name": name, "full_code": _full_code(code),
                    "kline": kl, "signals": {},
                }
                print(f"    {code} {name}: {len(kl)} 根")
            else:
                print(f"    ⚠️ {code} 抓取失败，跳过")
        # 幂等写回主文件
        data["stocks"] = stocks
        data["count"] = len(stocks)
        data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return klines, names


def latest_snapshot(klines: dict, names: dict,
                    weights: dict, flips: dict) -> tuple[list, str]:
    """对全池最新一个交易日做横截面评分，返回 [(code,score,coverage,factor_scores)] 降序 + 日期。"""
    mkt_ctx = flib.build_market_ctx(klines)
    latest = max(kl[-1][0] for kl in klines.values())
    rows = []
    for code, kl in klines.items():
        raw = flib.compute_raw(kl, mkt_ctx, names=flib.FACTOR_NAMES, code=code)
        res = flib.score_stock_raw(raw, weights, flips)
        rows.append((code, res["total_score"], res["coverage"],
                     res["factor_scores"]))
    rows.sort(key=lambda x: -x[1])
    return rows, str(latest)


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


def dir_light(score: float) -> str:
    if score >= 65:
        return "🟢强"
    if score >= 55:
        return "🟡偏强"
    if score >= 45:
        return "⚪中性"
    if score >= 35:
        return "🟠偏弱"
    return "🔴弱"


def history_pct_rank(klines: dict, weights: dict, flips: dict,
                     forward: int = 5, step: int = 20) -> dict:
    """滚动无前视截面，输出每只持仓股的历史排名分位 + 综合评分序列。"""
    built = fbt.build_panel(klines, forward, step)
    panel, names = built["panel"], built["names"]
    dates = [sec["date"] for sec in panel]

    hist: dict[str, dict] = {c: {"name": n, "pct": [], "score": [],
                                 "in_section": []}
                             for c, n in HOLDINGS}
    for sec in panel:
        ranked = fbt.score_cross_section(sec["rows"], names, weights, flips)
        n = len(ranked)
        if n < 15:
            continue
        rank_map = {c: i + 1 for i, (c, _) in enumerate(ranked)}
        for c, _ in HOLDINGS:
            if c in rank_map:
                hist[c]["pct"].append(round(1 - (rank_map[c] - 1) / n, 4))
                hist[c]["score"].append(
                    round([s for cc, s in ranked if cc == c][0], 1))
                hist[c]["in_section"].append(True)
            else:
                hist[c]["pct"].append(None)
                hist[c]["score"].append(None)
                hist[c]["in_section"].append(False)
    return {"dates": dates, "codes": hist}


def main() -> None:
    t0 = datetime.datetime.now()
    print("=" * 84)
    print("实际持仓数据 → 因子回测")
    print("=" * 84)

    # 1) 权重 + 翻转（复用最新 factor_ic.json）
    ic_path = os.path.join(CACHE_DIR, "factor_ic.json")
    with open(ic_path, encoding="utf-8") as f:
        ic = json.load(f)
    weights, flips = ic["weights"], ic["flips"]
    print(f"[1/4] 生效权重来自 factor_ic.json（{ic.get('updated_at')}）"
          f"｜翻转因子：{', '.join(flips) or '无'}")

    # 2) 回测池（补齐缺失持仓）
    klines, names = load_pool()
    print(f"[2/4] 回测池 {len(klines)} 只（含 6 只持仓）")

    # 3) 最新截面评分 + 持仓排名
    rows, asof = latest_snapshot(klines, names, weights, flips)
    n_pool = len(rows)
    rank_map = {c: i + 1 for i, (c, *_r) in enumerate(rows)}
    score_map = {c: (s, cov, fs) for c, s, cov, fs in rows}
    print(f"[3/4] 最新截面 {asof} 全池 {n_pool} 只评分完成")

    # 4) 历史排名分位
    hist = history_pct_rank(klines, weights, flips)
    print(f"[4/4] 历史滚动截面 {len(hist['dates'])} 期")

    # ---- 汇总输出 ----
    print("\n" + "=" * 84)
    print(f"6 只持仓股 · 因子评分体检（截至 {asof}，池内 {n_pool} 只）")
    print("=" * 84)
    print(f"{'代码':<8}{'名称':<10}{'综合分':>7}{'排名':>6}{'分位':>7}{'档位':>9}")
    print("-" * 84)
    holdings_out = []
    for c, nm in HOLDINGS:
        if c not in score_map:
            print(f"{c:<8}{nm:<10}  ⚠️ 不在池/无评分")
            continue
        sc, cov, fs = score_map[c]
        rk = rank_map[c]
        pr = 1 - (rk - 1) / n_pool
        q = quintile(pr)
        holdings_out.append({
            "code": c, "name": nm, "score": round(sc, 1),
            "rank": rk, "pct_rank": round(pr, 4), "quintile": q,
            "coverage": cov, "factor_scores": fs,
        })
        print(f"{c:<8}{nm:<10}{sc:>7.1f}{rk:>6}/{n_pool}"
              f"{pr * 100:>6.1f}%{q:>9}")

    # 组合汇总
    if holdings_out:
        avg_sc = sum(h["score"] for h in holdings_out) / len(holdings_out)
        avg_pr = sum(h["pct_rank"] for h in holdings_out) / len(holdings_out)
        print("-" * 84)
        print(f"持仓组合：平均综合分 {avg_sc:.1f}｜平均分位 {avg_pr * 100:.1f}%｜"
              f"{'整体偏强' if avg_pr >= 0.55 else ('整体偏弱' if avg_pr <= 0.45 else '整体中性')}")

    # ---- 关键因子明细 ----
    print("\n" + "=" * 84)
    print("关键因子明细（score 已应用翻转，0-100，越高越看多）")
    print("=" * 84)
    header = "".join(f"{flib.FACTORS[k]['label'][:8]:>10}" for k in KEY_FACTORS)
    print(f"{'名称':<10}{header}")
    print("-" * 84)
    for h in holdings_out:
        fs = h["factor_scores"]
        cells = ""
        for k in KEY_FACTORS:
            v = fs.get(k)
            if v is None:
                cells += f"{'—':>10}"
            else:
                cells += f"{v:>9.0f} "
        print(f"{h['name']:<10}{cells}")

    # ---- 历史分位走势摘要 ----
    print("\n" + "=" * 84)
    print("历史排名分位走势（当前因子体系回看，分位 50% = 池中位数）")
    print("=" * 84)
    dates = hist["dates"]
    print(f"{'名称':<10}" + "".join(f"{d[5:]:>7}" for d in dates))
    print("-" * 84)
    for c, nm in HOLDINGS:
        hh = hist["codes"][c]
        cells = ""
        for p in hh["pct"]:
            cells += f"{'—':>7}" if p is None else f"{p * 100:>6.0f}% "
        print(f"{nm:<10}{cells}")

    # ---- 全池回测对照（复用）----
    bt_path = os.path.join(CACHE_DIR, "factor_backtest.json")
    full_bt = {}
    if os.path.exists(bt_path):
        with open(bt_path, encoding="utf-8") as f:
            full_bt = json.load(f)

    # ---- 写 JSON ----
    out = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "asof": asof,
        "universe": {"stocks": n_pool,
                     "weights_source": ic.get("updated_at")},
        "weights": weights,
        "flips": flips,
        "full_pool_backtest": full_bt,
        "holdings_latest": holdings_out,
        "holdings_history": {
            "dates": dates,
            "codes": {c: {"name": v["name"], "pct_rank": v["pct"],
                          "score": v["score"], "in_section": v["in_section"]}
                      for c, v in hist["codes"].items()},
        },
        "summary": {
            "avg_score": round(sum(h["score"] for h in holdings_out) / len(holdings_out), 1) if holdings_out else None,
            "avg_pct_rank": round(sum(h["pct_rank"] for h in holdings_out) / len(holdings_out), 4) if holdings_out else None,
        },
    }
    out_path = os.path.join(CACHE_DIR, "factor_holdings_backtest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 84)
    print(f"已完成，耗时 {(datetime.datetime.now() - t0).total_seconds():.1f}s")
    print(f"结果已写入 {out_path}")
    print("⚠️ 未计交易成本/涨跌停/T+1；结果用于诊断持仓在因子体系中的相对强弱。")


if __name__ == "__main__":
    main()
