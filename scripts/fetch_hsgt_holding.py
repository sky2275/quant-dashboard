"""
fetch_hsgt_holding.py -- 抓取沪深通北向持股明细（Tushare hsgt_hold）

================================================================================
为什么需要这个
================================================================================
因子体系 v2 已用 Tushare 资金流（mf_main_ratio）、基本面（profit_yoy/roe）、
估值（pe_pct/pb_pct）三个维度解开了"纯量价无选股能力"的死结。但还有一个
全新维度一直没用：**北向资金（外资）**。

北向资金对 A 股有独立信息：
  · 外资投研深度强，其调仓常领先内资
  · 5/20 日持股变化率 与 5/20 日收益的相关性，在 A 股 2018 年后显著
  · 适用面：全 A（覆盖广，弱股也覆盖）

Tushare 15200 积分（=15000 档）解锁 hsgt_hold（沪深通持股明细），是引入
"外资维度"因子的最低成本路径。

================================================================================
数据源：Tushare pro.hsgt_hold（沪深通持股明细，2017 年后）
================================================================================
调用方式：pro.hsgt_hold(trade_date='20240801')  一次返回全市场当天 ~3000+ 只
字段：
  trade_date        交易日期
  ts_code           TS 代码（600598.SH）
  hold_amount       持股数量（股）
  hold_ratio        占流通市值比（%）
  hold_change       当日持股数变化（股）

⚠️ 单接口调一次 = 一天的全市场快照。需按交易日历逐天抓。
   交易日历取自 backtest_klines.json（K 线日期 100% 等于交易日）。

================================================================================
输出 cache/hsgt_history.json
================================================================================
  {
    "updated_at": ..., "universe": 452, "source": "tushare_hsgt_hold",
    "stocks": {
      "600598": {
        "dates": ["20240102", ...],      # 升序 YYYYMMDD
        "hold_amount": [12_500_000, ...], # 持股数（股）
        "hold_ratio": [1.85, ...],       # 持股占流通市值比（%）
        "hold_change": [-12_500, ...]    # 当日变化（股）
      }
    }
  }

用法：python3 fetch_hsgt_holding.py [start_date] [end_date]
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
OUT_PATH = os.path.join(CACHE_DIR, "hsgt_history.json")


def to_ts_code(code6: str) -> str | None:
    """6 位 A股代码 → tushare ts_code。"""
    if len(code6) != 6 or not code6.isdigit():
        return None
    if code6[0] in ("6", "9"):
        return code6 + ".SH"
    if code6[0] in ("4", "8"):
        return code6 + ".BJ"
    return code6 + ".SZ"


def _ts_to_code6(ts_code: str) -> str:
    """600598.SH → 600598。"""
    s = str(ts_code).strip()
    for suf in (".SH", ".SZ", ".BJ"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def get_trade_dates(klines_data: dict) -> list[str]:
    """从 backtest_klines.json 取一份完整的交易日历（升序 YYYYMMDD）。

    取最长 K 线那一只的日期列表 = 完整 A 股交易日历（剔除该股停牌日的偏差
    在此接口可忽略；hsgt_hold 当日停牌股无数据是正常的）。"""
    stocks = klines_data.get("stocks", {})
    best = max(stocks.values(), key=lambda s: len(s.get("kline") or []), default=None)
    if not best:
        return []
    return [str(k[0]).replace("-", "") for k in best["kline"]]


def fetch_day(pro, trade_date: str) -> list[dict]:
    """拉一天全市场北向持股 → list of {code6, hold_amount, hold_ratio, hold_change}。"""
    try:
        df = pro.hsgt_hold(trade_date=trade_date)
    except Exception as e:  # noqa: BLE001
        print(f"    {trade_date} 失败: {e}")
        return []
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        code6 = _ts_to_code6(r.get("ts_code", ""))
        if not code6.isdigit() or len(code6) != 6:
            continue
        out.append({
            "code6": code6,
            "hold_amount": _num(r.get("hold_amount")) or 0.0,
            "hold_ratio": _num(r.get("hold_ratio")) or 0.0,
            "hold_change": _num(r.get("hold_change")) or 0.0,
        })
    return out


def load_existing() -> dict:
    if not os.path.exists(OUT_PATH):
        return {"stocks": {}}
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stocks": {}}


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "20250101"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260830"

    pro = feed._tushare_pro()
    if pro is None:
        print("[fetch_hsgt_holding] 无 Tushare token（环境变量 TUSHARE_TOKEN 或 "
              "scripts/config_local.py），退出")
        sys.exit(1)

    if not os.path.exists(KLINES_PATH):
        print(f"[fetch_hsgt_holding] 找不到 {KLINES_PATH}，请先跑 fetch_backtest_klines.py")
        sys.exit(1)
    with open(KLINES_PATH, encoding="utf-8") as f:
        klines = json.load(f)
    pool = set(c for c, s in klines.get("stocks", {}).items() if s.get("kline"))
    print(f"[fetch_hsgt_holding] 股票池 {len(pool)} 只，目标区间 {start} ~ {end}")

    trade_dates = [d for d in get_trade_dates(klines) if start <= d <= end]
    print(f"[fetch_hsgt_holding] 交易日历 {len(trade_dates)} 个")

    existing = load_existing()
    out_stocks: dict[str, dict] = existing.get("stocks", {})
    done_dates: set[str] = set()
    for rec in out_stocks.values():
        for d in rec.get("dates", []):
            done_dates.add(d)

    t0 = time.time()
    new_stocks = 0
    new_rows = 0
    fail_days = 0
    for i, td in enumerate(trade_dates, 1):
        if td in done_dates:
            continue
        rows = fetch_day(pro, td)
        if not rows:
            fail_days += 1
            continue
        for r in rows:
            if r["code6"] not in pool:
                continue
            rec = out_stocks.setdefault(r["code6"],
                                        {"dates": [], "hold_amount": [],
                                         "hold_ratio": [], "hold_change": []})
            rec["dates"].append(td)
            rec["hold_amount"].append(round(r["hold_amount"], 0))
            rec["hold_ratio"].append(round(r["hold_ratio"], 4))
            rec["hold_change"].append(round(r["hold_change"], 0))
            new_rows += 1
            if len(rec["dates"]) == 1:
                new_stocks += 1
        if i % 20 == 0:
            print(f"  [{i}/{len(trade_dates)}] 新增 {new_rows} 行 / 覆盖 {len(out_stocks)} 只 / "
                  f"失败日 {fail_days}")
        time.sleep(0.18)  # 限速保护

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe": len(out_stocks),
        "source": "tushare_hsgt_hold",
        "start_date": start,
        "end_date": end,
        "stocks": out_stocks,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_hsgt_holding] 完成：覆盖 {len(out_stocks)} 只，"
          f"新增 {new_stocks} 只，{new_rows} 行，"
          f"失败 {fail_days} 日，耗时 {dt:.0f}s")
    print(f"[fetch_hsgt_holding] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
