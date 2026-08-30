"""
factor_ic.py -- 因子 IC（Information Coefficient）滚动跟踪

目的：让"静态因子"升级为"动态因子库"——定期回测每个因子的有效性，
      失效因子自动降权、**反向因子自动翻转符号**，对齐幻方量化的
      "因子动态筛选"思路。

原理：
  IC = 因子值(某时点) 与 未来 N 日收益 的 Spearman 秩相关系数。
  - IC 显著 > 0：因子有效（因子值越高 → 未来涨得越好）
  - IC 接近 0：因子失效
  - IC 显著 < 0：因子方向反了 → **翻转使用**（这是有效信息，不是垃圾）

================================================================================
v2 改动（2026-08-30）
================================================================================
1. 因子定义统一收敛到 factor_lib.py。
   旧版在 factor_ic.py 里另写一套 factor_raw_values()，与 multi_factor.py
   的评分逻辑各写各的、已经漂移（trend 定义就不一致）。
   现在两边共用 factor_lib.FACTORS，补因子只改一处。

2. 修复"反向因子降权"的逻辑错误。
   旧版：reversed → 权重 ×0.5。
   问题：方向都反了，还留一半仓位继续做错方向。
   新版：reversed → 符号翻转（100 - score），翻转后按有效因子对待。
   A股短期反转效应显著，"动量反向"恰恰是最强的 alpha 之一。

3. 权重改为「大类内等权 → 大类间按权重」，抑制共线性。
   20 个因子里动量和反转、ATR 和特异波动高度相关，逐因子独立加权
   等于把同一个观点压了两次。

数据源：cache/backtest_klines.json（297 只 × 500 根前复权日K）
  字段顺序：k[0]=date, k[1]=open, k[2]=close, k[3]=high, k[4]=low, k[5]=volume

输出：cache/factor_ic.json
  {
    "updated_at": ..., "version": 2,
    "universe": {...},
    "factors": { <name>: {ic_series, mean_ic, std_ic, ic_ir, ic_win_rate,
                          recent_ic, status, flip, category,
                          base_weight, adj_weight, label}, ... },
    "weights": { <name>: 归一化后的动态权重 },
    "flips":   { <name>: true }   ← 需要翻转使用的因子
  }

与 multi_factor.py 的关系：
  multi_factor.get_weights() 读本文件 weights + flips，实现"因子自己淘汰"闭环。
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
KLINES_PATH = os.path.join(CACHE_DIR, "backtest_klines.json")
OUT_PATH = os.path.join(CACHE_DIR, "factor_ic.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import factor_lib as flib  # noqa: E402

# ---------------------------------------------------------------- 参数（可调）
FORWARD = 5          # 未来收益窗口（交易日），默认 5 日 ≈ 一周
STEP = 20            # 截面滚动步长（交易日），20 ≈ 每月
MIN_STOCKS = 15      # 单个截面最少有效股票数，低于此则跳过该截面

# 判定阈值（从 factor_lib 继承，此处仅作缺省）
IC_THRESHOLD = flib.IC_THRESHOLD
IC_IR_SIGNIFICANT = flib.IC_IR_SIGNIFICANT
WEAK_PERIODS = 4     # 最近连续 N 期都弱 → 降权


# ---------------------------------------------------------------- Spearman 秩相关（零依赖）
def _rank(values: list[float]) -> list[float]:
    """平均秩（处理并列值）。返回 1-based 秩列表。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    """Spearman 秩相关系数（Pearson on ranks）。样本 < 3 或常数列返回 0。"""
    n = len(x)
    if n < 3 or len(y) != n:
        return 0.0
    rx = _rank(x)
    ry = _rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n))
    vy = sum((ry[i] - my) ** 2 for i in range(n))
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


# ---------------------------------------------------------------- 数据
def _load_klines() -> dict[str, list]:
    """读 backtest_klines.json，返回 {code: kline}。"""
    if not os.path.exists(KLINES_PATH):
        print(f"[factor_ic] 找不到 {KLINES_PATH}，请先运行 fetch_backtest_klines.py")
        return {}
    with open(KLINES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, list] = {}
    for code, stock in data.get("stocks", {}).items():
        kl = stock.get("kline", [])
        if kl:
            out[code] = kl
    return out


# ---------------------------------------------------------------- IC 滚动计算
def compute_ic_series(codes_klines: dict[str, list],
                      names: list[str] | None = None) -> dict[str, list]:
    """
    对每个因子计算 IC 序列。
    返回 {factor_name: [ic或None, ...]}，序列长度 = 截面数（旧→新）。
    """
    if not codes_klines:
        return {}
    factor_names = names or flib.FACTOR_NAMES
    codes = list(codes_klines.keys())
    max_len = max(len(kl) for kl in codes_klines.values())
    min_bars = max(flib.FACTORS[n]["min_bars"] for n in factor_names)
    start = max(min_bars, flib.MAX_LOOKBACK // 2)
    # 截面索引：从 start 起每隔 STEP 取一个，保证 t+FORWARD 不越界
    t_indices = list(range(start, max_len - FORWARD, STEP))
    if not t_indices:
        return {}

    # 市场等权收益（beta / 特异波动 的基准），全样本构造一次
    mkt_ctx = flib.build_market_ctx(codes_klines)

    ic_series: dict[str, list] = {f: [] for f in factor_names}
    valid_counts: list[int] = []

    for t in t_indices:
        section: dict[str, dict[str, float]] = {f: {} for f in factor_names}
        fwd_rets: list[float] = []
        valid_codes: list[str] = []

        for code in codes:
            kl = codes_klines[code]
            if len(kl) < t + FORWARD + 1:
                continue  # 未来数据不足
            close_t = float(kl[t][2])
            close_fwd = float(kl[t + FORWARD][2])
            if close_t <= 0:
                continue

            end = t + 1
            window = kl[max(0, end - flib.MAX_LOOKBACK): end]
            ctx = flib.slice_market_ctx(mkt_ctx, [str(k[0]) for k in window])
            raw = flib.compute_raw(window, ctx, names=factor_names, code=code)

            # 至少要有 60% 的因子算得出来，否则这只股票不进截面
            got = [v for v in raw.values() if v is not None]
            if len(got) < len(factor_names) * 0.6:
                continue

            valid_codes.append(code)
            fwd_rets.append(close_fwd / close_t - 1)
            for f in factor_names:
                # 用中位数填充缺失值，保持截面宽度（秩相关对单点不敏感）
                section[f][code] = raw.get(f)

        valid_counts.append(len(valid_codes))
        if len(valid_codes) < MIN_STOCKS:
            for f in factor_names:
                ic_series[f].append(None)
            continue

        # 缺失值用该截面中位数填补
        for f in factor_names:
            vals = [section[f][c] for c in valid_codes]
            present = [v for v in vals if v is not None]
            if len(present) < MIN_STOCKS:
                ic_series[f].append(None)
                continue
            med = sorted(present)[len(present) // 2]
            x = [v if v is not None else med for v in vals]
            ic_series[f].append(round(spearman(x, fwd_rets), 4))

    compute_ic_series.last_valid_counts = valid_counts  # 供报告展示
    return ic_series


def _safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _safe_std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _safe_mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def build_report(ic_series: dict[str, list]) -> dict:
    """把 IC 序列汇总成统计 + 权重调整 + 翻转标记。"""
    base_w_all = flib.base_weights()
    factors: dict[str, dict] = {}

    for name, series in ic_series.items():
        spec = flib.FACTORS.get(name, {})
        base_w = base_w_all.get(name, 0.05)
        valid = [v for v in series if v is not None]
        n_valid = len(valid)

        if n_valid == 0:
            factors[name] = {
                "ic_series": series, "mean_ic": None, "std_ic": None,
                "ic_ir": None, "ic_win_rate": None, "recent_ic": None,
                "status": "insufficient", "flip": False,
                "category": spec.get("category", ""),
                "base_weight": base_w, "adj_weight": base_w,
                "n_periods": 0, "label": spec.get("label", ""),
            }
            continue

        mean_ic = round(_safe_mean(valid), 4)
        std_ic = round(_safe_std(valid), 4)
        ic_ir = round(mean_ic / std_ic, 3) if std_ic > 0 else 0.0
        win_rate = round(sum(1 for v in valid if v > 0) / n_valid, 4)
        recent = valid[-WEAK_PERIODS:]
        recent_ic = round(_safe_mean(recent), 4)

        # ---- 状态判定（四档）----
        #   reversed : IC 显著为负（|IC_IR|>=0.2）→ 翻转符号使用，不降权
        #              A股短期反转效应显著，"动量反向"恰恰是有效 alpha
        #   negative : IC 为负但不显著 → 方向存疑（可能是噪声），降权不翻转
        #   weak     : |IC| 接近 0 或最近连续 N 期都弱 → 降权
        #   effective: IC 为正 → 正常权重
        recent_weak = (len(recent) >= 2
                       and all(abs(v) < IC_THRESHOLD for v in recent))
        long_weak = abs(mean_ic) < IC_THRESHOLD
        significant = abs(ic_ir) >= IC_IR_SIGNIFICANT
        # 倒U型因子（如"量比越接近2.0越好"）非单调，秩相关无法表达其真实形态，
        # 翻转后语义会变成"越极端越好"，属于误读 → 只降权不翻转
        monotonic = spec.get("monotonic", True)

        if mean_ic < -IC_THRESHOLD and significant and monotonic:
            status, flip = "reversed", True
        elif mean_ic < -IC_THRESHOLD:
            status, flip = "negative", False
        elif long_weak or recent_weak:
            status, flip = "weak", False
        else:
            status, flip = "effective", False

        factors[name] = {
            "ic_series": series,
            "mean_ic": mean_ic, "std_ic": std_ic, "ic_ir": ic_ir,
            "ic_win_rate": win_rate, "recent_ic": recent_ic,
            "status": status, "flip": flip,
            "category": spec.get("category", ""),
            "base_weight": base_w, "adj_weight": base_w,
            "n_periods": n_valid, "label": spec.get("label", ""),
        }

    # ---- 双重检验：IC 状态 + 分层回测证据，合成最终处置 ----
    # 只有 IC 与分层回测方向一致时，才信任该因子的方向并给足权重。
    bt = flib.load_backtest_evidence(CACHE_DIR)
    ic_stats = {
        name: {
            "mean_ic": f.get("mean_ic"),
            "ic_ir": f.get("ic_ir") or 0.0,
            "status": f.get("status", "insufficient"),
            "n_periods": f.get("n_periods", 0),
        }
        for name, f in factors.items()
    }
    verdict = flib.combine_evidence(ic_stats, bt)
    weights = flib.apply_evidence(base_w_all, verdict)
    flips = {k: True for k, v in verdict.items() if v.get("flip")}

    # 同步回写每个因子的最终权重与处置理由（供报告展示）
    for name in factors:
        v = verdict.get(name, {})
        factors[name]["adj_weight"] = weights.get(name, factors[name]["base_weight"])
        factors[name]["status"] = v.get("status", factors[name]["status"])
        factors[name]["flip"] = bool(v.get("flip"))
        factors[name]["reason"] = v.get("reason", "")
        factors[name]["bt_long_short"] = (bt.get(name) or {}).get("long_short")
        factors[name]["bt_ir"] = (bt.get(name) or {}).get("ir")

    return {"factors": factors, "weights": weights, "flips": flips}


def run(forward: int = FORWARD, step: int = STEP) -> dict:
    """完整跑一遍：加载 K 线 → 算 IC → 汇总 → 写缓存。"""
    global FORWARD, STEP
    FORWARD, STEP = forward, step

    codes_klines = _load_klines()
    if not codes_klines:
        return {}

    max_len = max(len(kl) for kl in codes_klines.values())
    ic_series = compute_ic_series(codes_klines)
    report = build_report(ic_series)

    counts = getattr(compute_ic_series, "last_valid_counts", [])
    out = {
        "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "version": 2,
        "universe": {
            "stocks": len(codes_klines),
            "max_days": max_len,
            "periods": len(next(iter(ic_series.values()), [])),
            "forward": FORWARD, "step": STEP,
            "min_stocks": MIN_STOCKS,
            "ic_threshold": IC_THRESHOLD,
            "avg_section_stocks": round(sum(counts) / len(counts), 1) if counts else 0,
        },
        **report,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[factor_ic] 已写入 {OUT_PATH}")
    return out


def print_report(out: dict) -> None:
    """人类可读的 IC 报告。"""
    uni = out.get("universe", {})
    print("\n" + "=" * 100)
    print(f"因子 IC 滚动跟踪报告 v2  （{uni.get('stocks', 0)} 只 × 最长 {uni.get('max_days', 0)} 日"
          f" · {uni.get('periods', 0)} 期 · 前瞻 {uni.get('forward', 0)} 日"
          f" · 截面均 {uni.get('avg_section_stocks', 0)} 只）")
    print("=" * 100)
    print(f"{'因子':<13}{'大类':<10}{'mean_IC':>9}{'IC_IR':>8}{'胜率':>7}"
          f"{'近4期':>9}{'状态':<11}{'翻转':>6}{'基础':>7}{'动态权重':>9}")
    print("-" * 100)

    status_cn = {"effective": "✅ 有效", "weak": "⚠️ 降权",
                 "reversed": "🔄 反向→翻转", "insufficient": "— 样本不足",
                 "negative": "⚠️ 负向不显著", "validated": "⭐ 双验证",
                 "contradict": "❗证据矛盾", "harmful": "☠️ 分层亏钱"}
    rows = sorted(out.get("factors", {}).items(),
                  key=lambda kv: -(abs(kv[1].get("ic_ir") or 0)))
    for name, f in rows:
        mean_ic = f.get("mean_ic")
        mean_s = f"{mean_ic:+.4f}" if mean_ic is not None else "   —"
        ir_s = f"{f.get('ic_ir', 0):+.2f}" if f.get("ic_ir") is not None else " —"
        wr = f.get("ic_win_rate")
        wr_s = f"{wr:.0%}" if wr is not None else " —"
        rc = f.get("recent_ic")
        rc_s = f"{rc:+.4f}" if rc is not None else "   —"
        st = status_cn.get(f.get("status"), f.get("status"))
        flip_s = "是" if f.get("flip") else ""
        print(f"{name:<13}{f.get('category',''):<10}{mean_s:>9}{ir_s:>8}{wr_s:>7}"
              f"{rc_s:>9}{st:<13}{flip_s:>5}"
              f"{f.get('base_weight', 0):>7.4f}{f.get('adj_weight', 0):>9.4f}")
    print("-" * 100)
    print("权重合计:", round(sum(out.get("weights", {}).values()), 4),
          "  需翻转因子:", ", ".join(out.get("flips", {})) or "无")
    print("规则：IC 与分层回测方向一致才信任 —— 双正向加码 ×1.25，双负向翻转使用，"
          "矛盾 ×0.35，分层亏钱 ×0.3；|IC| < %.2f 或近 %d 期连续弱 → ×0.6"
          % (IC_THRESHOLD, WEAK_PERIODS))
    print("注：权重列 = 基础权重 × 上述系数后归一化。分层证据来自 factor_diag.json"
          "（python3 factor_backtest.py --diag）")


if __name__ == "__main__":
    args = sys.argv[1:]
    fwd, step = FORWARD, STEP
    if args:
        try:
            fwd = int(args[0])
        except ValueError:
            pass
    if len(args) > 1:
        try:
            step = int(args[1])
        except ValueError:
            pass
    result = run(forward=fwd, step=step)
    if result:
        print_report(result)
    else:
        print("[factor_ic] 未生成报告（K 线数据缺失）")
