"""
fetch_valuation.py -- 抓取个股历史估值数据（Tushare daily_basic），预计算滚动估值分位

================================================================================
为什么需要这个
================================================================================
资金流、基本面两个新维度已经证明「新维度数据」能解开纯量价无选股能力的死结。
估值是第三个新维度：PE/PB 历史分位代表「当前便宜还是贵」——这是纯量价、资金流、
基本面都给不了的信息。

估值分位（不是绝对值）：
  · 个股 PE/PB 绝对值横截面不可比（不同行业盈利水平/净资产结构差异巨大）。
  · 但「当前 PE 处在它自己过去 250 个交易日的什么位置」是横截面可比的——
    处于自身历史低位的股票（便宜）与处于高位的股票（贵）有本质区别。

本脚本拉取 297 只股票（backtest_klines.json 的股票池）的 PE_TTM / PB 历史，
按交易日升序，预计算「滚动 250 日估值分位」（0=最便宜，1=最贵），落到
cache/valuation_history.json，供 factor_lib 的估值因子消费。

================================================================================
数据源：Tushare pro.daily_basic（每日指标）
================================================================================
字段：
  trade_date   交易日（YYYYMMDD）
  pe_ttm       滚动市盈率（TTM）
  pb           市净率

⚠️ 无前视关键：
  估值分位的窗口必须是「截至当日及以前」的自身历史，绝不能包含未来。
  因为 daily_basic 按 trade_date 升序返回，遍历时只取 [i-window+1, i] 的切片，
  天然不含未来数据。
  pe_ttm <= 0（亏损）或 null 时该日不参与分位（亏损股的 PE 无意义），
  当前日 pe<=0/null → 分位记 None（估值维度不表态，交给 profit_yoy 等因子惩罚）。

================================================================================
输出 cache/valuation_history.json
================================================================================
  {
    "updated_at": ..., "universe": 297, "source": "tushare_daily_basic",
    "window": 250,
    "stocks": {
      "600598": {
        "dates":   ["20220104", ...],     # trade_date 升序，YYYYMMDD
        "pe_ttm":  [24.20, ...],          # 原始 PE_TTM，<=0/null 记 None
        "pb":      [3.31, ...],           # 原始 PB
        "pe_pct":  [0.42, ...],           # 滚动250日分位 [0,1]，0=最便宜
        "pb_pct":  [0.37, ...]            # 滚动250日分位 [0,1]
      }
    }
  }

用法：python3 fetch_valuation.py [start_date] [end_date]
  · 断点续跑：已抓到的股票自动跳过，只补缺失的。
  · 复用 feed._tushare_pro() 读 token。
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feed  # noqa: E402  复用 _tushare_pro() 的 token 读取

KLINES_PATH = os.path.join(CACHE_DIR, "backtest_klines.json")
OUT_PATH = os.path.join(CACHE_DIR, "valuation_history.json")

WINDOW = 250          # 滚动分位窗口（交易日，约 1 年）
MIN_SAMPLES = 60      # 窗口内至少需要的有效样本数，否则分位记 None


def to_ts_code(code6: str) -> str | None:
    """6 位 A股代码 → tushare ts_code（600598 → 600598.SH）。"""
    if len(code6) != 6 or not code6.isdigit():
        return None
    if code6[0] in ("6", "9"):
        return code6 + ".SH"
    if code6[0] in ("4", "8"):
        return code6 + ".BJ"
    return code6 + ".SZ"


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # 排除 NaN
    except (TypeError, ValueError):
        return None


def rolling_pct(vals: list[float | None], window: int = WINDOW,
                min_samples: int = MIN_SAMPLES) -> list[float | None]:
    """计算滚动估值分位。vals 里 <=0 或 None 视为无效（不参与分位）。

    对第 i 个交易日，分位 = 窗口 [i-window+1, i] 内「有效值中 < vals[i] 的比例」。
    当前值无效 → None；窗口有效样本不足 min_samples → None。
    只依赖 i 及之前的数据，无前视。"""
    n = len(vals)
    out: list[float | None] = [None] * n
    for i in range(n):
        cur = vals[i]
        if cur is None or cur <= 0:
            continue
        lo = max(0, i - window + 1)
        window_vals = [x for x in vals[lo:i + 1] if x is not None and x > 0]
        if len(window_vals) < min_samples:
            continue
        cnt_less = sum(1 for x in window_vals if x < cur)
        out[i] = cnt_less / len(window_vals)
    return out


def fetch_stock(pro, ts_code: str) -> dict | None:
    """拉单只股票的 daily_basic，按交易日升序，预计算滚动分位。失败返回 None。"""
    df = pro.daily_basic(
        ts_code=ts_code, start_date="20220101", end_date="20260830",
        fields="ts_code,trade_date,pe_ttm,pb",
    )
    if df is None or df.empty:
        return None

    df = df[df["trade_date"].notna()].sort_values("trade_date")
    df = df.drop_duplicates(subset=["trade_date"], keep="last")

    dates: list[str] = []
    pe: list[float | None] = []
    pb: list[float | None] = []
    for _, r in df.iterrows():
        dates.append(str(r["trade_date"]))
        p = _num(r.get("pe_ttm"))
        b = _num(r.get("pb"))
        pe.append(p if (p is not None and p > 0) else None)
        pb.append(b if (b is not None and b > 0) else None)

    if not dates:
        return None

    return {
        "dates": dates,
        "pe_ttm": pe,
        "pb": pb,
        "pe_pct": rolling_pct(pe),
        "pb_pct": rolling_pct(pb),
    }


def load_existing() -> dict:
    if not os.path.exists(OUT_PATH):
        return {"stocks": {}}
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stocks": {}}


def main() -> None:
    pro = feed._tushare_pro()
    if pro is None:
        print("[fetch_valuation] 无 Tushare token，退出")
        sys.exit(1)

    if not os.path.exists(KLINES_PATH):
        print(f"[fetch_valuation] 找不到 {KLINES_PATH}，请先跑 fetch_backtest_klines.py")
        sys.exit(1)
    with open(KLINES_PATH, encoding="utf-8") as f:
        klines = json.load(f)
    stocks = klines.get("stocks", {})
    codes = [c for c in stocks if stocks[c].get("kline")]
    print(f"[fetch_valuation] 股票池 {len(codes)} 只，滚动分位窗口 {WINDOW} 日")

    existing = load_existing()
    out_stocks = existing.get("stocks", {})
    done = set(out_stocks.keys())

    t0 = time.time()
    ok = fail = skipped = 0
    for i, code6 in enumerate(codes, 1):
        if code6 in done:
            skipped += 1
            continue
        ts_code = to_ts_code(code6)
        if not ts_code:
            fail += 1
            continue
        try:
            rec = fetch_stock(pro, ts_code)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(codes)}] {code6} 失败: {e}")
            fail += 1
            time.sleep(0.5)
            continue
        if rec is None or not rec["dates"]:
            fail += 1
        else:
            out_stocks[code6] = rec
            ok += 1
        if i % 20 == 0:
            print(f"  [{i}/{len(codes)}] 已抓 {ok}，失败 {fail}，跳过 {skipped}")
        time.sleep(0.12)

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe": len(out_stocks),
        "source": "tushare_daily_basic",
        "window": WINDOW,
        "stocks": out_stocks,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_valuation] 完成：成功 {ok}，失败 {fail}，跳过 {skipped}，"
          f"共 {len(out_stocks)} 只，耗时 {dt:.0f}s")
    print(f"[fetch_valuation] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
