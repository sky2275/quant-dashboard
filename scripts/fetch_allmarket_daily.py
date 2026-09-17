#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_allmarket_daily.py — 抓全市场日线（Tushare），供形态扫描用
=================================================================
Tushare 的 daily 接口按「单个交易日」返回全市场（5500+ 只），
比按股票逐个抓效率高 5000 倍：250 个交易日 = 250 次调用。

输出：cache/allmarket_daily.parquet
  列：ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol, amount
输出：cache/allmarket_basic.parquet
  列：ts_code, name, industry, market, list_date

用法：
  python3 scripts/fetch_allmarket_daily.py            # 默认抓 250 个交易日
  python3 scripts/fetch_allmarket_daily.py 120        # 抓 120 个交易日
  python3 scripts/fetch_allmarket_daily.py 250 20260917
"""
import os
import sys
import time
import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
OUT_DAILY = os.path.join(CACHE, "allmarket_daily.parquet")
OUT_BASIC = os.path.join(CACHE, "allmarket_basic.parquet")

SLEEP = 0.12  # 限速


def get_trade_days(pro, end_date, n_days):
    """取最近 n_days 个交易日（升序返回）"""
    start = (datetime.datetime.strptime(end_date, "%Y%m%d") -
             datetime.timedelta(days=int(n_days * 1.8) + 40)).strftime("%Y%m%d")
    df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end_date, is_open="1")
    days = sorted(df["cal_date"].astype(str).tolist())
    return days[-n_days:]


def main():
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    end_date = sys.argv[2] if len(sys.argv) > 2 else datetime.datetime.now().strftime("%Y%m%d")

    pro = feed._tushare_pro()
    if pro is None:
        print("[ERR] Tushare 不可用")
        return 1

    # ── 1. 股票基础信息 ──────────────────────────────────
    print(f"[1/2] 抓股票基础信息 ...")
    try:
        basic = pro.stock_basic(exchange="", list_status="L",
                                fields="ts_code,name,area,industry,market,list_date")
        basic.to_parquet(OUT_BASIC, index=False)
        print(f"      {len(basic)} 只 → {OUT_BASIC}")
    except Exception as e:
        print(f"      [WARN] stock_basic 失败: {e}")
        basic = None

    # ── 2. 逐日抓全市场日线 ──────────────────────────────
    days = get_trade_days(pro, end_date, n_days)
    print(f"[2/2] 抓 {len(days)} 个交易日全市场日线 "
          f"({days[0]} ~ {days[-1]})，预计 {len(days)*SLEEP:.0f}s ...")

    frames = []
    ok = fail = 0
    for i, d in enumerate(days, 1):
        try:
            df = pro.daily(trade_date=d,
                           fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount")
            if df is not None and len(df):
                frames.append(df)
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"      [WARN] {d} 失败: {str(e)[:60]}")
        time.sleep(SLEEP)
        if i % 25 == 0 or i == len(days):
            print(f"      {i}/{len(days)}  ok={ok} fail={fail}")

    if not frames:
        print("[ERR] 无数据")
        return 1

    all_df = pd.concat(frames, ignore_index=True)
    all_df["trade_date"] = all_df["trade_date"].astype(str)
    all_df = all_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    all_df.to_parquet(OUT_DAILY, index=False)

    size_mb = os.path.getsize(OUT_DAILY) / 1024 / 1024
    print(f"\n[OK] {len(all_df):,} 条 / {all_df['ts_code'].nunique()} 只 / "
          f"{all_df['trade_date'].nunique()} 天 → {OUT_DAILY} ({size_mb:.1f} MB)")
    print(f"     成功 {ok} 天，失败 {fail} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
