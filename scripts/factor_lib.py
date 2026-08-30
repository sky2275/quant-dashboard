"""
factor_lib.py -- 可扩展因子库（量化工作台「决策引擎」的因子底座）

================================================================================
为什么要这个文件
================================================================================
改造前，因子逻辑分散在两处且各写一遍：
  · multi_factor.py  score_stock()      —— 分档 if/else 打出 0-100 分（用于选股）
  · factor_ic.py     factor_raw_values() —— 另写一套原始值（用于算 IC）
两套实现已经不同步（multi_factor 的 trend 是「MA20位置+MA60斜率」的三段加分，
factor_ic 的 trend 只是 (close-MA20)/MA20）。补一个因子要改两处，极易漏改。

改造后：**一个因子只写一处**。
  每个因子 = 一个 raw 函数（K线 → 原始值），方向统一约定「值越大 → 越看好」。
  · 评分：raw → 线性映射到 0-100（单调，不破坏 IC）
  · IC  ：直接用 raw
两边共用同一份 raw，天然同步。补因子 = 往 FACTORS 里加一条字典。

================================================================================
补一个因子的三步（唯一需要动的文件）
================================================================================
  1. 写 raw 函数：def f_xxx(v: KLineView, ctx: dict) -> float | None
       方向必须统一：返回值越大 = 越看多。想做「越低越好」就取负号。
       数据不足 / 无法计算 → 返回 None（框架会跳过，不污染统计）。
  2. 在 FACTORS 里登记：
        "xxx": {"label": "中文名(方向说明)", "category": "大类",
                "raw": f_xxx, "lo": -10.0, "hi": 10.0, "min_bars": 60}
       lo/hi 是 raw → 0-100 的映射区间（经验分位）。
       不确定就先填宽一点，跑 `python3 factor_lib.py` 看分布再回填。
  3. 跑 `python3 factor_ic.py` 重算 IC —— 新因子自动进入评分与权重体系，
     无需改 multi_factor.py / factor_ic.py 任何一行。

================================================================================
类别权重（抗共线性）
================================================================================
16 个因子里动量和反转、ATR 和特异波动高度相关。若每个因子独立加权，
相关因子会被重复计权（等于把同一个观点压了两次）。
因此采用「大类内等权 → 大类间按权重分配」：
    因子权重 = 大类权重 / 类内因子数 × IC调整系数 → 全局归一化
这是多因子实战里的标准降共线性做法。

数据：cache/backtest_klines.json，K线字段 [0]=date [1]=open [2]=close
      [3]=high [4]=low [5]=volume
"""
from __future__ import annotations

import bisect
import json
import math
import os
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

# 单因子计算最多回溯多少根K线（最长因子是 250 日高点，留到 260）
MAX_LOOKBACK = 260

# ----------------------------------------------------------------- 大类权重
# 按「因子大类」分配权重，而不是按单个因子。总和 = 1.0
CATEGORY_WEIGHTS = {
    "动量反转": 0.22,
    "波动风险": 0.22,
    "量能量价": 0.17,
    "技术形态": 0.15,
    "统计特征": 0.06,
    "资金流向": 0.10,
    "基本面": 0.08,
}

# IC 状态 → 权重调整系数
# 注意：reversed 不再像旧版那样 ×0.5 降权。反向因子的正确用法是「翻转符号」，
# 翻转后它是有效因子（A股短期反转效应显著），降权只会让它半仓继续做错方向。
STATUS_MULTIPLIER = {
    "effective": 1.0,      # IC 显著为正
    "reversed": 1.0,       # IC 显著为负 → 翻转符号后使用，按有效因子对待
    "weak": 0.6,           # IC 长期接近 0，该因子的信息已衰减
    "negative": 0.6,       # IC 为负但不显著：方向存疑，降权观察，不盲翻
    "insufficient": 0.5,   # 样本不足，先给中性偏低权重
    # 为什么是"接近剔除"而不是"降权"：消融实验（factor_backtest.py --ablation）证明
    # 20 个因子全用 → 多空 +0.08%（IR 0.03，等于没有选股能力）；
    # 只留通过双重检验的 9 个 → 多空 +1.67%（IR 0.51，胜率 68%）。
    # 无效因子不是"贡献小"，而是稀释信号。因此这里给到接近 0 的权重而非温和降权。
    "contradict": 0.10,    # IC 与分层回测方向矛盾 → 证据不足，近乎剔除
    "harmful": 0.05,       # 分层回测显著亏钱 → 近乎剔除
    "validated": 1.25,     # IC 与分层回测双正向 → 奖励权重
}

# ----------------------------------------------------------------- 双重检验
# 只看 IC 会误判：IC 是秩相关，被尾部极值主导；分层回测看的是极端分组的实际
# 收益。两者会给出相反结论——例如 vol_atr 的 IC 判为"有效"，但分层回测显示
# 按它做多头部、做空尾部要亏 1.21%。
# 因此采用双重证据：只有两个检验方向一致，才信任该因子的方向。
BT_IR_SIGNIFICANT = 0.25   # 分层回测多空 IR 的显著阈值
BT_LS_SIGNIFICANT = 0.003  # 分层回测多空收益阈值（0.3% / 5日）

# ----------------------------------------------------------------- 置信度收缩
# 光看"方向对不对"不够，还要看"这个方向有多可信"。
# IC_IR = mean(IC)/std(IC)，本质是 IC 的 t 值除以 sqrt(期数)。
# 期数 19 时，IC_IR=0.2 对应 t≈0.9（噪声），IC_IR=0.5 对应 t≈2.2（可信）。
# 若只按状态给权重，一个 IC_IR=0.25 的"反向因子"会和 IC_IR=0.51 的强因子
# 拿到同样权重 —— 等于把噪声和信号一视同仁。
# 因此再乘一个置信度收缩系数：IR 越接近 0，权重压得越狠。
IR_FULL_CONFIDENCE = 0.4   # IC_IR 达到此值视为完全可信（收缩系数 = 1.0）
IR_FLOOR = 0.4             # IC_IR = 0 时保留的收缩下限


def _confidence_shrink(ic_ir: float) -> float:
    """IC_IR → 置信度收缩系数，落在 [IR_FLOOR, 1.0]。"""
    if not ic_ir:
        return IR_FLOOR
    strength = min(1.0, abs(ic_ir) / IR_FULL_CONFIDENCE)
    return IR_FLOOR + (1.0 - IR_FLOOR) * strength


def load_backtest_evidence(cache_dir: str | None = None) -> dict:
    """读 factor_diag.json（由 factor_backtest.py --diag 生成）的分层回测证据。
    文件不存在时返回空 dict —— 此时退化为纯 IC 判定，不影响主流程。"""
    path = os.path.join(cache_dir or CACHE_DIR, "factor_diag.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("factors", {}) or {}
    except Exception:
        return {}


def combine_evidence(
    ic_stats: dict[str, dict],
    bt: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """
    结合「IC 检验」与「分层回测」双重证据，给出每个因子的最终处置。

    ic_stats: {name: {"mean_ic":.., "ic_ir":.., "status":.., "n_periods":..}}
    bt      : {name: {"long_short":.., "ir":.., "win_rate":..}}

    返回: {name: {"status":.., "flip":bool, "mult":float, "reason":str}}

    决策表（ic_dir / bt_dir 取值 -1 / 0 / +1）：
      IC负 & BT负 → 方向确实反了 → 翻转使用
      IC正 & BT正 → 双验证有效   → 奖励权重
      两者矛盾     → 证据不足     → 重罚
      BT负但IC不显著 → 有害因子   → 重罚（不翻转：可能是噪声方向）
      其余         → 沿用 IC 判定
    """
    bt = bt or {}
    out: dict[str, dict] = {}
    for name, s in ic_stats.items():
        status = s.get("status", "insufficient")
        monotonic = FACTORS.get(name, {}).get("monotonic", True)
        mean_ic = s.get("mean_ic")
        ic_ir = s.get("ic_ir") or 0.0
        b = bt.get(name) or {}
        bt_ls = b.get("long_short")
        bt_ir = b.get("ir") or 0.0

        # IC 方向：-1 显著为负 / +1 显著为正 / 0 不显著
        if mean_ic is None:
            ic_dir = 0
        elif mean_ic < -IC_THRESHOLD and abs(ic_ir) >= IC_IR_SIGNIFICANT:
            ic_dir = -1
        elif mean_ic > IC_THRESHOLD:
            ic_dir = 1
        else:
            ic_dir = 0

        # 分层方向：-1 显著亏钱 / +1 显著赚钱 / 0 不显著
        if bt_ls is None:
            bt_dir = 0
        elif bt_ls < -BT_LS_SIGNIFICANT and abs(bt_ir) >= BT_IR_SIGNIFICANT:
            bt_dir = -1
        elif bt_ls > BT_LS_SIGNIFICANT and bt_ir >= BT_IR_SIGNIFICANT:
            bt_dir = 1
        elif bt_ls < -BT_LS_SIGNIFICANT:
            bt_dir = -1   # 亏钱且幅度够大，即便 IR 不显著也要处理
        else:
            bt_dir = 0

        shrink = _confidence_shrink(ic_ir)

        if ic_dir == -1 and bt_dir == -1 and monotonic:
            out[name] = {"status": "reversed", "flip": True,
                         "mult": round(STATUS_MULTIPLIER["reversed"] * shrink, 4),
                         "reason": f"IC({mean_ic:+.3f}) 与分层({bt_ls * 100:+.2f}%) 同为负 → 方向反了，翻转"}
        elif ic_dir == 1 and bt_dir == 1:
            out[name] = {"status": "validated", "flip": False,
                         "mult": round(STATUS_MULTIPLIER["validated"] * shrink, 4),
                         "reason": f"IC({mean_ic:+.3f}) 与分层({bt_ls * 100:+.2f}%) 双正向 → 加码"}
        elif ic_dir == -1 and bt_dir == 1:
            out[name] = {"status": "contradict", "flip": False,
                         "mult": STATUS_MULTIPLIER["contradict"],
                         "reason": f"IC 为负但分层为正({bt_ls * 100:+.2f}%) → 证据矛盾，重罚"}
        elif ic_dir == 1 and bt_dir == -1:
            out[name] = {"status": "contradict", "flip": False,
                         "mult": STATUS_MULTIPLIER["contradict"],
                         "reason": f"IC 为正但分层为负({bt_ls * 100:+.2f}%) → 证据矛盾，重罚"}
        elif bt_dir == -1:
            out[name] = {"status": "harmful", "flip": False,
                         "mult": STATUS_MULTIPLIER["harmful"],
                         "reason": f"分层回测显著亏钱({bt_ls * 100:+.2f}%) → 当前样本上有害"}
        else:
            # 分层证据不显著时沿用 IC 判定。注意 status="reversed" 本身就意味着
            # 要翻转——状态与翻转标记必须一致，否则会出现"标记反向却不翻转"的矛盾。
            flip = (status == "reversed") and monotonic
            out[name] = {"status": status, "flip": flip,
                         "mult": round(STATUS_MULTIPLIER.get(status, 0.5) * shrink, 4),
                         "reason": f"沿用 IC 判定：{status}"
                                   + ("（分层未证伪）" if flip else "")
                                   + f"｜置信收缩 ×{shrink:.2f}"}
    return out


def apply_evidence(base_w: dict[str, float],
                   verdict: dict[str, dict]) -> dict[str, float]:
    """把处置结果（含翻转标记）应用到基础权重上并归一化。"""
    adj = {k: w * verdict.get(k, {}).get("mult", 0.5) for k, w in base_w.items()}
    total = sum(adj.values())
    if total <= 0:
        n = max(1, len(adj))
        return {k: 1.0 / n for k in adj}
    return {k: round(v / total, 4) for k, v in adj.items()}

# IC 判定阈值
IC_THRESHOLD = 0.02     # |IC| 低于此视为弱
IC_IR_SIGNIFICANT = 0.2  # |IC_IR| 高于此才认为"显著"（否则可能是噪声）


# ===========================================================================
# KLineView：惰性视图，避免每个因子重复拆数组
# ===========================================================================
class KLineView:
    """K线切片视图（旧→新，末尾为当前时点）。数组惰性构建，算一次缓存。"""

    __slots__ = ("_kl", "closes", "volumes", "highs", "lows", "_rets", "_dates")

    def __init__(self, kl: list):
        self._kl = kl
        self.closes: list[float] | None = None
        self.volumes: list[float] | None = None
        self.highs: list[float] | None = None
        self.lows: list[float] | None = None
        self._rets: list[float] | None = None
        self._dates: list[str] | None = None

    @property
    def n(self) -> int:
        return len(self._kl)

    def _build(self) -> None:
        if self.closes is not None:
            return
        kl = self._kl
        self.closes = [float(k[2]) for k in kl]
        self.volumes = [float(k[5]) for k in kl]
        self.highs = [float(k[3]) for k in kl]
        self.lows = [float(k[4]) for k in kl]

    @property
    def rets(self) -> list[float]:
        """日收益率序列（长度 = n-1）。"""
        if self._rets is None:
            self._build()
            c = self.closes
            self._rets = [
                (c[i] / c[i - 1] - 1.0) if c[i - 1] > 0 else 0.0
                for i in range(1, len(c))
            ]
        return self._rets

    @property
    def dates(self) -> list[str]:
        if self._dates is None:
            self._dates = [str(k[0]) for k in self._kl]
        return self._dates


# ===========================================================================
# 基础指标（零依赖）
# ===========================================================================
def _sma(vals: list[float], period: int) -> float | None:
    if len(vals) < period:
        return None
    return sum(vals[-period:]) / period


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def _atr(v: KLineView, period: int = 14) -> float | None:
    v._build()
    if v.n < period + 1:
        return None
    trs = []
    for i in range(1, v.n):
        hi, lo, pc = v.highs[i], v.lows[i], v.closes[i - 1]
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return _mean(trs[-period:]) if len(trs) >= period else None


def _rsi(closes: list[float], period: int = 14) -> float | None:
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
    return 100 - 100 / (1 + avg_gain / avg_loss)


def _max_drawdown(closes: list[float]) -> float:
    """最大回撤（正数，%）。"""
    peak = closes[0]
    mdd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            dd = (c / peak - 1.0) * 100
            if dd < mdd:
                mdd = dd
    return mdd


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3 or len(y) != n:
        return 0.0
    mx, my = _mean(x), _mean(y)
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


# ===========================================================================
# 因子 raw 函数（方向统一：返回值越大 → 越看多）
# ===========================================================================

# ------------------------------ 动量 / 反转 ------------------------------
def f_mom_20d(v: KLineView, ctx: dict) -> float | None:
    """20日涨幅。经典动量。"""
    c = v.closes if v.closes is not None else [float(k[2]) for k in v._kl]
    if len(c) < 21 or c[-21] <= 0:
        return None
    return (c[-1] / c[-21] - 1.0) * 100


def f_rev_5d(v: KLineView, ctx: dict) -> float | None:
    """5日反转：-(过去5日涨幅)。
    A股短期反转效应显著——涨得多的接下来容易回吐，所以取负号后才是"越大越看好"。"""
    v._build()
    c = v.closes
    if len(c) < 6 or c[-6] <= 0:
        return None
    return -((c[-1] / c[-6] - 1.0) * 100)


def f_mom_120_20(v: KLineView, ctx: dict) -> float | None:
    """中期动量：120日前 → 20日前的涨幅，剔除最近一个月。
    把"中期趋势"和"短期反转"两个效应切开，避免动量因子被短期反转污染。"""
    v._build()
    c = v.closes
    if len(c) < 121 or c[-121] <= 0:
        return None
    return (c[-21] / c[-121] - 1.0) * 100


def f_dist_high(v: KLineView, ctx: dict) -> float | None:
    """距一年高点回撤（取负）：-(现价/250日最高 - 1)。
    离高点越远 → 值越大（0 = 就在最高点）。捕捉超跌反弹。"""
    v._build()
    h = v.highs[-250:] if v.n > 250 else v.highs
    if not h or h and max(h) <= 0:
        return None
    return -((v.closes[-1] / max(h) - 1.0) * 100)


# ------------------------------ 波动 / 风险 ------------------------------
def f_vol_atr(v: KLineView, ctx: dict) -> float | None:
    """低波动：-(ATR14 / 收盘价)。低波动异象——波动越低未来收益越好。"""
    v._build()
    atr = _atr(v, 14)
    if not atr or v.closes[-1] <= 0:
        return None
    return -(atr / v.closes[-1] * 100)


def f_idio_vol(v: KLineView, ctx: dict) -> float | None:
    """低特异波动：-(对市场收益回归后残差的年化波动 %)。
    A股最强的异象之一：剔除市场波动后的"个股自身波动"越低，未来收益越好。
    需要 ctx["mkt_ret"]（市场等权日收益，由 build_market_ctx 提供）。"""
    mkt = ctx.get("mkt_ret") if ctx else None
    if not mkt:
        return None
    r = v.rets[-60:]
    m = mkt[-60:]
    if len(r) < 40 or len(m) < len(r):
        return None
    m = m[-len(r):]
    beta = _beta(r, m)
    resid = [r[i] - beta * m[i] for i in range(len(r))]
    return -(_std(resid) * (252 ** 0.5) * 100)


def _beta(r: list[float], m: list[float]) -> float:
    n = len(r)
    mr, mm = _mean(r), _mean(m)
    cov = sum((r[i] - mr) * (m[i] - mm) for i in range(n))
    var = sum((x - mm) ** 2 for x in m)
    return cov / var if var > 0 else 1.0


def f_downside_vol(v: KLineView, ctx: dict) -> float | None:
    """低下行波动：-(只统计负收益的年化半方差 %)。
    相比 ATR，只惩罚"往下波动"，不惩罚上涨波动——更符合真实风险感受。"""
    r = v.rets[-60:]
    if len(r) < 40:
        return None
    neg = [x for x in r if x < 0]
    if len(neg) < 5:
        return None
    return -(sum(x ** 2 for x in neg) / len(neg)) ** 0.5 * (252 ** 0.5) * 100


def f_max_dd(v: KLineView, ctx: dict) -> float | None:
    """低回撤：120日最大回撤（负值，越接近 0 = 回撤越小 = 越好）。
    注意 _max_drawdown 返回的已是负数（-40 表示回撤 40%），
    直接返回即可满足"越大越好"，不要再取负号。"""
    v._build()
    c = v.closes[-120:] if v.n > 120 else v.closes
    if len(c) < 60:
        return None
    return _max_drawdown(c)


# ------------------------------ 量能 / 量价 ------------------------------
def f_amihud(v: KLineView, ctx: dict) -> float | None:
    """Amihud 非流动性（取负后 = 流动性越好越高）：
        -log10( mean(|日收益| / 成交量) × 1e8 + 1 )
    含义：单位成交量推动的价格冲击越小 → 流动性越好 → 值越大。
    流动性差的股票需要更高的预期收益补偿（流动性溢价），
    但在短线选股里，流动性好 = 进出不滑点，实战更优。"""
    r = v.rets[-60:]
    v._build()
    vol = v.volumes[-60:]
    if len(r) < 40 or len(vol) < len(r):
        return None
    vol = vol[-len(r):]
    impact = [
        abs(r[i]) / vol[i] if vol[i] > 0 else 0.0
        for i in range(len(r))
    ]
    avg = _mean(impact)
    if avg <= 0:
        return None
    return -math.log10(avg * 1e8 + 1.0)


def f_vol_trend(v: KLineView, ctx: dict) -> float | None:
    """量能温和放大：-|5日均量/60日均量 - 1.5|。
    温和放量（约1.5倍）最优；突然爆量往往是出货，缩量则无人问津。"""
    v._build()
    vol = v.volumes
    if len(vol) < 60:
        return None
    r5 = _mean(vol[-5:])
    r60 = _mean(vol[-60:])
    if r60 <= 0:
        return None
    return -abs(r5 / r60 - 1.5)


def f_vol_stab(v: KLineView, ctx: dict) -> float | None:
    """量能稳定性：-(60日成交量变异系数)。持续稳定放量 > 忽大忽小。"""
    v._build()
    vol = v.volumes[-60:]
    if len(vol) < 40:
        return None
    m = _mean(vol)
    if m <= 0:
        return None
    return -(_std(vol) / m)


def f_vol_price(v: KLineView, ctx: dict) -> float | None:
    """量价比：-|5日均量/前20日均量 - 2.0|（沿用旧 vol_price）。"""
    v._build()
    vol = v.volumes
    if len(vol) < 25:
        return None
    recent = _mean(vol[-5:])
    base = _mean(vol[-25:-5])
    if base <= 0:
        return None
    return -abs(recent / base - 2.0)


def f_vp_corr(v: KLineView, ctx: dict) -> float | None:
    """量价相关性：过去20日 corr(成交量, 收益)。
    >0 = 价涨量增、价跌量缩（健康）；<0 = 价涨量缩（背离，上涨乏力）。"""
    r = v.rets[-20:]
    v._build()
    vol = v.volumes[-20:]
    if len(r) < 15 or len(vol) < len(r):
        return None
    return _pearson(vol[-len(r):], r)


# ------------------------------ 技术形态 ------------------------------
def f_trend_ma20(v: KLineView, ctx: dict) -> float | None:
    """趋势位置：(收盘 - MA20) / MA20 %（旧 trend 的连续化版本）。
    旧版是"站上MA20 +20分、MA20>MA60 +20分"的离散加分，台阶化严重且
    与 IC 版定义不一致。改成连续值后与 IC 完全同源。"""
    v._build()
    c = v.closes
    ma20 = _sma(c, 20)
    if not ma20 or ma20 <= 0:
        return None
    return (c[-1] - ma20) / ma20 * 100


def f_ma_slope60(v: KLineView, ctx: dict) -> float | None:
    """MA60 斜率：MA60 相对 10 日前的 MA60 变化 %。中期趋势方向。"""
    v._build()
    c = v.closes
    if len(c) < 70:
        return None
    ma_now = _sma(c, 60)
    ma_prev = _sma(c[:-10], 60) if len(c) > 70 else None
    if not ma_now or not ma_prev or ma_prev <= 0:
        return None
    return (ma_now / ma_prev - 1.0) * 100


def f_rsi_mid(v: KLineView, ctx: dict) -> float | None:
    """RSI 中性：-|RSI14 - 50|。不追超买、不接超卖（沿用旧 rsi 逻辑）。"""
    v._build()
    rsi = _rsi(v.closes, 14)
    if rsi is None:
        return None
    return -abs(rsi - 50)


def f_bb_pos(v: KLineView, ctx: dict) -> float | None:
    """布林带中性位置：-|布林位置 - 0.5| × 100。
    贴近上轨(1.0)短期过热，贴近下轨(0.0)弱势，中枢附近最健康。"""
    v._build()
    c = v.closes
    if len(c) < 20:
        return None
    ma20 = _sma(c, 20)
    sd = _std(c[-20:])
    if not ma20 or sd <= 0:
        return None
    upper, lower = ma20 + 2 * sd, ma20 - 2 * sd
    if upper <= lower:
        return None
    pos = (c[-1] - lower) / (upper - lower)
    return -abs(pos - 0.5) * 100


def f_macd_hist(v: KLineView, ctx: dict) -> float | None:
    """MACD 柱 / 收盘价 %：动能拐点。红柱放大=动能增强。"""
    v._build()
    c = v.closes
    if len(c) < 35:
        return None
    def ema(vals, p):
        k = 2.0 / (p + 1)
        e = vals[0]
        for x in vals[1:]:
            e = x * k + e * (1 - k)
        return e
    # 用滑动窗口近似 EMA12/EMA26（避免全序列递归，够用且快）
    e12 = _ema_series(c, 12)
    e26 = _ema_series(c, 26)
    if e12 is None or e26 is None:
        return None
    diff = e12 - e26
    dea = _ema_series([diff], 9)
    hist = (diff - dea) if dea is not None else diff
    if c[-1] <= 0:
        return None
    return hist / c[-1] * 100


def _ema_series(vals: list[float], period: int) -> float | None:
    """返回序列末端的 EMA 值（递归全序列，O(n)）。"""
    if len(vals) < period:
        return None
    k = 2.0 / (period + 1)
    e = _mean(vals[:period])
    for x in vals[period:]:
        e = x * k + e * (1 - k)
    return e


# ------------------------------ 统计特征 ------------------------------
def f_skew(v: KLineView, ctx: dict) -> float | None:
    """收益偏度（取负）：-(60日日收益偏度)。
    正偏度（少数几天暴涨）= 彩票型股票，A股实证未来收益更差。"""
    r = v.rets[-60:]
    if len(r) < 40:
        return None
    m = _mean(r)
    s = _std(r)
    if s <= 0:
        return None
    n = len(r)
    return -(sum(((x - m) / s) ** 3 for x in r) / n)


def f_beta_low(v: KLineView, ctx: dict) -> float | None:
    """低 Beta：-Beta（对市场等权收益回归）。低 beta 异象。"""
    mkt = ctx.get("mkt_ret") if ctx else None
    if not mkt:
        return None
    r = v.rets[-60:]
    m = mkt[-60:]
    if len(r) < 40 or len(m) < len(r):
        return None
    return -_beta(r, m[-len(r):])


# ------------------------------ 资金流向 ------------------------------
# 数据来自 cache/moneyflow_history.json（fetch_moneyflow.py 抓取 Tushare moneyflow）。
# ctx["flow"] = {"main_ratio": [...], "main_net": [...], "total_amt": [...]}
# 数组按 v.dates 对齐（长度 = v.n），缺失处为 None。
def _mf_series(v: KLineView, ctx: dict, field: str) -> list[float] | None:
    """从 ctx 取资金流字段（按 v.dates 对齐）。无资金流数据返回 None。"""
    flow = (ctx or {}).get("flow") or {}
    arr = flow.get(field)
    if not arr:
        return None
    return arr


def _mf_valid(arr: list[float] | None, n: int) -> list[float]:
    """取最近 n 个非 None 值。"""
    return [x for x in (arr or [])[-n:] if x is not None]


def f_mf_ratio(v: KLineView, ctx: dict) -> float | None:
    """当日主力净流入占成交额比(%)。值越大主力越主动买入。"""
    vals = _mf_valid(_mf_series(v, ctx, "main_ratio"), 1)
    return vals[-1] if vals else None


def f_mf_ratio_5d(v: KLineView, ctx: dict) -> float | None:
    """过去 5 日主力净流入占比之和(%)。短期资金持续流入。"""
    vals = _mf_valid(_mf_series(v, ctx, "main_ratio"), 5)
    if len(vals) < 3:
        return None
    return sum(vals)


def f_mf_ratio_20d(v: KLineView, ctx: dict) -> float | None:
    """过去 20 日主力净流入占比之和(%)。中期资金持续流入。"""
    vals = _mf_valid(_mf_series(v, ctx, "main_ratio"), 20)
    if len(vals) < 10:
        return None
    return sum(vals)


def f_mf_accel(v: KLineView, ctx: dict) -> float | None:
    """资金流入加速度：近 5 日占比均值 − 近 20 日占比均值。加速流入越看好。"""
    arr = _mf_series(v, ctx, "main_ratio")
    if arr is None:
        return None
    recent = _mf_valid(arr[-5:], 5)
    base = _mf_valid(arr[-20:-5], 15)
    if len(recent) < 3 or len(base) < 8:
        return None
    return _mean(recent) - _mean(base)


# ------------------------------ 基本面 ------------------------------
# 数据来自 cache/fundamental_history.json（fetch_fundamental.py 抓 Tushare fina_indicator）。
# ctx["fundamental"] = {"roe": [...], "netprofit_yoy": [...]}
# 数组按 v.dates 对齐（长度 = v.n），已做「按公告日前向填充」，缺失处为 None。
def _fund_series(v: KLineView, ctx: dict, field: str) -> list[float] | None:
    """从 ctx 取基本面字段（按 v.dates 对齐）。无基本面数据返回 None。"""
    fund = (ctx or {}).get("fundamental") or {}
    arr = fund.get(field)
    if not arr:
        return None
    return arr


def f_roe(v: KLineView, ctx: dict) -> float | None:
    """最近已披露 ROE 净资产收益率(%)。盈利能力越强越看好。"""
    arr = _fund_series(v, ctx, "roe")
    if not arr:
        return None
    val = arr[-1]
    return val if val is not None else None


def f_profit_yoy(v: KLineView, ctx: dict) -> float | None:
    """最近已披露归母净利润同比增速(%)，截尾到 [-100, 200]。成长越强越看好。"""
    arr = _fund_series(v, ctx, "netprofit_yoy")
    if not arr:
        return None
    val = arr[-1]
    if val is None:
        return None
    return max(-100.0, min(200.0, val))


# ===========================================================================
# 因子注册表 —— 补因子只需在这里加一条
# ===========================================================================
FACTORS: dict[str, dict[str, Any]] = {
    # ---------------- 动量反转 ----------------
    "mom_20d": {
        "label": "20日涨幅(%)", "category": "动量反转",
        "raw": f_mom_20d, "lo": -15.0, "hi": 35.0, "min_bars": 21,
        "legacy": "momentum",
    },
    "rev_5d": {
        "label": "-5日涨幅(%)（短期反转）", "category": "动量反转",
        "raw": f_rev_5d, "lo": -12.0, "hi": 8.0, "min_bars": 6,
    },
    "mom_120_20": {
        "label": "120→20日前涨幅(%)（中期动量）", "category": "动量反转",
        "raw": f_mom_120_20, "lo": -45.0, "hi": 85.0, "min_bars": 121,
    },
    "dist_high": {
        "label": "-距250日高点(%)（超跌）", "category": "动量反转",
        "raw": f_dist_high, "lo": 0.0, "hi": 60.0, "min_bars": 60,
    },
    # ---------------- 波动风险 ----------------
    "vol_atr": {
        "label": "-ATR14占比(%)（低波动）", "category": "波动风险",
        "raw": f_vol_atr, "lo": -9.0, "hi": -1.5, "min_bars": 15,
        "legacy": "volatility",
    },
    "idio_vol": {
        "label": "-特异波动年化(%)", "category": "波动风险",
        "raw": f_idio_vol, "lo": -100.0, "hi": -20.0, "min_bars": 61,
    },
    "downside_vol": {
        "label": "-下行波动年化(%)", "category": "波动风险",
        "raw": f_downside_vol, "lo": -105.0, "hi": -22.0, "min_bars": 61,
    },
    "max_dd": {
        "label": "-120日最大回撤(%)", "category": "波动风险",
        "raw": f_max_dd, "lo": -60.0, "hi": -15.0, "min_bars": 60,
    },
    # ---------------- 量能量价 ----------------
    "amihud": {
        "label": "-Amihud非流动性（流动性越好越高）", "category": "量能量价",
        "raw": f_amihud, "lo": -2.0, "hi": -0.1, "min_bars": 61,
    },
    "vol_trend": {
        "label": "-|5/60日均量比-1.5|（温和放量）", "category": "量能量价",
        "raw": f_vol_trend, "lo": -1.2, "hi": -0.1, "min_bars": 60,
    },
    "vol_stab": {
        "label": "-成交量变异系数（量能稳定）", "category": "量能量价",
        "raw": f_vol_stab, "lo": -0.9, "hi": -0.25, "min_bars": 60,
    },
    "vol_price": {
        "label": "-|量比-2.0|", "category": "量能量价",
        "raw": f_vol_price, "lo": -1.8, "hi": -0.1, "min_bars": 25,
        "monotonic": False,  # 倒U型：中间最优，秩相关无法表达，不参与翻转
        "legacy": "vol_price",
    },
    "vp_corr": {
        "label": "20日量价相关性", "category": "量能量价",
        "raw": f_vp_corr, "lo": -0.4, "hi": 0.6, "min_bars": 21,
    },
    # ---------------- 技术形态 ----------------
    "trend_ma20": {
        "label": "(收盘-MA20)/MA20(%)", "category": "技术形态",
        "raw": f_trend_ma20, "lo": -12.0, "hi": 10.0, "min_bars": 20,
        "legacy": "trend",
    },
    "ma_slope60": {
        "label": "MA60十日斜率(%)", "category": "技术形态",
        "raw": f_ma_slope60, "lo": -7.0, "hi": 5.0, "min_bars": 70,
    },
    "rsi_mid": {
        "label": "-|RSI14-50|（中性最佳）", "category": "技术形态",
        "raw": f_rsi_mid, "lo": -18.0, "hi": 0.0, "min_bars": 15,
        "legacy": "rsi",
    },
    "bb_pos": {
        "label": "-|布林位置-0.5|×100", "category": "技术形态",
        "raw": f_bb_pos, "lo": -55.0, "hi": -1.0, "min_bars": 20,
    },
    "macd_hist": {
        "label": "MACD柱/收盘(%)", "category": "技术形态",
        "raw": f_macd_hist, "lo": -5.0, "hi": 3.0, "min_bars": 35,
    },
    # ---------------- 统计特征 ----------------
    "skew": {
        "label": "-60日收益偏度", "category": "统计特征",
        "raw": f_skew, "lo": -1.5, "hi": 0.3, "min_bars": 61,
    },
    "beta_low": {
        "label": "-Beta（低beta）", "category": "统计特征",
        "raw": f_beta_low, "lo": -2.7, "hi": 0.1, "min_bars": 61,
    },
    # ---------------- 资金流向 ----------------
    "mf_main_ratio": {
        "label": "主力净流入占比(%)", "category": "资金流向",
        "raw": f_mf_ratio, "lo": -5.0, "hi": 5.0, "min_bars": 1,
    },
    "mf_ratio_5d": {
        "label": "5日主力净流入占比累计(%)", "category": "资金流向",
        "raw": f_mf_ratio_5d, "lo": -15.0, "hi": 15.0, "min_bars": 5,
    },
    "mf_ratio_20d": {
        "label": "20日主力净流入占比累计(%)", "category": "资金流向",
        "raw": f_mf_ratio_20d, "lo": -60.0, "hi": 60.0, "min_bars": 20,
    },
    "mf_accel": {
        "label": "资金流入加速度(5日-20日)", "category": "资金流向",
        "raw": f_mf_accel, "lo": -2.0, "hi": 2.0, "min_bars": 20,
    },
    # ---------------- 基本面 ----------------
    "roe": {
        "label": "ROE净资产收益率(%)", "category": "基本面",
        "raw": f_roe, "lo": -12.0, "hi": 27.0, "min_bars": 1,
    },
    "profit_yoy": {
        "label": "净利润同比增速(%)", "category": "基本面",
        "raw": f_profit_yoy, "lo": -100.0, "hi": 200.0, "min_bars": 1,
    },
}

FACTOR_NAMES: list[str] = list(FACTORS.keys())

# 旧因子名 → 新因子名（用于平滑迁移，避免历史 IC 记录错位）
LEGACY_MAP: dict[str, str] = {
    v["legacy"]: k for k, v in FACTORS.items() if v.get("legacy")
}


# ===========================================================================
# 权重计算
# ===========================================================================
def base_weights() -> dict[str, float]:
    """大类权重 → 因子权重（类内等权），再全局归一化。"""
    cat_count: dict[str, int] = {}
    for f in FACTORS.values():
        cat = f["category"]
        cat_count[cat] = cat_count.get(cat, 0) + 1

    raw_w: dict[str, float] = {}
    for name, f in FACTORS.items():
        cat_w = CATEGORY_WEIGHTS.get(f["category"], 0.1)
        raw_w[name] = cat_w / max(1, cat_count[f["category"]])

    total = sum(raw_w.values())
    if total <= 0:
        n = len(raw_w)
        return {k: 1.0 / n for k in raw_w}
    return {k: round(v / total, 4) for k, v in raw_w.items()}


def adjust_weights(
    weights: dict[str, float],
    status: dict[str, str],
) -> dict[str, float]:
    """按 IC 状态调整权重后归一化。"""
    adj = {
        k: w * STATUS_MULTIPLIER.get(status.get(k, "insufficient"), 0.5)
        for k, w in weights.items()
    }
    total = sum(adj.values())
    if total <= 0:
        n = len(adj)
        return {k: 1.0 / n for k in adj}
    return {k: round(v / total, 4) for k, v in adj.items()}


# ===========================================================================
# 原始值 / 评分
# ===========================================================================
def raw_to_score(name: str, raw: float | None) -> float | None:
    """raw → 0-100。线性截断映射（单调，不破坏 IC 排序）。"""
    if raw is None:
        return None
    spec = FACTORS.get(name)
    if not spec:
        return None
    lo, hi = spec["lo"], spec["hi"]
    if hi == lo:
        return 50.0
    s = (raw - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, s))


def compute_raw(kl: list, ctx: dict | None = None,
                names: list[str] | None = None,
                code: str | None = None) -> dict[str, float | None]:
    """对一只股票的K线切片计算全部因子的原始值。
    内部只回溯 MAX_LOOKBACK 根，避免长序列无谓复制。
    code：6 位股票代码，用于资金流因子按日期取数（可选，向后兼容）。"""
    if not kl:
        return {}
    spec_names = names or FACTOR_NAMES
    need = max((FACTORS[n]["min_bars"] for n in spec_names), default=1)
    need = max(need, MAX_LOOKBACK)
    view_kl = kl[-need:] if len(kl) > need else kl
    v = KLineView(view_kl)
    v._build()

    # 外部数据因子（资金流/基本面）需要按日期对齐的序列；无 code 或数据缺失时退化为纯量价
    eff_ctx = ctx or {}
    if code:
        eff_ctx = inject_flow(eff_ctx, code, v.dates)
        eff_ctx = inject_fundamental(eff_ctx, code, v.dates)

    out: dict[str, float | None] = {}
    for n in spec_names:
        spec = FACTORS[n]
        if v.n < spec["min_bars"]:
            out[n] = None
            continue
        try:
            out[n] = spec["raw"](v, eff_ctx)
        except Exception:
            out[n] = None  # 单因子异常不影响整批
    return out


def score_stock_raw(raws: dict[str, float | None],
                    weights: dict[str, float],
                    flips: dict[str, bool] | None = None) -> dict[str, Any]:
    """原始值 → 各因子分 + 加权总分。
    flips：IC 显著为负的因子翻转使用（100 - score）。"""
    flips = flips or {}
    scores: dict[str, float] = {}
    for name, raw in raws.items():
        s = raw_to_score(name, raw)
        if s is None:
            continue
        if flips.get(name):
            s = 100.0 - s
        scores[name] = round(s, 1)

    w = weights or base_weights()
    num = 0.0
    den = 0.0
    for name, wv in w.items():
        if name in scores:
            num += scores[name] * wv
            den += wv
    total = num / den if den > 0 else 50.0

    return {
        "factor_scores": scores,
        "total_score": round(total, 1),
        "coverage": round(len(scores) / max(1, len(w)), 3),
    }


# ===========================================================================
# 市场收益（beta / 特异波动 的基准）
# ===========================================================================
def build_market_ctx(all_klines: dict[str, list]) -> dict:
    """构造全样本日期 → 市场等权日收益 的映射。
    用于 beta / 特异波动因子：个股收益对"市场平均收益"回归，剥离系统性波动。
    无未来函数——某日的市场收益只由当日与前一日的全市场均价算出。"""
    by_date: dict[str, list[float]] = {}
    for kl in all_klines.values():
        prev = None
        for k in kl:
            c = float(k[2])
            if prev is not None and prev > 0:
                by_date.setdefault(str(k[0]), []).append(c / prev - 1.0)
            prev = c
    mkt = {d: sum(v) / len(v) for d, v in by_date.items() if len(v) >= 5}
    return {"mkt_ret_by_date": mkt}


def slice_market_ctx(ctx: dict, dates: list[str]) -> dict:
    """把全局市场收益按某只股票的日期序列对齐，返回该切片的 ctx。"""
    mkt = ctx.get("mkt_ret_by_date", {})
    if not mkt:
        return {}
    return {"mkt_ret": [mkt.get(d, 0.0) for d in dates]}


# ===========================================================================
# 资金流历史（cache/moneyflow_history.json，fetch_moneyflow.py 抓取）
# ===========================================================================
_MF_CACHE: dict | None = None


def _load_moneyflow(force_reload: bool = False) -> dict[str, dict]:
    """读资金流历史，转成 {code: {field: {date: value}}} 便于按日期 O(1) 查询。
    文件缺失时返回空 dict（资金流因子将返回 None，不污染统计）。"""
    global _MF_CACHE
    if _MF_CACHE is not None and not force_reload:
        return _MF_CACHE
    path = os.path.join(CACHE_DIR, "moneyflow_history.json")
    if not os.path.exists(path):
        _MF_CACHE = {}
        return _MF_CACHE
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        _MF_CACHE = {}
        return _MF_CACHE

    fields = ("main_ratio", "main_net", "total_amt")
    out: dict[str, dict] = {}
    for code, rec in data.get("stocks", {}).items():
        dates = rec.get("dates") or []
        entry: dict[str, dict] = {fld: {} for fld in fields}
        for fld in fields:
            arr = rec.get(fld) or []
            entry[fld] = {d: v for d, v in zip(dates, arr)}
        out[code] = entry
    _MF_CACHE = out
    return out


def slice_moneyflow(code: str, dates: list[str]) -> dict | None:
    """把某只股票的资金流按日期序列对齐，返回 {field: [值或None]}。
    无该股票资金流数据时返回 None。"""
    rec = _load_moneyflow().get(code)
    if not rec:
        return None
    out: dict[str, list] = {}
    for fld in ("main_ratio", "main_net", "total_amt"):
        by_date = rec.get(fld, {})
        out[fld] = [
            by_date.get((d.replace("-", "") if isinstance(d, str) else str(d)))
            for d in dates
        ]
    return out


def inject_flow(ctx: dict | None, code: str, dates: list[str]) -> dict:
    """把资金流序列注入 ctx（按日期对齐）。无资金流数据时原样返回。"""
    flow = slice_moneyflow(code, dates) if code else None
    if not flow:
        return ctx or {}
    merged = dict(ctx or {})
    merged["flow"] = flow
    return merged


# ===========================================================================
# 基本面历史（cache/fundamental_history.json，fetch_fundamental.py 抓取）
# ===========================================================================
_FUND_CACHE: dict | None = None


def _load_fundamental(force_reload: bool = False) -> dict[str, dict]:
    """读基本面历史，转成 {code: {ann_dates:[...], roe:{ann_date:val}, ...}}。
    文件缺失时返回空 dict（基本面因子将返回 None，不污染统计）。"""
    global _FUND_CACHE
    if _FUND_CACHE is not None and not force_reload:
        return _FUND_CACHE
    path = os.path.join(CACHE_DIR, "fundamental_history.json")
    if not os.path.exists(path):
        _FUND_CACHE = {}
        return _FUND_CACHE
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        _FUND_CACHE = {}
        return _FUND_CACHE

    out: dict[str, dict] = {}
    for code, rec in data.get("stocks", {}).items():
        ad = rec.get("ann_dates") or []
        roe = rec.get("roe") or []
        g = rec.get("netprofit_yoy") or []
        out[code] = {
            "ann_dates": ad,  # 升序 YYYYMMDD
            "roe": {a: v for a, v in zip(ad, roe)},
            "netprofit_yoy": {a: v for a, v in zip(ad, g)},
        }
    _FUND_CACHE = out
    return out


def slice_fundamental(code: str, dates: list[str]) -> dict | None:
    """把某只股票的基本面按日期前向填充，返回 {field: [值或None]}。
    无前视：用公告日严格小于 K 线日期（盘后公告，次日才生效）的最近一条财报。"""
    rec = _load_fundamental().get(code)
    if not rec:
        return None
    ann_dates = rec.get("ann_dates") or []
    if not ann_dates:
        return None
    roe_map = rec.get("roe", {})
    g_map = rec.get("netprofit_yoy", {})

    out_roe: list[float | None] = []
    out_g: list[float | None] = []
    for d in dates:
        key = d.replace("-", "") if isinstance(d, str) else str(d)
        idx = bisect.bisect_left(ann_dates, key) - 1  # 最后一个 ann_date < key
        if idx < 0:
            out_roe.append(None)
            out_g.append(None)
        else:
            ad = ann_dates[idx]
            out_roe.append(roe_map.get(ad))
            out_g.append(g_map.get(ad))
    return {"roe": out_roe, "netprofit_yoy": out_g}


def inject_fundamental(ctx: dict | None, code: str, dates: list[str]) -> dict:
    """把基本面序列注入 ctx（按日期前向填充）。无数据时原样返回。"""
    fund = slice_fundamental(code, dates) if code else None
    if not fund:
        return ctx or {}
    merged = dict(ctx or {})
    merged["fundamental"] = fund
    return merged


# ===========================================================================
# 自检 / 分布校准
# ===========================================================================
def _load_klines() -> dict[str, list]:
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for code, st in data.get("stocks", {}).items():
        kl = st.get("kline") or []
        if len(kl) >= 60:
            out[code] = kl
    return out


def calibrate(sample: int = 80, percentiles: tuple[float, float] = (2, 98)) -> dict:
    """统计各因子 raw 值的经验分位，输出建议的 lo/hi（用于回填 FACTORS）。"""
    kl_all = _load_klines()
    if not kl_all:
        return {}
    codes = list(kl_all.keys())[:sample]
    ctx = build_market_ctx(kl_all)

    collected: dict[str, list[float]] = {n: [] for n in FACTOR_NAMES}
    for code in codes:
        kl = kl_all[code]
        v = KLineView(kl[-MAX_LOOKBACK:])
        v._build()
        c = inject_flow(slice_market_ctx(ctx, v.dates), code, v.dates)
        c = inject_fundamental(c, code, v.dates)
        for n in FACTOR_NAMES:
            spec = FACTORS[n]
            if v.n < spec["min_bars"]:
                continue
            try:
                val = spec["raw"](v, c)
            except Exception:
                val = None
            if val is not None and val == val:  # 排除 NaN
                collected[n].append(val)

    def pct(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
        return s[idx]

    advice = {}
    for n, vals in collected.items():
        if len(vals) < 10:
            advice[n] = {"n": len(vals), "lo": None, "hi": None,
                         "cur_lo": FACTORS[n]["lo"], "cur_hi": FACTORS[n]["hi"]}
            continue
        advice[n] = {
            "n": len(vals),
            "lo": round(pct(vals, percentiles[0]), 2),
            "hi": round(pct(vals, percentiles[1]), 2),
            "cur_lo": FACTORS[n]["lo"],
            "cur_hi": FACTORS[n]["hi"],
        }
    return advice


if __name__ == "__main__":
    import sys
    print(f"因子库：{len(FACTORS)} 个因子 / {len(CATEGORY_WEIGHTS)} 个大类")
    print(f"{'因子':<14}{'大类':<10}{'基础权重':>9}   说明")
    print("-" * 78)
    bw = base_weights()
    for n, spec in FACTORS.items():
        print(f"{n:<14}{spec['category']:<10}{bw[n]:>9.4f}   {spec['label']}")
    print("-" * 78)
    print("大类权重:", CATEGORY_WEIGHTS)
    print("权重合计:", round(sum(bw.values()), 4))

    if "--calibrate" in sys.argv:
        print("\n=== raw 值经验分位（p2 / p98），用于回填 lo/hi ===")
        print(f"{'因子':<14}{'样本数':>7}{'建议lo':>11}{'建议hi':>11}{'当前lo':>10}{'当前hi':>10}")
        print("-" * 66)
        for n, a in calibrate().items():
            print(f"{n:<14}{a['n']:>7}{str(a['lo']):>11}{str(a['hi']):>11}"
                  f"{a['cur_lo']:>10}{a['cur_hi']:>10}")
