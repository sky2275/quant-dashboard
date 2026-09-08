"""
fetch_holder_number.py -- 抓取股东户数季报（Tushare stk_holdernumber）

================================================================================
为什么需要这个
================================================================================
筹码集中度是 A 股实证有效的异象之一：股东户数下降 = 大资金吸收筹码 =
未来收益更优。因子体系 v2 当前 28 因子**完全没有**筹码维度——这是
Tushare 15200 积分档「所有打板专题数据、机构调研、龙虎榜」等专有数据
之外的一个**全新独立信息源**。

Tushare 15200 积分档（=15000 档）解锁 stk_holdernumber（股东户数季报）。
每只股每季 1 条（约 4 笔/年），452 只 × 3 年 ≈ 5400 条，数据极轻。

================================================================================
数据源：Tushare pro.stk_holdernumber
================================================================================
字段：
  ann_date     公告日期 YYYYMMDD（市场真正知道该数据的时间点）
  end_date     报告期（季末/年末）
  holder_num   股东户数（户）

⚠️ 无前视关键：按 ann_date 对齐（不是 end_date）。
   例：2025Q3 end_date=20250930，但 ann_date=20251025——必须按公告日，
   否则 2025-10-25 之前的交易日就用了「当时还没披露」的户数。

================================================================================
输出 cache/holder_history.json
================================================================================
  {
    "updated_at": ..., "universe": 452, "source": "tushare_stk_holdernumber",
    "stocks": {
      "600598": {
        "ann_dates": ["20240430", "20250829", ...],  # 升序 YYYYMMDD
        "holder_num": [180_000, 175_000, ...]         # 股东户数（户）
      }
    }
  }

用法：python3 fetch_holder_number.py [start_ann_date] [end_ann_date]
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
OUT_PATH = os.path.join(CACHE_DIR, "holder_history.json")


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


def fetch_stock(pro, ts_code: str, start_ann: str, end_ann: str) -> dict | None:
    """拉单只股票的股东户数季报，按公告日升序。"""
    df = pro.stk_holdernumber(
        ts_code=ts_code, start_date="20200101", end_date="20301231",
        fields="ts_code,ann_date,end_date,holder_num",
    )
    if df is None or df.empty:
        return None

    df = df[df["ann_date"].notna()].sort_values("ann_date")
    # 同一报告期可能多次披露（更新/更正），保留首次公告
    df = df.drop_duplicates(subset=["end_date"], keep="first")
    df = df[(df["ann_date"].astype(str) >= start_ann)
            & (df["ann_date"].astype(str) <= end_ann)]

    ann_dates: list[str] = []
    holder_num: list[float] = []
    for _, r in df.iterrows():
        v = _num(r.get("holder_num"))
        if v is None or v <= 0:
            continue
        ann_dates.append(str(r["ann_date"]))
        holder_num.append(int(v))

    if not ann_dates:
        return None
    return {"ann_dates": ann_dates, "holder_num": holder_num}


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
        print("[fetch_holder_number] 无 Tushare token，退出")
        sys.exit(1)

    if not os.path.exists(KLINES_PATH):
        print(f"[fetch_holder_number] 找不到 {KLINES_PATH}，请先跑 fetch_backtest_klines.py")
        sys.exit(1)
    with open(KLINES_PATH, encoding="utf-8") as f:
        klines = json.load(f)
    codes = [c for c, s in klines.get("stocks", {}).items() if s.get("kline")]
    print(f"[fetch_holder_number] 股票池 {len(codes)} 只，公告日区间 {start} ~ {end}")

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
            print(f"  [{i}/{len(codes)}] {code6} 失败: {e}")
            fail += 1
            time.sleep(0.3)
            continue
        if rec is None or not rec["ann_dates"]:
            fail += 1
        else:
            out_stocks[code6] = rec
            ok += 1
        if i % 30 == 0:
            print(f"  [{i}/{len(codes)}] 已抓 {ok}，失败 {fail}，跳过 {skipped}")
        time.sleep(0.10)

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe": len(out_stocks),
        "source": "tushare_stk_holdernumber",
        "start_ann_date": start,
        "end_ann_date": end,
        "stocks": out_stocks,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_holder_number] 完成：成功 {ok}，失败 {fail}，跳过 {skipped}，"
          f"共 {len(out_stocks)} 只，耗时 {dt:.0f}s")
    print(f"[fetch_holder_number] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
