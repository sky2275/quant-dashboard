"""
factor_backtest.py -- 因子体系的滚动分层回测（补因子后的验收工具）

================================================================================
为什么需要这个
================================================================================
IC 只是"因子值与未来收益的相关性"，它不等于"这套因子选股能赚钱"。
补完因子必须回答三个问题：
  Q1 新因子体系选出来的股票，实际收益比旧体系高吗？
  Q2 比全市场等权（不择股）高吗？
  Q3 这个优势是稳定的，还是靠某几期撑起来的？

本脚本用**滚动无前视**的方式回答：
  在第 k 期打分时，只使用第 1..k-1 期的 IC 来定权重和翻转方向，
  绝不用到 k 期及之后的任何信息。这是唯一可信的验证方式。

================================================================================
三组对照
================================================================================
  A 新体系  : 20 因子 + IC 动态权重 + 反向因子翻转（滚动，无前视）
  B 旧体系  : 旧 5 因子 + 固定权重 0.25/0.15/0.25/0.15/0.20 + 不翻转
              （还原 v1 的行为，作为改造前的基准）
  C 等权基准: 全样本等权买入（不选股）

指标：每期把股票按得分分 5 组，Q1=得分最高组，Q5=最低组。
     看各组平均 5 日收益、Q1-Q5 多空价差、以及多空的信息比率。

⚠️ 回测含简化假设（不计交易成本、涨跌停不可买、T+1），
   结果用于比较"因子体系 A/B 的相对优劣"，不是实盘收益预测。

用法：python3 factor_backtest.py [forward_days] [step]
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import factor_lib as flib  # noqa: E402

FORWARD = 5
STEP = 20
MIN_HISTORY_IC = 3      # 至少积累多少期 IC 才开始回测
N_GROUPS = 5

# 旧体系的 5 个因子（对应 v1 的 momentum/trend/volatility/vol_price/rsi）
LEGACY_FACTORS = ["mom_20d", "trend_ma20", "vol_atr", "vol_price", "rsi_mid"]
LEGACY_WEIGHTS = {
    "mom_20d": 0.25, "trend_ma20": 0.25, "vol_atr": 0.15,
    "vol_price": 0.15, "rsi_mid": 0.20,
}


# ---------------------------------------------------------------- 工具
def _rank(values: list[float]) -> list[float]:
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def _mean(v: list[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def _std(v: list[float]) -> float:
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def _ic_status(mean_ic: float, ic_ir: float, monotonic: bool = True) -> tuple[str, bool]:
    """与 factor_ic.build_report 保持一致的判定（局部复刻，避免循环 import）。"""
    if mean_ic < -flib.IC_THRESHOLD and abs(ic_ir) >= flib.IC_IR_SIGNIFICANT and monotonic:
        return "reversed", True
    if mean_ic < -flib.IC_THRESHOLD:
        return "negative", False
    if abs(mean_ic) < flib.IC_THRESHOLD:
        return "weak", False
    return "effective", False


# ---------------------------------------------------------------- 预计算
def build_panel(codes_klines: dict[str, list], forward: int, step: int) -> dict:
    """
    预计算「截面 × 股票」的因子值与前瞻收益。
    因子只算一次，滚动回测阶段纯查表，避免 O(n²) 重复计算。
    """
    names = flib.FACTOR_NAMES
    codes = list(codes_klines.keys())
    max_len = max(len(kl) for kl in codes_klines.values())
    start = max(max(flib.FACTORS[n]["min_bars"] for n in names),
                flib.MAX_LOOKBACK // 2)
    t_indices = list(range(start, max_len - forward, step))
    mkt_ctx = flib.build_market_ctx(codes_klines)

    panel: list[dict] = []
    for t in t_indices:
        rows: dict[str, dict] = {}
        for code in codes:
            kl = codes_klines[code]
            if len(kl) < t + forward + 1:
                continue
            close_t = float(kl[t][2])
            close_fwd = float(kl[t + forward][2])
            if close_t <= 0:
                continue
            window = kl[max(0, t + 1 - flib.MAX_LOOKBACK): t + 1]
            ctx = flib.slice_market_ctx(mkt_ctx, [str(k[0]) for k in window])
            raw = flib.compute_raw(window, ctx, names=names, code=code)
            if sum(1 for v in raw.values() if v is not None) < len(names) * 0.6:
                continue
            rows[code] = {
                "raw": raw,
                "fwd_ret": close_fwd / close_t - 1.0,
                "date": str(kl[t][0]),
            }
        if len(rows) >= 15:
            panel.append({"t": t, "date": str(
                codes_klines[codes[0]][t][0]) if codes else "", "rows": rows})
    return {"panel": panel, "names": names}


def ic_from_history(panel: list[dict], upto: int, names: list[str]) -> dict:
    """用第 0..upto-1 期计算各因子的 IC 序列（无前视）。"""
    series: dict[str, list[float]] = {n: [] for n in names}
    for k in range(upto):
        rows = panel[k]["rows"]
        codes = list(rows.keys())
        fwd = [rows[c]["fwd_ret"] for c in codes]
        for n in names:
            vals = [rows[c]["raw"].get(n) for c in codes]
            present = [v for v in vals if v is not None]
            if len(present) < 15:
                continue
            med = sorted(present)[len(present) // 2]
            x = [v if v is not None else med for v in vals]
            series[n].append(spearman(x, fwd))
    return series


def bt_evidence_from_history(panel: list[dict], upto: int,
                             names: list[str]) -> dict:
    """用第 0..upto-1 期计算单因子的分层多空收益（无前视）。
    与 factor_backtest.py --diag 的算法一致，只是只取历史部分。"""
    out: dict[str, dict] = {}
    for n in names:
        ls: list[float] = []
        for k in range(upto):
            rows = panel[k]["rows"]
            items = [(c, d["raw"].get(n)) for c, d in rows.items()]
            items = [(c, v) for c, v in items if v is not None]
            if len(items) < N_GROUPS * 3:
                continue
            items.sort(key=lambda x: x[1], reverse=True)
            size = len(items) // N_GROUPS
            top = items[:size]
            bot = items[-size:]
            ls.append(_mean([rows[c]["fwd_ret"] for c, _ in top])
                      - _mean([rows[c]["fwd_ret"] for c, _ in bot]))
        if ls:
            sd = _std(ls)
            out[n] = {"long_short": _mean(ls),
                      "ir": _mean(ls) / sd if sd > 0 else 0.0,
                      "win_rate": sum(1 for x in ls if x > 0) / len(ls)}
    return out


def weights_from_history(panel: list[dict], upto: int,
                         names: list[str]) -> tuple[dict, dict]:
    """
    滚动权重（无前视）：只用第 0..upto-1 期的 IC + 分层回测证据。
    与 factor_ic.build_report 采用同一套 combine_evidence 决策规则，
    保证回测结果能真实反映线上生效的因子机制。
    """
    series = ic_from_history(panel, upto, names)
    ic_stats: dict[str, dict] = {}
    for n, s in series.items():
        if len(s) < 2:
            ic_stats[n] = {"mean_ic": None, "ic_ir": 0.0,
                           "status": "insufficient", "n_periods": len(s)}
            continue
        m, sd = _mean(s), _std(s)
        ir = m / sd if sd > 0 else 0.0
        st, _ = _ic_status(m, ir, flib.FACTORS[n].get("monotonic", True))
        ic_stats[n] = {"mean_ic": m, "ic_ir": ir, "status": st,
                       "n_periods": len(s)}

    bt = bt_evidence_from_history(panel, upto, names)
    verdict = flib.combine_evidence(ic_stats, bt)
    w = flib.apply_evidence(flib.base_weights(), verdict)
    flips = {k: True for k, v in verdict.items() if v.get("flip")}
    return w, flips


def score_cross_section(rows: dict, names: list[str], weights: dict,
                        flips: dict) -> list[tuple[str, float]]:
    """给一个截面的所有股票打分，返回 [(code, score)] 降序。"""
    out = []
    for code, d in rows.items():
        res = flib.score_stock_raw(d["raw"], weights, flips)
        if res["coverage"] < 0.5:
            continue
        out.append((code, res["total_score"]))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


# ---------------------------------------------------------------- 单因子诊断
def run_diag(forward: int = FORWARD, step: int = STEP) -> dict:
    """
    单因子分层诊断：逐个因子做「按 raw 值分 5 组 → 看各组前瞻收益」。
    这是定位"到底是因子没用，还是权重机制拖后腿"的关键一步：
      · 单因子分层单调（Q1 > Q5）→ 因子有效，问题在组合权重
      · 单因子分层也不单调      → 因子本身在该样本上不成立
    """
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    kls = {c: s.get("kline", []) for c, s in data.get("stocks", {}).items()
           if s.get("kline")}
    built = build_panel(kls, forward, step)
    panel, names = built["panel"], built["names"]

    out: dict[str, dict] = {}
    for n in names:
        grp: list[list[float]] = [[] for _ in range(N_GROUPS)]
        ls: list[float] = []
        for sec in panel:
            rows = sec["rows"]
            items = [(c, d["raw"].get(n)) for c, d in rows.items()]
            items = [(c, v) for c, v in items if v is not None]
            if len(items) < N_GROUPS * 3:
                continue
            items.sort(key=lambda x: x[1], reverse=True)  # raw 越大越看好
            size = len(items) // N_GROUPS
            rets = []
            for g in range(N_GROUPS):
                seg = items[g * size: (g + 1) * size] if g < N_GROUPS - 1 \
                    else items[(N_GROUPS - 1) * size:]
                rets.append(_mean([rows[c]["fwd_ret"] for c, _ in seg]))
            for g in range(N_GROUPS):
                grp[g].append(rets[g])
            ls.append(rets[0] - rets[-1])
        if ls:
            out[n] = {
                "q1": _mean(grp[0]), "q5": _mean(grp[-1]),
                "long_short": _mean(ls),
                "ir": _mean(ls) / _std(ls) if _std(ls) > 0 else 0.0,
                "win_rate": sum(1 for x in ls if x > 0) / len(ls),
                "monotonic": all(
                    _mean(grp[i]) >= _mean(grp[i + 1]) - 0.0005
                    for i in range(N_GROUPS - 1)),
            }
    return out


# ---------------------------------------------------------------- 消融实验
def run_ablation(forward: int = FORWARD, step: int = STEP) -> dict:
    """
    因子子集消融：比较"用哪些因子"对选股效果的影响。
    统一用等权（排除权重机制干扰），只看**选哪批因子**的差别。

    全部 20 个都用，未必比只用通过双重检验的那几个更好 ——
    加了无效因子等于往信号里掺噪声，这是补因子最常见的误区。
    """
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    kls = {c: s.get("kline", []) for c, s in data.get("stocks", {}).items()
           if s.get("kline")}
    built = build_panel(kls, forward, step)
    panel, names = built["panel"], built["names"]

    # 用全样本诊断挑出分层多空为正的因子（仅用于构造子集，
    # 子集本身在下面的滚动回测里仍是等权、无前视的打分）
    diag = run_diag(forward=forward, step=step)
    positive = [n for n, d in diag.items() if d["long_short"] > 0]
    validated = [n for n, d in diag.items()
                 if d["long_short"] > 0 and d.get("win_rate", 0) >= 0.55]

    # 资金流因子 = 大类为「资金流向」的因子；基本面 = 「基本面」；估值 = 「估值」。
    flow = [n for n in names if flib.FACTORS[n].get("category") == "资金流向"]
    fund = [n for n in names if flib.FACTORS[n].get("category") == "基本面"]
    val = [n for n in names if flib.FACTORS[n].get("category") == "估值"]
    new_dim = flow + fund  # 有效新维度 = 资金流 + 基本面
    all_new = flow + fund + val  # 含估值的三新维度
    price_only = [n for n in names if n not in all_new]
    subsets = {
        "全部因子": names,
        "纯量价(无新维度)": price_only,
        "资金流因子": flow or ["mf_main_ratio"],
        "基本面因子": fund or ["profit_yoy"],
        "新维度(资金流+基本面)": new_dim,
        "估值因子(低估值偏好)": val or ["pe_pct", "pb_pct"],
        "三维(量价+资金流+基本面)": price_only + new_dim,
        "分层多空为正": positive or names,
        "双验证(多空>0且胜率≥55%)": validated or names,
        "趋势动量组": [n for n in ("ma_slope60", "mom_120_20", "macd_hist",
                                   "mom_20d", "trend_ma20") if n in names],
        "旧5因子": LEGACY_FACTORS,
    }

    out: dict[str, dict] = {}
    for tag, subset in subsets.items():
        w = {n: 1.0 / len(subset) for n in subset}
        ls: list[float] = []
        q1: list[float] = []
        for sec in panel:
            rows = sec["rows"]
            ranked = score_cross_section(rows, subset, w, {})
            if len(ranked) < N_GROUPS * 3:
                continue
            size = len(ranked) // N_GROUPS
            top = ranked[:size]
            bot = ranked[-size:]
            r_top = _mean([rows[c]["fwd_ret"] for c, _ in top])
            r_bot = _mean([rows[c]["fwd_ret"] for c, _ in bot])
            ls.append(r_top - r_bot)
            q1.append(r_top)
        if ls:
            sd = _std(ls)
            out[tag] = {
                "factors": subset, "n": len(subset),
                "q1": _mean(q1), "long_short": _mean(ls),
                "ir": _mean(ls) / sd if sd > 0 else 0.0,
                "win_rate": sum(1 for x in ls if x > 0) / len(ls),
            }
    return out


def report_ablation(ab: dict) -> None:
    print("\n" + "=" * 84)
    print("因子子集消融（统一等权，只看『用哪批因子』的差别）")
    print("=" * 84)
    print(f"{'因子子集':<26}{'数量':>5}{'Q1收益':>10}{'多空':>10}{'IR':>8}{'胜率':>8}")
    print("-" * 84)
    for tag, d in sorted(ab.items(), key=lambda kv: -kv[1]["long_short"]):
        print(f"{tag:<26}{d['n']:>5}{d['q1'] * 100:>9.2f}%"
              f"{d['long_short'] * 100:>9.2f}%{d['ir']:>8.2f}{d['win_rate']:>7.0%}")
    print("-" * 84)
    best = max(ab.items(), key=lambda kv: kv[1]["long_short"])
    print(f"最优子集：{best[0]}（多空 {best[1]['long_short'] * 100:+.2f}%，"
          f"IR {best[1]['ir']:.2f}，胜率 {best[1]['win_rate']:.0%}）")
    if best[1]["long_short"] <= 0:
        print("⚠️ 所有子集多空均为负：说明在该样本期（等权基准 "
              f"{'上涨' if ab and list(ab.values())[0]['q1'] > 0 else '震荡/下跌'}）"
              "上，量价类因子整体不具选股能力，"
              "问题不在因子数量，而在数据维度本身（缺资金流/基本面/估值）。")


def report_diag(diag: dict) -> None:
    print("\n" + "=" * 92)
    print("单因子分层诊断（按因子 raw 值分组，Q1=因子值最高组）")
    print("=" * 92)
    print(f"{'因子':<14}{'大类':<10}{'Q1':>8}{'Q5':>8}{'多空':>9}{'IR':>7}{'胜率':>7}{'单调':>6}")
    print("-" * 92)
    rows = sorted(diag.items(), key=lambda kv: -kv[1]["long_short"])
    for n, d in rows:
        print(f"{n:<14}{flib.FACTORS[n]['category']:<10}"
              f"{d['q1'] * 100:>7.2f}%{d['q5'] * 100:>7.2f}%"
              f"{d['long_short'] * 100:>8.2f}%{d['ir']:>7.2f}"
              f"{d['win_rate']:>6.0%}{'✅' if d['monotonic'] else '❌':>6}")
    print("-" * 92)
    good = [n for n, d in diag.items() if d["long_short"] > 0 and d["win_rate"] >= 0.5]
    print("多空为正且胜率≥50% 的因子:", ", ".join(good) or "无")
    print("解读：『单调✅』= Q1→Q5 收益递减，因子方向正确；"
          "『多空』为正 = 按该因子做多头部做空尾部能赚钱。")


# ---------------------------------------------------------------- 主流程
def run(forward: int = FORWARD, step: int = STEP) -> dict:
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    if not os.path.exists(path):
        print("[factor_bt] 缺少 backtest_klines.json")
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    kls = {c: s.get("kline", []) for c, s in data.get("stocks", {}).items()
           if s.get("kline")}
    if not kls:
        return {}

    print(f"[factor_bt] 预计算因子面板：{len(kls)} 只 × {forward}日前瞻 ...")
    built = build_panel(kls, forward, step)
    panel, names = built["panel"], built["names"]
    print(f"[factor_bt] 得到 {len(panel)} 个截面，从第 {MIN_HISTORY_IC + 1} 期开始滚动回测")

    results = {
        "A_new": {"groups": [[] for _ in range(N_GROUPS)], "ls": [], "dates": []},
        "B_legacy": {"groups": [[] for _ in range(N_GROUPS)], "ls": [], "dates": []},
        "C_equal": {"ret": [], "dates": []},
    }

    for k in range(MIN_HISTORY_IC, len(panel)):
        rows = panel[k]["rows"]
        date = panel[k]["date"]

        # ---- A：新体系（滚动 IC + 分层证据 定权重/翻转，无前视）----
        w_a, flips_a = weights_from_history(panel, k, names)
        ranked_a = score_cross_section(rows, names, w_a, flips_a)

        # ---- B：旧体系（固定 5 因子、固定权重、不翻转）----
        ranked_b = score_cross_section(rows, LEGACY_FACTORS, LEGACY_WEIGHTS, {})

        # ---- 分组收益 ----
        for tag, ranked in (("A_new", ranked_a), ("B_legacy", ranked_b)):
            n = len(ranked)
            if n < N_GROUPS * 3:
                continue
            size = n // N_GROUPS
            rets = []
            for g in range(N_GROUPS):
                seg = ranked[g * size: (g + 1) * size] if g < N_GROUPS - 1 \
                    else ranked[(N_GROUPS - 1) * size:]
                rets.append(_mean([rows[c]["fwd_ret"] for c, _ in seg]))
            for g in range(N_GROUPS):
                results[tag]["groups"][g].append(rets[g])
            results[tag]["ls"].append(rets[0] - rets[-1])
            results[tag]["dates"].append(date)

        results["C_equal"]["ret"].append(
            _mean([d["fwd_ret"] for d in rows.values()]))
        results["C_equal"]["dates"].append(date)

    return results


def report(res: dict, forward: int) -> None:
    if not res:
        return
    print("\n" + "=" * 88)
    print(f"因子体系滚动分层回测（滚动无前视 · 前瞻 {forward} 日 · 分 {N_GROUPS} 组）")
    print("=" * 88)
    print(f"{'组别':<8}{'A 新体系(20因子)':>18}{'B 旧体系(5因子)':>18}{'差异':>12}")
    print("-" * 88)
    labels = ["Q1 最高分", "Q2", "Q3", "Q4", "Q5 最低分"]
    for g in range(N_GROUPS):
        a = _mean(res["A_new"]["groups"][g])
        b = _mean(res["B_legacy"]["groups"][g])
        print(f"{labels[g]:<8}{a * 100:>17.2f}%{b * 100:>17.2f}%{(a - b) * 100:>11.2f}%")

    base = _mean(res["C_equal"]["ret"])
    print("-" * 88)
    a_ls = res["A_new"]["ls"]
    b_ls = res["B_legacy"]["ls"]
    a_m, b_m = _mean(a_ls), _mean(b_ls)
    a_ir = a_m / _std(a_ls) if _std(a_ls) > 0 else 0
    b_ir = b_m / _std(b_ls) if _std(b_ls) > 0 else 0
    print(f"{'全市场等权':<8}{base * 100:>17.2f}%")
    print(f"{'多空Q1-Q5':<8}{a_m * 100:>17.2f}%{b_m * 100:>17.2f}%{(a_m - b_m) * 100:>11.2f}%")
    print(f"{'多空IR':<8}{a_ir:>18.2f}{b_ir:>18.2f}{a_ir - b_ir:>12.2f}")
    print(f"{'多空胜率':<8}{sum(1 for x in a_ls if x > 0) / len(a_ls):>17.0%}"
          f"{sum(1 for x in b_ls if x > 0) / len(b_ls):>18.0%}")
    print("-" * 88)
    print(f"回测期数：{len(a_ls)} 期（每期间隔 {STEP} 交易日）")

    verdict = "✅ 新体系优于旧体系" if a_m > b_m and a_ir > b_ir else \
              "⚠️ 新体系未全面胜出（可能样本期不足或因子需再筛）"
    print(f"结论：{verdict}")
    print("⚠️ 未计交易成本/涨跌停/T+1，仅用于比较两套因子体系的相对优劣。")


if __name__ == "__main__":
    import datetime
    fwd = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else FORWARD
    stp = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else STEP

    if "--ablation" in sys.argv:
        ab = run_ablation(forward=fwd, step=stp)
        report_ablation(ab)
        p = os.path.join(CACHE_DIR, "factor_ablation.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                       "forward": fwd, "subsets": ab}, f, ensure_ascii=False, indent=2)
        print(f"\n[factor_bt] 已写入 {p}")
        sys.exit(0)

    if "--diag" in sys.argv:
        d = run_diag(forward=fwd, step=stp)
        report_diag(d)
        p = os.path.join(CACHE_DIR, "factor_diag.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                       "forward": fwd, "factors": d}, f, ensure_ascii=False, indent=2)
        print(f"\n[factor_bt] 已写入 {p}")
        sys.exit(0)

    r = run(forward=fwd, step=stp)
    report(r, fwd)

    if r:
        out = {
            "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "forward": fwd, "step": stp,
            "periods": len(r["A_new"]["ls"]),
            "A_new": {
                "group_mean": [_mean(g) for g in r["A_new"]["groups"]],
                "long_short": _mean(r["A_new"]["ls"]),
                "ir": _mean(r["A_new"]["ls"]) / _std(r["A_new"]["ls"]) if _std(r["A_new"]["ls"]) else 0,
                "win_rate": sum(1 for x in r["A_new"]["ls"] if x > 0) / max(1, len(r["A_new"]["ls"])),
            },
            "B_legacy": {
                "group_mean": [_mean(g) for g in r["B_legacy"]["groups"]],
                "long_short": _mean(r["B_legacy"]["ls"]),
                "ir": _mean(r["B_legacy"]["ls"]) / _std(r["B_legacy"]["ls"]) if _std(r["B_legacy"]["ls"]) else 0,
                "win_rate": sum(1 for x in r["B_legacy"]["ls"] if x > 0) / max(1, len(r["B_legacy"]["ls"])),
            },
            "C_equal_weight": _mean(r["C_equal"]["ret"]),
            "dates": r["A_new"]["dates"],
        }
        p = os.path.join(CACHE_DIR, "factor_backtest.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n[factor_bt] 已写入 {p}")
