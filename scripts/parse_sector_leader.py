#!/usr/bin/env python3
"""Parse Desktop 板块/A股 TSV files into dashboard data source (sector_leader_data.json)."""
import json, os, datetime
import pandas as pd

SECTOR_SRC = "/Users/sky/Desktop/Table-板块.xls"
ASTOCK_SRC = "/Users/sky/Desktop/Tabl-A股e.xls"
OUT = "/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard/cache/sector_leader_data.json"

def parse(path, cols):
    df = pd.read_csv(path, sep="\t", encoding="gb18030", dtype=str)
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df

# ---------- Sector data ----------
sector_df = parse(SECTOR_SRC, ["板块名称","涨幅","主力金额","主力资金","涨停数","涨家数","跌家数","领涨股","5日涨幅","量比","总市值","流通市值","概念解析","10日涨幅","20日涨幅","年初至今"])

def to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("+", "").replace("%", "").strip()
    if s in ("", "--", "-", "None", "nan"):
        return None
    try:
        return float(s)
    except Exception:
        return None

sectors = []
for _, r in sector_df.iterrows():
    name = str(r.get("板块名称", "")).strip()
    if not name:
        continue
    sectors.append({
        "name": name,
        "chg": to_num(r.get("涨幅")),            # 涨幅 %
        "main_amount": to_num(r.get("主力金额")),  # 主力净额(元) — 排序依据
        "main_fund": to_num(r.get("主力资金")),
        "limit_up": to_num(r.get("涨停数")),
        "up_count": to_num(r.get("涨家数")),
        "down_count": to_num(r.get("跌家数")),
        "leader": str(r.get("领涨股", "") or "").strip() or "—",
        "chg5d": to_num(r.get("5日涨幅")),
        "chg10d": to_num(r.get("10日涨幅")),
        "chg20d": to_num(r.get("20日涨幅")),
        "vol_ratio": to_num(r.get("量比")),
        "float_cap": to_num(r.get("流通市值")),
        "total_cap": to_num(r.get("总市值")),
        "concept": str(r.get("概念解析", "") or "").strip(),
    })

def sort_key(x):
    v = x.get("main_amount")
    return v if v is not None else 0

sectors_sorted = sorted(sectors, key=sort_key, reverse=True)
top_in = [s for s in sectors_sorted[:30] if (s["main_amount"] or 0) >= 0]
top_out = [s for s in sectors_sorted[::-1][:30] if (s["main_amount"] or 0) < 0]
# 保证各 30：若不足，从中间补
if len(top_in) < 30:
    top_in = sectors_sorted[:30]
if len(top_out) < 30:
    bottom = [s for s in sectors_sorted if (s["main_amount"] or 0) < 0]
    top_out = bottom[:30]

# ---------- A-share data ----------
a_df = parse(ASTOCK_SRC, ["代码","名称","涨幅","现价","量比","所属行业","换手%","金额","总市值","流通市值","市盈(动)","市净率","涨跌","最高","最低","开盘","昨收","笔数"])
a_stocks = []
for _, r in a_df.iterrows():
    code = str(r.get("代码", "")).strip()
    name = str(r.get("名称", "")).strip()
    if not code or not name:
        continue
    a_stocks.append({
        "code": code,
        "name": name,
        "chg": to_num(r.get("涨幅")),
        "price": to_num(r.get("现价")),
        "vol_ratio": to_num(r.get("量比")),
        "industry": str(r.get("所属行业", "") or "").strip(),
        "turnover": to_num(r.get("换手%")),
        "amount": to_num(r.get("金额")),
        "pe": to_num(r.get("市盈(动)")),
        "pb": to_num(r.get("市净率")),
        "float_cap": to_num(r.get("流通市值")),
        "total_cap": to_num(r.get("总市值")),
    })

# Build name->stock lookup for enriching leader codes
name2stock = {s["name"]: s for s in a_stocks if s["name"]}
for s in sectors:
    leader = s["leader"]
    if leader and leader in name2stock:
        ls = name2stock[leader]
        s["leader_code"] = ls["code"]
        s["leader_price"] = ls["price"]
        s["leader_chg"] = ls["chg"]
    else:
        s["leader_code"] = None
        s["leader_price"] = None
        s["leader_chg"] = None

data = {
    "updated_at": datetime.datetime.now().isoformat(),
    "source": "Desktop/Table-板块.xls + Desktop/Tabl-A股e.xls (同花顺/东财 TSV 导出)",
    "sector_count": len(sectors),
    "astock_count": len(a_stocks),
    "top_inflow": top_in,
    "top_outflow": top_out,
    "astocks": a_stocks,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(data, f, ensure_ascii=False)

print("sectors:", len(sectors))
print("astocks:", len(a_stocks))
print("top_inflow:", len(top_in), "top_outflow:", len(top_out))
print("top_in first:", [(s["name"], s["main_amount"]) for s in top_in[:5]])
print("top_out first:", [(s["name"], s["main_amount"]) for s in top_out[:5]])
print("OUT size:", os.path.getsize(OUT), "bytes")
