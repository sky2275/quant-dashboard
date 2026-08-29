"""
factor_ic.py -- 因子 IC（Information Coefficient）滚动跟踪

目的：让"静态因子"升级为"动态因子库"——定期回测每个因子的有效性，
      失效因子自动降权，对齐幻方量化的"因子动态筛选"思路。

原理：
  IC = 因子值(某时点) 与 未来 N 日收益 的 Spearman 秩相关系数。
  - IC 显著 > 0：因子有效（因子值越高 → 未来涨得越好）
  - IC 接近 0 或 < 0：因子失效/反向
  通过滚动多个历史截面得到 IC 序列，再统计 mean_ic / IC_IR / 胜率，
  对长期失效的因子自动降权。

数据源：cache/backtest_klines.json（43 只股票 × 501 根前复权日K）
  字段顺序：k[0]=date, k[1]=open, k[2]=close, k[3]=high, k[4]=low, k[5]=volume

输出：cache/factor_ic.json
  {
    "updated_at": ...,
    "universe": {stocks, days, periods, forward},
    "factors": { <name>: {ic_series, mean_ic, std_ic, ic_ir, ic_win_rate,
                          recent_ic, status, base_weight, adj_weight}, ... },
    "weights": { <name>: <归一化后的动态权重> }
  }

与 multi_factor.py 的关系：
  multi_factor.score_stock() 的 get_weights() 优先读本文件 weights 字段，
  实现"因子自己淘汰"闭环。本文件独立运行，不依赖 multi_factor。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
KLINES_PATH = os.path.join(CACHE_DIR, "backtest_klines.json")
OUT_PATH = os.path.join(CACHE_DIR, "factor_ic.json")

# ---------------------------------------------------------------- 参数（可调）
FORWARD = 5          # 未来收益窗口（交易日），默认 5 日 ≈ 一周
STEP = 20            # 截面滚动步长（交易日），20 ≈ 每月
MIN_HISTORY = 60     # 因子计算所需最少历史 K 线（趋势因子需 MA60）
MIN_STOCKS = 15      # 单个截面最少有效股票数，低于此则跳过该截面
IC_THRESHOLD = 0.02  # IC 绝对值低于此视为"弱"
WEAK_PERIODS = 4     # 最近连续 N 期都弱 → 降权
HALF_FACTOR = 0.5    # 降权系数

# 基础权重（与 multi_factor.FACTOR_WEIGHTS 保持一致）
BASE_WEIGHTS = {
    "momentum": 0.25,
    "vol_price": 0.15,
    "trend": 0.25,
    "volatility": 0.15,
    "rsi": 0.20,
}

# 因子原始值方向说明：全部对齐 multi_factor 评分方向（值越高 → 评分越高）
FACTOR_LABELS = {
    "momentum": "20日涨幅(%)",
    "vol_price": "-|量比-2.0|（越接近理想放量中心越高）",
    "trend": "(收盘-MA20)/MA20(%)",
    "volatility": "-ATR占比(%)（低波动越高）",
    "rsi": "-|RSI-50|（越接近中性越高）",
}


# ---------------------------------------------------------------- 指标（零外部依赖）
def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _atr(klines: list, period: int = 14) -> float | None:
    """Average True Range。klines 字段 [2]=close, [3]=high, [4]=low。"""
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i][3])
        low = float(klines[i][4])
        prev_close = float(klines[i - 1][2])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else None


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI。closes 为收盘价序列（旧→新）。"""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def factor_raw_values(klines: list) -> dict[str, float]:
    """
    对 K 线切片（截至某时点，旧→新）计算 5 因子原始值。
    方向全部对齐 multi_factor 评分方向（值越高 → 评分越高），
    因此 IC 为正即"因子有效"，IC 为负/接近 0 即"失效/反向"。
    """
    if not klines or len(klines) < MIN_HISTORY:
        return {}
    closes = [float(k[2]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    last_close = closes[-1]
    vals: dict[str, float] = {}

    # momentum：20 日涨幅（越高越好）
    if len(closes) >= 21:
        vals["momentum"] = (closes[-1] / closes[-21] - 1) * 100

    # vol_price：量比偏离理想中心 2.0 的负距离（越接近 2.0 越高）
    if len(volumes) >= 25:
        recent_vol = sum(volumes[-5:]) / 5
        base_vol = sum(volumes[-25:-5]) / 20
        vr = recent_vol / base_vol if base_vol > 0 else 1.0
        vals["vol_price"] = -abs(vr - 2.0)

    # trend：(收盘 - MA20) / MA20（价格在 MA20 上方为正）
    ma20 = _sma(closes, 20)
    if ma20 and ma20 > 0:
        vals["trend"] = (last_close - ma20) / ma20 * 100

    # volatility：-ATR 占比（低波动越高）
    atr = _atr(klines, 14)
    if atr and last_close > 0:
        vals["volatility"] = -(atr / last_close * 100)

    # rsi：-|RSI-50|（越接近中性 50 越高）
    rsi = _rsi(closes, 14)
    if rsi is not None:
        vals["rsi"] = -abs(rsi - 50)

    return vals


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


# ---------------------------------------------------------------- IC 滚动计算
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


def compute_ic_series(codes_klines: dict[str, list]) -> dict[str, list]:
    """
    对每个因子计算 IC 序列。
    返回 {factor_name: [ic或None, ...]}，序列长度 = 截面数（按时间旧→新）。
    """
    if not codes_klines:
        return {}
    codes = list(codes_klines.keys())
    max_len = max(len(kl) for kl in codes_klines.values())
    # 截面索引：从 MIN_HISTORY 起，每隔 STEP 取一个，保证 t+FORWARD 不越界
    t_indices = list(range(MIN_HISTORY, max_len - FORWARD, STEP))
    if not t_indices:
        return {}

    factor_names = list(BASE_WEIGHTS.keys())
    ic_series: dict[str, list] = {f: [] for f in factor_names}

    for t in t_indices:
        # 收集该截面下所有股票的因子值 + 未来收益
        section: dict[str, dict[str, float]] = {f: {} for f in factor_names}
        fwd_rets: list[float] = []
        valid_codes = []
        for code in codes:
            kl = codes_klines[code]
            if len(kl) < t + FORWARD + 1:
                continue  # 未来数据不足
            raw = factor_raw_values(kl[: t + 1])
            if not raw:
                continue
            close_t = float(kl[t][2])
            close_fwd = float(kl[t + FORWARD][2])
            if close_t <= 0:
                continue
            valid_codes.append(code)
            fwd_rets.append(close_fwd / close_t - 1)
            for f in factor_names:
                section[f][code] = raw.get(f, 0.0)

        if len(valid_codes) < MIN_STOCKS:
            # 有效股票不足，该截面全部记 None（表示无样本）
            for f in factor_names:
                ic_series[f].append(None)
            continue

        for f in factor_names:
            x = [section[f][c] for c in valid_codes]
            y = fwd_rets
            ic_series[f].append(round(spearman(x, y), 4))

    return ic_series


def _safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _safe_std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _safe_mean(vals)
    var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return var ** 0.5


def build_report(ic_series: dict[str, list]) -> dict:
    """把 IC 序列汇总成统计 + 权重调整，输出 factor_ic.json 的完整结构。"""
    factors: dict[str, Any] = {}
    for name, series in ic_series.items():
        base_w = BASE_WEIGHTS.get(name, 0.2)
        valid = [v for v in series if v is not None]
        n_valid = len(valid)
        if n_valid == 0:
            factors[name] = {
                "ic_series": series,
                "mean_ic": None, "std_ic": None, "ic_ir": None,
                "ic_win_rate": None, "recent_ic": None,
                "status": "insufficient", "base_weight": base_w,
                "adj_weight": base_w, "n_periods": 0,
                "label": FACTOR_LABELS.get(name, ""),
            }
            continue

        mean_ic = round(_safe_mean(valid), 4)
        std_ic = round(_safe_std(valid), 4)
        ic_ir = round(mean_ic / std_ic, 3) if std_ic > 0 else 0.0
        win_rate = round(sum(1 for v in valid if v > 0) / n_valid, 4)
        recent = valid[-WEAK_PERIODS:]
        recent_ic = round(_safe_mean(recent), 4)

        # 失效判定（三类）：
        #   reversed  —— IC 显著为负，因子方向反了（最该降权）
        #   weak      —— 长期 IC 弱（|IC| < 阈值）或最近连续 N 期都弱
        #   effective —— 有效
        recent_weak = (len(recent) >= 2 and
                       all(abs(v) < IC_THRESHOLD for v in recent))
        long_weak = abs(mean_ic) < IC_THRESHOLD
        if mean_ic < 0:
            status = "reversed"
            adj_w = round(base_w * HALF_FACTOR, 4)
        elif long_weak or recent_weak:
            status = "weak"
            adj_w = round(base_w * HALF_FACTOR, 4)
        else:
            status = "effective"
            adj_w = base_w

        factors[name] = {
            "ic_series": series,
            "mean_ic": mean_ic, "std_ic": std_ic, "ic_ir": ic_ir,
            "ic_win_rate": win_rate, "recent_ic": recent_ic,
            "status": status, "base_weight": base_w,
            "adj_weight": adj_w, "n_periods": n_valid,
            "label": FACTOR_LABELS.get(name, ""),
        }

    # 归一化权重（总和 = 1）
    total = sum(factors[f]["adj_weight"] for f in factors)
    weights: dict[str, float] = {}
    if total > 0:
        for f in factors:
            weights[f] = round(factors[f]["adj_weight"] / total, 4)
            factors[f]["adj_weight"] = weights[f]

    return {"factors": factors, "weights": weights}


def run(forward: int = FORWARD, step: int = STEP) -> dict:
    """完整跑一遍：加载 K 线 → 算 IC → 汇总 → 写缓存 → 返回报告。"""
    global FORWARD, STEP
    FORWARD, STEP = forward, step

    codes_klines = _load_klines()
    if not codes_klines:
        return {}

    max_len = max(len(kl) for kl in codes_klines.values())
    ic_series = compute_ic_series(codes_klines)
    report = build_report(ic_series)

    out = {
        "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "universe": {
            "stocks": len(codes_klines),
            "max_days": max_len,
            "periods": len(next(iter(ic_series.values()), [])),
            "forward": FORWARD,
            "step": STEP,
            "min_stocks": MIN_STOCKS,
            "ic_threshold": IC_THRESHOLD,
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
    print("\n" + "=" * 78)
    print(f"因子 IC 滚动跟踪报告  （{uni.get('stocks', 0)} 只 × 最长 {uni.get('max_days', 0)} 日"
          f" · 截面 {uni.get('periods', 0)} 期 · 前瞻 {uni.get('forward', 0)} 日）")
    print("=" * 78)
    print(f"{'因子':<12} {'mean_IC':>8} {'IC_IR':>7} {'胜率':>7} {'近4期':>7} {'状态':<10} {'基础权重':>8} {'动态权重':>8}")
    print("-" * 78)
    status_cn = {"effective": "✅ 有效", "weak": "⚠️ 降权", "reversed": "🔴 反向降权", "insufficient": "— 样本不足"}
    for name, f in out.get("factors", {}).items():
        mean_ic = f.get("mean_ic")
        mean_s = f"{mean_ic:+.4f}" if mean_ic is not None else "  —"
        ir_s = f"{f.get('ic_ir', 0):.2f}" if f.get("ic_ir") is not None else "—"
        wr = f.get("ic_win_rate")
        wr_s = f"{wr:.0%}" if wr is not None else "—"
        rc = f.get("recent_ic")
        rc_s = f"{rc:+.4f}" if rc is not None else "—"
        st = status_cn.get(f.get("status"), f.get("status"))
        print(f"{name:<12} {mean_s:>8} {ir_s:>7} {wr_s:>7} {rc_s:>7} {st:<12} "
              f"{f.get('base_weight', 0):>7.2f} {f.get('adj_weight', 0):>8.4f}")
    print("-" * 78)
    print("权重合计:", round(sum(out.get("weights", {}).values()), 4))
    print("\n规则：IC 为负（方向反了）/ 长期 |IC| < %.2f / 近 %d 期连续弱 → 权重 ×%.1f 降权" %
          (IC_THRESHOLD, WEAK_PERIODS, HALF_FACTOR))


if __name__ == "__main__":
    args = sys.argv[1:]
    fwd = FORWARD
    step = STEP
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
