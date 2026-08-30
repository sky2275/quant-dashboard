"""
fetch_fundamental.py -- 抓取个股历史基本面数据（Tushare fina_indicator）

================================================================================
为什么需要这个
================================================================================
资金流因子已证明「新维度数据」能解开纯量价无选股能力的死结。基本面是第二个
新维度：ROE 代表盈利能力、净利润同比代表成长性——这两个都是纯量价和资金流
给不了的维度。

本脚本拉取 297 只股票（backtest_klines.json 的股票池）的历史 ROE / 净利润同比，
落到 cache/fundamental_history.json，供 factor_lib 的基本面因子消费。

================================================================================
数据源：Tushare pro.fina_indicator（财务指标，季度）
================================================================================
字段：
  ann_date       公告日期（YYYYMMDD）——**市场真正知道该财报的时间点**
  end_date       报告期（如 20251231）
  roe            净资产收益率（%）
  roe_waa        加权平均净资产收益率（%）
  netprofit_yoy  归母净利润同比增长率（%）

⚠️ 无前视关键：必须按 ann_date（公告日）对齐，而不是 end_date（报告期）。
   例如 2025 年报 end_date=20251231，但 ann_date=20260321——若按报告期对齐，
   2025 年 12 月之后的交易日就用到了「当时还没披露」的 ROE，属前视偏差。

================================================================================
输出 cache/fundamental_history.json
================================================================================
  {
    "updated_at": ..., "universe": 297, "source": "tushare_fina_indicator",
    "stocks": {
      "600598": {
        "ann_dates": ["20240430", "20240829", ...],   # 公告日升序，YYYYMMDD
        "roe": [7.1325, 12.9386, ...],                # 净资产收益率（%）
        "netprofit_yoy": [3.6125, 2.4120, ...]        # 净利润同比（%）
      }
    }
  }

用法：python3 fetch_fundamental.py [start_ann_date] [end_ann_date]
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
OUT_PATH = os.path.join(CACHE_DIR, "fundamental_history.json")


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


def fetch_stock(pro, ts_code: str, start_ann: str, end_ann: str) -> dict | None:
    """拉单只股票的财务指标，按公告日升序、按报告期去重。失败返回 None。"""
    df = pro.fina_indicator(
        ts_code=ts_code, start_date="20190101", end_date="20301231",
        fields="ts_code,ann_date,end_date,roe,roe_waa,netprofit_yoy",
    )
    if df is None or df.empty:
        return None

    # 去掉报告期为空的异常行，按公告日升序
    df = df[df["ann_date"].notna()].sort_values("ann_date")
    # 同一报告期可能有多条（更正公告等），保留首次公告那条（无前视）
    df = df.drop_duplicates(subset=["end_date"], keep="first")
    # 只保留公告日落在目标区间的
    df = df[(df["ann_date"].astype(str) >= start_ann)
            & (df["ann_date"].astype(str) <= end_ann)]

    ann_dates: list[str] = []
    roe: list[float] = []
    netprofit_yoy: list[float] = []
    for _, r in df.iterrows():
        rv = _num(r.get("roe"))
        gv = _num(r.get("netprofit_yoy"))
        if rv is None and gv is None:
            continue
        ann_dates.append(str(r["ann_date"]))
        roe.append(round(rv, 4) if rv is not None else None)
        netprofit_yoy.append(round(gv, 4) if gv is not None else None)

    if not ann_dates:
        return None
    return {"ann_dates": ann_dates, "roe": roe, "netprofit_yoy": netprofit_yoy}


def load_existing() -> dict:
    if not os.path.exists(OUT_PATH):
        return {"stocks": {}}
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stocks": {}}


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "20230101"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260830"

    pro = feed._tushare_pro()
    if pro is None:
        print("[fetch_fundamental] 无 Tushare token，退出")
        sys.exit(1)

    if not os.path.exists(KLINES_PATH):
        print(f"[fetch_fundamental] 找不到 {KLINES_PATH}，请先跑 fetch_backtest_klines.py")
        sys.exit(1)
    with open(KLINES_PATH, encoding="utf-8") as f:
        klines = json.load(f)
    stocks = klines.get("stocks", {})
    codes = [c for c in stocks if stocks[c].get("kline")]
    print(f"[fetch_fundamental] 股票池 {len(codes)} 只，公告日区间 {start} ~ {end}")

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
        if rec is None or not rec["ann_dates"]:
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
        "source": "tushare_fina_indicator",
        "start_ann_date": start,
        "end_ann_date": end,
        "stocks": out_stocks,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_fundamental] 完成：成功 {ok}，失败 {fail}，跳过 {skipped}，"
          f"共 {len(out_stocks)} 只，耗时 {dt:.0f}s")
    print(f"[fetch_fundamental] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
