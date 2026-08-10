#!/usr/bin/env python3
"""将 westock data_kline API 响应转换为 backtest_klines.json 格式"""
import json, os, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))

# 股票映射: ts_code -> (code, name, full_code)
STOCK_MAP = {
    "sh603776": ("603776", "永安行", "sh603776"),
    "sz002747": ("002747", "埃斯顿", "sz002747"),
    "sz300223": ("300223", "北京君正", "sz300223"),
    "sh600664": ("600664", "哈药股份", "sh600664"),
    "sz003033": ("003033", "征和工业", "sz003033"),
    "sz003032": ("003032", "传智教育", "sz003032"),
    "sz002230": ("002230", "科大讯飞", "sz002230"),
}

# 读取 API 响应
api_file = os.path.join(HERE, "_kline_raw.json")
with open(api_file, encoding="utf-8") as f:
    raw = json.load(f)

stocks = {}
for item in raw["data"]["data"]:
    sym = item["symbol"]
    if sym not in STOCK_MAP:
        continue
    code, name, full_code = STOCK_MAP[sym]
    nodes = item["data"]["nodes"]
    # 转换格式: [date, open, close, high, low, volume]
    kline = []
    for n in nodes:
        kline.append([
            n["date"],
            n["open"],
            n["last"],   # close
            n["high"],
            n["low"],
            n["volume"],
        ])
    # 反转为正序（旧 -> 新）
    kline.reverse()
    stocks[code] = {
        "name": name,
        "full_code": full_code,
        "kline": kline,
    }

out = {
    "updated_at": dt.datetime.now().isoformat() + "+08:00",
    "days": 500,
    "stocks": stocks,
}

out_path = os.path.join(os.path.dirname(HERE), "cache", "backtest_klines.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"[ok] 写入 {out_path}")
print(f"     {len(stocks)} 只股票")
for code, s in stocks.items():
    closes = [x[2] for x in s["kline"]]
    print(f"     {s['name']}({code}): {len(s['kline'])}根K线, 最新收盘={closes[-1]}")
