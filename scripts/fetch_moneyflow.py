"""
fetch_moneyflow.py -- 抓取个股历史资金流数据（Tushare moneyflow）

================================================================================
为什么需要这个
================================================================================
因子体系 v2 的核心结论是「纯量价因子在 2025-2026 样本上无稳定选股能力」。
死结在于：资金流现在只有**单日快照**（market_snapshot.json 的 heatmap），
只有一天的数据算不了 IC，自然进不了因子库的「双重检验」闭环。

本脚本拉取 297 只股票（backtest_klines.json 的股票池）的历史资金流，
落到 cache/moneyflow_history.json，供 factor_lib 的资金流因子消费。

================================================================================
数据源：Tushare pro.moneyflow（个股资金流向，2010 年至今）
================================================================================
字段（金额单位：万元）：
  buy_sm/md/lg/elg_amount  小/中/大/特大单 买入金额
  sell_sm/md/lg/elg_amount 小/中/大/特大单 卖出金额
  net_mf_amount            全口径净流入额

关键预计算：
  main_net  = (buy_lg + buy_elg) - (sell_lg + sell_elg)   主力净流入（万元）
  total_amt = 全部买卖金额之和                              当日成交额近似（万元）
  main_ratio = main_net / total_amt * 100                  主力净流入占成交额比（%）
     ↑ 无量纲、横截面可比，规避「大市值股票金额天然大」的偏差。

================================================================================
输出 cache/moneyflow_history.json
================================================================================
  {
    "updated_at": ..., "universe": 297, "source": "tushare_moneyflow",
    "start_date": "20230701", "end_date": "20260828",
    "stocks": {
      "600598": {                          # 6 位代码（与 backtest_klines 的 key 一致）
        "dates": ["20240807", ...],        # 升序，YYYYMMDD
        "main_net": [...],                 # 主力净流入（万元）
        "net_mf": [...],                   # 全口径净流入（万元）
        "total_amt": [...],                # 成交额近似（万元）
        "main_ratio": [...]                # 主力净流入占比（%）
      }
    }
  }

用法：python3 fetch_moneyflow.py [start_date] [end_date]
  · 断点续跑：已抓到的股票自动跳过，只补缺失的。
  · 复用 feed._tushare_pro() 读 token（环境变量 TUSHARE_TOKEN 或 config_local.py）。
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
OUT_PATH = os.path.join(CACHE_DIR, "moneyflow_history.json")

# 金额字段（万元）
BUY_FIELDS = ["buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount"]
SELL_FIELDS = ["sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount"]


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


def fetch_stock(pro, ts_code: str, start: str, end: str) -> dict | None:
    """拉单只股票的资金流，返回按日期升序对齐的数组字典。失败返回 None。"""
    df = pro.moneyflow(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date")

    dates: list[str] = []
    main_net: list[float] = []
    net_mf: list[float] = []
    total_amt: list[float] = []
    main_ratio: list[float] = []

    for _, r in df.iterrows():
        buy = sum(_num(r.get(f)) or 0.0 for f in BUY_FIELDS)
        sell = sum(_num(r.get(f)) or 0.0 for f in SELL_FIELDS)
        lg_elg_buy = (_num(r.get("buy_lg_amount")) or 0.0) + (_num(r.get("buy_elg_amount")) or 0.0)
        lg_elg_sell = (_num(r.get("sell_lg_amount")) or 0.0) + (_num(r.get("sell_elg_amount")) or 0.0)
        mn = lg_elg_buy - lg_elg_sell          # 主力净流入（万元）
        ta = buy + sell                        # 成交额近似（万元）
        nm = _num(r.get("net_mf_amount")) or 0.0

        dates.append(str(r["trade_date"]))
        main_net.append(round(mn, 4))
        net_mf.append(round(nm, 4))
        total_amt.append(round(ta, 4))
        main_ratio.append(round(mn / ta * 100.0, 4) if ta > 0 else 0.0)

    return {
        "dates": dates,
        "main_net": main_net,
        "net_mf": net_mf,
        "total_amt": total_amt,
        "main_ratio": main_ratio,
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
    start = sys.argv[1] if len(sys.argv) > 1 else "20230701"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260828"

    pro = feed._tushare_pro()
    if pro is None:
        print("[fetch_moneyflow] 无 Tushare token（环境变量 TUSHARE_TOKEN 或 "
              "scripts/config_local.py），退出")
        sys.exit(1)

    if not os.path.exists(KLINES_PATH):
        print(f"[fetch_moneyflow] 找不到 {KLINES_PATH}，请先跑 fetch_backtest_klines.py")
        sys.exit(1)
    with open(KLINES_PATH, encoding="utf-8") as f:
        klines = json.load(f)
    stocks = klines.get("stocks", {})
    codes = [c for c in stocks if stocks[c].get("kline")]
    print(f"[fetch_moneyflow] 股票池 {len(codes)} 只，区间 {start} ~ {end}")

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
            rec = fetch_stock(pro, ts_code, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(codes)}] {code6} 失败: {e}")
            fail += 1
            time.sleep(0.3)
            continue
        if rec is None or not rec["dates"]:
            fail += 1
        else:
            out_stocks[code6] = rec
            ok += 1
        # 温和节流，避免撞限
        if i % 10 == 0:
            print(f"  [{i}/{len(codes)}] 已抓 {ok}，失败 {fail}，跳过 {skipped}")
        time.sleep(0.15)

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe": len(out_stocks),
        "source": "tushare_moneyflow",
        "start_date": start,
        "end_date": end,
        "stocks": out_stocks,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_moneyflow] 完成：成功 {ok}，失败 {fail}，跳过 {skipped}，"
          f"共 {len(out_stocks)} 只，耗时 {dt:.0f}s")
    print(f"[fetch_moneyflow] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
