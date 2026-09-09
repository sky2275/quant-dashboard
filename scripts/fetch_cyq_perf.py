"""
fetch_cyq_perf.py -- 抓取筹码分布（Tushare cyq_perf），替代已停更的北向资金因子

================================================================================
为什么改
================================================================================
原 hsgt_chg_20d（北向资金 20 日变化率）依赖 pro.hsgt_hold，但该接口在
Tushare 中**不存在**（返回「请指定正确的接口名」），且北向资金个股持股
明细自 2024-08-16 起全球停更（港/深/沪交易所不再披露），数据已死。

改用 cyq_perf（筹码分布）作「主力/聪明钱」维度替代：
  - 个股级、每日更新、数据新鲜（实测覆盖到当日收盘）
  - 筹码集中度是 A 股实证有效异象：成本带越窄 → 筹码越集中 → 主力控盘
    度越高 → 拉升概率越大
  - 与股东户数（holder_chg_q）角度不同：户数看「户数增减」，筹码带看
    「成本分布带宽」，共线性低

Tushare 15200 积分档解锁 cyq_perf。

================================================================================
数据源：Tushare pro.cyq_perf
================================================================================
字段：
  trade_date  交易日 YYYYMMDD
  cost_5pct   5% 成本价（最便宜 5% 筹码的平均成本）
  cost_50pct  50% 成本价（中位成本）
  cost_95pct  95% 成本价（最贵 5% 筹码的平均成本）
  winner_rate 获利盘比例(%)

================================================================================
输出 cache/cyq_perf_history.json
================================================================================
  {
    "updated_at": ..., "universe": 297, "source": "tushare_cyq_perf",
    "stocks": {
      "300223": {
        "dates": ["20260908", ...],       # 升序 YYYYMMDD
        "cost_5pct": [...], "cost_50pct": [...],
        "cost_95pct": [...], "winner_rate": [...]
      }
    }
  }

用法：python3 fetch_cyq_perf.py [start_date] [end_date]
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feed  # noqa: E402

KLINES_PATH = os.path.join(CACHE_DIR, "backtest_klines.json")
OUT_PATH = os.path.join(CACHE_DIR, "cyq_perf_history.json")


def to_ts_code(code6: str) -> str | None:
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
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def fetch_stock(pro, ts_code: str, start: str, end: str) -> dict | None:
    """拉单只股票每日筹码分布，按交易日升序。"""
    df = pro.cyq_perf(ts_code=ts_code, start_date=start, end_date=end,
                      fields="ts_code,trade_date,cost_5pct,cost_50pct,cost_95pct,winner_rate")
    if df is None or df.empty:
        return None

    df = df[df["trade_date"].notna()].sort_values("trade_date")

    dates: list[str] = []
    c5: list[float] = []
    c50: list[float] = []
    c95: list[float] = []
    wr: list[float] = []
    for _, r in df.iterrows():
        a, b, c = _num(r.get("cost_5pct")), _num(r.get("cost_50pct")), _num(r.get("cost_95pct"))
        if b is None or b <= 0:
            continue
        dates.append(str(r["trade_date"]))
        c5.append(a if a is not None else 0.0)
        c50.append(b)
        c95.append(c if c is not None else 0.0)
        w = _num(r.get("winner_rate"))
        wr.append(w if w is not None else 0.0)

    if not dates:
        return None
    return {"dates": dates, "cost_5pct": c5, "cost_50pct": c50,
            "cost_95pct": c95, "winner_rate": wr}


def load_existing() -> dict:
    if not os.path.exists(OUT_PATH):
        return {"stocks": {}}
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stocks": {}}


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "20240101"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260908"

    pro = feed._tushare_pro()
    if pro is None:
        print("[fetch_cyq_perf] 无 Tushare token，退出")
        sys.exit(1)

    if not os.path.exists(KLINES_PATH):
        print(f"[fetch_cyq_perf] 找不到 {KLINES_PATH}，请先跑 fetch_backtest_klines.py")
        sys.exit(1)
    with open(KLINES_PATH, encoding="utf-8") as f:
        klines = json.load(f)
    codes = [c for c, s in klines.get("stocks", {}).items() if s.get("kline")]
    print(f"[fetch_cyq_perf] 股票池 {len(codes)} 只，区间 {start} ~ {end}")

    existing = load_existing()
    out_stocks: dict[str, dict] = existing.get("stocks", {})
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
            rec = fetch_stock(pro, ts_code, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(codes)}] {code6} 失败: {str(e)[:80]}")
            fail += 1
            time.sleep(0.3)
            continue
        if rec is None or not rec["dates"]:
            fail += 1
        else:
            out_stocks[code6] = rec
            ok += 1
        if i % 30 == 0:
            print(f"  [{i}/{len(codes)}] 已抓 {ok}，失败 {fail}，跳过 {skipped}")
        time.sleep(0.12)

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe": len(out_stocks),
        "source": "tushare_cyq_perf",
        "start_date": start,
        "end_date": end,
        "stocks": out_stocks,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_cyq_perf] 完成：成功 {ok}，失败 {fail}，跳过 {skipped}，"
          f"共 {len(out_stocks)} 只，耗时 {dt:.0f}s")
    print(f"[fetch_cyq_perf] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
