"""
fetch_sector_daily.py -- 抓取申万一级行业指数日线 + 股票-行业映射（Tushare）

================================================================================
为什么需要这个
================================================================================
因子体系 v2 当前 28 因子全部是「个股绝对水平」视角（动量、波动、资金流、
基本面、估值），**没有「个股相对行业」视角**。

行业相对强度（个股 vs 所属申万一级行业的超额收益）是 A 股实证有效的 alpha：
  · 牛股往往先于行业启动（行业 beta + 个股 alpha）
  · 弱势股跌得比行业还狠 = 行业里最差
  · 适用面：全 A（按行业映射找对应行业指数）

Tushare 15200 积分档（=15000 档）解锁：
  · index_classify    申万行业分类
  · sw_daily          申万行业指数日线
  · index_member_all  申万指数成分股（用于构造 stock→industry 映射）

================================================================================
数据源：Tushare
================================================================================
  pro.index_classify(level='L1', src='SW')     → 30 个申万一级行业 (ts_code, name)
  pro.sw_daily(ts_code, start_date, end_date)  → 行业指数日线 [trade_date, close]
  pro.index_member_all(ts_code=行业代码)        → 行业成分股 (con_code + in_date + out_date)

⚠️ 行业归属有「纳入日 in_date」和「剔除日 out_date」，必须按交易日判断
   该股当前所属行业。空 out_date 视为「当前仍在该行业」。

================================================================================
输出 cache/sector_index_history.json
================================================================================
  {
    "updated_at": ..., "source": "tushare_sw_daily",
    "indices": {                          # 行业指数日线
      "801010.SI": {
        "name": "农林牧渔",
        "dates": ["20240102", ...],
        "closes": [3200.0, ...]
      },
      ...
    },
    "mapping": {                          # 股票-行业当前映射（按 in_date <= 今日 < out_date）
      "600598": "801010.SI",
      ...
    }
  }

用法：python3 fetch_sector_daily.py [start_date] [end_date]
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

OUT_PATH = os.path.join(CACHE_DIR, "sector_index_history.json")


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _ts_to_code6(ts_code: str) -> str:
    s = str(ts_code).strip()
    for suf in (".SH", ".SZ", ".BJ"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


def fetch_sw_index_list(pro) -> list[dict]:
    """拉申万一级行业列表。返回 [{ts_code, name}, ...]。"""
    # src 必须是 SW2021（申万2021版）；src="SW" 会返回空表
    df = pro.index_classify(level="L1", src="SW2021")
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        code = r.get("index_code")
        if not code:
            continue
        # index_code 已经是 "801010.SI" 带后缀，无需再拼 .SI
        out.append({"ts_code": str(code),
                    "name": str(r.get("industry_name", code))})
    return out


def fetch_sw_daily(pro, ts_code: str, start: str, end: str) -> dict | None:
    """拉单个申万行业指数日线。"""
    df = pro.sw_daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date")
    dates: list[str] = []
    closes: list[float] = []
    for _, r in df.iterrows():
        c = _num(r.get("close"))
        if c is None or c <= 0:
            continue
        dates.append(str(r["trade_date"]))
        closes.append(c)
    if not dates:
        return None
    return {"dates": dates, "closes": closes}


def fetch_sw_members(pro, ts_code: str) -> list[dict]:
    """拉一个申万指数的成分股（in_date, out_date, ts_code）。"""
    # 参数名是 index_code（不是 ts_code）；成分股代码字段是 ts_code（不是 con_code）
    df = pro.index_member_all(index_code=ts_code)
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        out.append({
            "con_code": str(r.get("ts_code", "")),
            "in_date": str(r.get("in_date", "")) if r.get("in_date") else "",
            "out_date": str(r.get("out_date", "")) if r.get("out_date") else "",
        })
    return out


def load_existing() -> dict:
    if not os.path.exists(OUT_PATH):
        return {"indices": {}, "mapping": {}}
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"indices": {}, "mapping": {}}


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "20250101"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260830"

    pro = feed._tushare_pro()
    if pro is None:
        print("[fetch_sector_daily] 无 Tushare token，退出")
        sys.exit(1)

    existing = load_existing()
    out_indices: dict[str, dict] = existing.get("indices", {})
    out_mapping: dict[str, str] = existing.get("mapping", {})

    t0 = time.time()

    # ---------- 1. 申万一级行业列表 ----------
    print("[fetch_sector_daily] 拉取申万一级行业列表…")
    sw_list = fetch_sw_index_list(pro)
    print(f"  共 {len(sw_list)} 个申万一级行业")
    if not sw_list:
        sys.exit(1)

    # ---------- 2. 每个行业的日线（断点续跑） ----------
    print(f"[fetch_sector_daily] 拉取日线 {start} ~ {end}…")
    for i, idx in enumerate(sw_list, 1):
        ts = idx["ts_code"]
        if out_indices.get(ts, {}).get("dates"):
            continue
        rec = fetch_sw_daily(pro, ts, start, end)
        if rec:
            out_indices[ts] = {"name": idx["name"], **rec}
            print(f"  [{i}/{len(sw_list)}] {ts} {idx['name']}: {len(rec['dates'])} 根")
        else:
            print(f"  [{i}/{len(sw_list)}] {ts} {idx['name']}: 无数据")
        time.sleep(0.15)

    # ---------- 3. 行业成分股 → 构造 stock→industry 映射 ----------
    print("[fetch_sector_daily] 拉取申万一级行业成分股…")
    latest = max(end, "20260830")
    # 增量：mapping 只对还没归属的股票需要
    need_mapping_codes = set()  # 留作未来扩展，目前覆盖全量
    new_mapping = 0
    for i, idx in enumerate(sw_list, 1):
        ts = idx["ts_code"]
        members = fetch_sw_members(pro, ts)
        for m in members:
            code6 = _ts_to_code6(m["con_code"])
            if len(code6) != 6 or not code6.isdigit():
                continue
            # 按 in_date / out_date 判断：今日仍属于该行业
            in_d = m["in_date"].replace("-", "")
            out_d = m["out_date"].replace("-", "") if m["out_date"] else "99999999"
            if in_d and in_d <= latest and (not out_d or out_d > latest):
                # 若该股已归属其它行业（多次变更），后入的覆盖（行业归类本身有歧义时取最新）
                out_mapping[code6] = ts
                new_mapping += 1
        if i % 10 == 0:
            print(f"  [{i}/{len(sw_list)}] 已映射 {len(out_mapping)} 只股")
        time.sleep(0.20)

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "tushare_sw_daily",
        "start_date": start,
        "end_date": end,
        "n_indices": len(out_indices),
        "n_mapping": len(out_mapping),
        "indices": out_indices,
        "mapping": out_mapping,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    dt = time.time() - t0
    print(f"[fetch_sector_daily] 完成：{len(out_indices)} 个行业指数，"
          f"{len(out_mapping)} 只股的行业映射，耗时 {dt:.0f}s")
    print(f"[fetch_sector_daily] 已写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
