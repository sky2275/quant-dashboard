#!/usr/bin/env python3
"""
补抓 9 只持仓股的 K 线：新增 002779/301217 + 9 月 1-8 日增量（9 只）。
输出 cache/holdings_kline_20260908.json（独立文件，不动原 backtest_klines.json）。
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path("/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard")
OUT = ROOT / "cache" / "holdings_kline_20260908.json"

CODES = ["002779","301217","601606","300223","003033","300499","300579","600664","601138"]

def mkt_prefix(code):
    """市场前缀：6→sh, 8/4/43/92→bj, 5→sh(基金), 9→bj, 0/2/3→sz"""
    if code.startswith(("6","5")): return "sh"
    if code.startswith(("8","4","43","92")): return "bj"
    return "sz"

def fetch_kline(code, days=120):
    """腾讯 qt.gtimg.cn 抓日 K（前复权 fqkline）。
    URL: param=<sym>,day,,,<count>,qfq
    返回 data[sym].qfqday = [[date, open, close, high, low, volume], ...]"""
    pref = mkt_prefix(code)
    sym = f"{pref}{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{days},qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://gu.qq.com/"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        d = json.loads(raw)
        qfq = d.get("data", {}).get(sym, {}).get("qfqday", [])
        return [{"date":r[0],"open":float(r[1]),"close":float(r[2]),
                 "high":float(r[3]),"low":float(r[4]),"volume":float(r[5])} for r in qfq]
    except Exception as e:
        print(f"  ❌ {code} 失败: {e}", file=sys.stderr)
        return []

def main():
    out = {"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "codes": {}}
    for code in CODES:
        print(f"  → 抓 {code} ...", end=" ", flush=True)
        k = fetch_kline(code, days=180)  # 半年+ 数据
        if k:
            print(f"✅ {len(k)} 根  ({k[0]['date']} ~ {k[-1]['date']})  last_close={k[-1]['close']:.2f}")
            out["codes"][code] = {"kline": k, "last_date": k[-1]["date"], "last_close": k[-1]["close"]}
        else:
            print(f"❌")
        time.sleep(0.2)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✅ 落盘 {OUT}")

if __name__ == "__main__":
    main()