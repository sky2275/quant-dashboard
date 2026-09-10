#!/usr/bin/env python3
"""2026-09-10 抓 12 只持仓股最新 K 线（覆盖 9/1~9/10 增量）"""
import json, sys, os, urllib.request
from pathlib import Path
from datetime import datetime

ROOT = Path("/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard")
HOLD = ROOT / "cache" / "holdings.json"
KL_NEW = ROOT / "cache" / "holdings_kline_20260910.json"
KL_BASE = ROOT / "cache" / "backtest_klines.json"  # 8/30 旧数据

# 6 只持仓 + 复用 K 线池
with open(HOLD) as f:
    hold = json.load(f)
codes = []
for p in hold["positions"]:
    if p["code"] not in codes:
        codes.append(p["code"])
print(f"[scan] {len(codes)} 只持仓代码: {codes}")

# 复用旧 K 线池
kline_pool = {}
if KL_BASE.exists():
    with open(KL_BASE) as f:
        kline_pool = json.load(f).get("stocks", {})

def mkt_prefix(code):
    if code.startswith(("600","601","603","688","605")): return "sh"
    return "sz"

def fetch_kline(code, days=130):
    pref = mkt_prefix(code)
    sym = f"{pref}{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{days},qfq"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://gu.qq.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="ignore")
        d = json.loads(text)
        sym_data = d.get("data", {}).get(sym, {})
        day_arr = sym_data.get("qfqday") or sym_data.get("day") or []
        return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
                 "high": float(r[3]), "low": float(r[4]), "volume": int(float(r[5]))}
                for r in day_arr if len(r) >= 6]
    except Exception as e:
        return None

result = {}
for code in codes:
    # 优先新抓（覆盖 9 月增量）
    new_kl = fetch_kline(code, days=130)
    old_kl_raw = kline_pool.get(code, {}).get("kline", [])
    # 兼容旧 pool 里 dict-of-list 结构
    if isinstance(old_kl_raw, dict):
        old_kl = old_kl_raw.get("data", [])
    elif isinstance(old_kl_raw, list):
        old_kl = old_kl_raw
    else:
        old_kl = []

    if new_kl:
        # 旧截到新数据首日之前
        first_new_date = new_kl[0]["date"] if new_kl else "20990101"
        # 旧数据可能是 tuple list 或 dict list
        old_only = []
        for k in old_kl:
            if isinstance(k, dict):
                d = k.get("date", "")
            elif isinstance(k, (list, tuple)):
                d = k[0] if k else ""
            else:
                d = ""
            if d < first_new_date:
                # 转成新格式
                if isinstance(k, dict):
                    old_only.append(k)
                elif isinstance(k, (list, tuple)) and len(k) >= 6:
                    old_only.append({"date": k[0], "open": float(k[1]), "close": float(k[2]),
                                     "high": float(k[3]), "low": float(k[4]), "volume": int(float(k[5]))})
        merged = old_only + new_kl
        name = hold["positions"][next(i for i,p in enumerate(hold["positions"]) if p["code"] == code)]["name"]
        result[code] = {"name": name, "kline": merged}
        print(f"  {code} {name:8s} kline={len(merged)}  首={merged[0]['date']}  末={merged[-1]['date']}  末价={merged[-1]['close']}")
    else:
        # 用旧数据
        old = kline_pool.get(code)
        if old:
            result[code] = old
            print(f"  {code} ⚠️ 抓取失败，复用旧 {len(old.get('kline',[]))} 根")
        else:
            print(f"  {code} ❌ 无 K 线数据")

# 落盘
out = {
    "asof_date": "2026-09-10",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "codes": result,
}
KL_NEW.parent.mkdir(parents=True, exist_ok=True)
with open(KL_NEW, "w") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"[write] {KL_NEW}")
