#!/usr/bin/env python3
"""
同步 9/10 实盘持仓到 cache/holdings.json
依据：用户截图 + 中信建投明细 + 银河证券 + 东方财富
- 备份旧 holdings.json → cache/holdings.json.bak.YYYYMMDD_HHMM
- 全仓 list 覆盖（13 条：中坚+铜冠+长城 / 征和+数字+高澜+广汇+哈药+新安+工业富联+君正中信+君正东财）
- bucket/stop 仍走 holdings_buckets.json 配置（除非内联 stop）
"""
import json, shutil, sys
from pathlib import Path
from datetime import datetime

ROOT = Path("/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard")
HOLD = ROOT / "cache" / "holdings.json"
BUCKET = ROOT / "config" / "holdings_buckets.json"

NOW = datetime.now().strftime("%Y%m%d_%H%M")
BAK = HOLD.parent / f"holdings.json.bak.{NOW}"

# 备份
if HOLD.exists():
    shutil.copy2(HOLD, BAK)
    print(f"[backup] {HOLD.name} → {BAK.name}")

# 读 bucket 配置（归属+内联 stop）
with open(BUCKET) as f:
    cfg = json.load(f)
cfg_stocks = {s["code"]: s for s in cfg.get("stocks", [])}

# 用户截图原始持仓 (3 账户)
# 9/10 收盘实盘
positions = [
    # === 银河证券 ===
    {"account": "银河证券", "code": "002779", "name": "中坚科技",   "quantity": 200,  "avg_cost": 81.820,  "current_price": 81.650},
    {"account": "银河证券", "code": "301217", "name": "铜冠铜箔",   "quantity": 100,  "avg_cost": 107.450, "current_price": 108.450},
    {"account": "银河证券", "code": "601606", "name": "长城军工",   "quantity": 1000, "avg_cost": 34.305,  "current_price": 34.490},
    # === 东方财富证券 ===
    {"account": "东方财富", "code": "300223", "name": "君正集团",   "quantity": 1300, "avg_cost": 141.321, "current_price": 132.450},
    # === 中信建投 ===
    {"account": "中信建投", "code": "003033", "name": "征和工业",   "quantity": 500,  "avg_cost": 55.968,  "current_price": 74.460},
    {"account": "中信建投", "code": "300223", "name": "君正股份",   "quantity": 700,  "avg_cost": 129.382, "current_price": 132.450},
    {"account": "中信建投", "code": "300499", "name": "高澜股份",   "quantity": 200,  "avg_cost": 24.528,  "current_price": 36.530},
    {"account": "中信建投", "code": "300579", "name": "数字认证",   "quantity": 1000, "avg_cost": 22.877,  "current_price": 23.030},
    {"account": "中信建投", "code": "600256", "name": "广汇能源",   "quantity": 2000, "avg_cost": 7.473,   "current_price": 7.190},
    {"account": "中信建投", "code": "600596", "name": "新安股份",   "quantity": 1000, "avg_cost": 12.105,  "current_price": 12.020},
    {"account": "中信建投", "code": "600664", "name": "哈药股份",   "quantity": 4000, "avg_cost": 7.571,   "current_price": 7.130},
    {"account": "中信建投", "code": "601138", "name": "工业富联",   "quantity": 1000, "avg_cost": 63.186,  "current_price": 63.910},
]

# 9/10 当日盈亏（用户原话）
intraday_pnl = {
    "002779": -34.00,   # 中坚科技
    "301217": 100.00,   # 铜冠铜箔
    "601606": 184.76,   # 长城军工
    "300223_dfzq": 611.00,  # 君正集团（东财）
    "003033": -166.00,  # 征和工业
    "300223": 329.00,   # 君正股份（中信）
    "300499": 86.00,    # 高澜股份
    "300579": -350.00,  # 数字认证
    "600256": -565.15,  # 广汇能源
    "600596": -85.12,   # 新安股份
    "600664": -1540.00, # 哈药股份
    "601138": -1182.00, # 工业富联
}

# 填充 bucket / stop_loss_pct
for p in positions:
    code = p["code"]
    cfg_row = cfg_stocks.get(code, {})
    p["bucket"] = cfg_row.get("bucket", "short")
    p["stop_loss_pct"] = cfg_row.get("stop_loss_pct", 0.08)
    # 计算浮盈 & 盈亏比
    market_value = p["quantity"] * p["current_price"]
    cost_value = p["quantity"] * p["avg_cost"]
    p["market_value"] = round(market_value, 2)
    p["cost_value"] = round(cost_value, 2)
    p["pnl"] = round(market_value - cost_value, 2)
    p["pnl_pct"] = round((p["current_price"] / p["avg_cost"] - 1) * 100, 2)
    # 标记三仓
    p["tier"] = p["bucket"]

# 聚合汇总
total_market = sum(p["market_value"] for p in positions)
total_cost = sum(p["cost_value"] for p in positions)
total_pnl = total_market - total_cost
total_intraday = sum(intraday_pnl.values())  # 实际 9/10 损益（含君正两账户）

# 9/10 全账户数据
today_pnl = -676 + 611 + (-3988.15)  # 银河-676 + 东财+611 + 中信-3988.15

data = {
    "asof_date": "2026-09-10",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "accounts": ["银河证券", "东方财富", "中信建投"],
    "positions": positions,
    "summary": {
        "total_market_value": round(total_market, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / total_cost * 100, 2),
        "today_pnl": round(today_pnl, 2),
        "today_pnl_galaxy": -676,
        "today_pnl_dfzq": 611,
        "today_pnl_zhongxin": -3988.15,
        "stock_count": len(positions),
        "long_count": sum(1 for p in positions if p["bucket"] == "long"),
        "short_count": sum(1 for p in positions if p["bucket"] == "short"),
    },
    "intraday_pnl": intraday_pnl,
    "backup_file": str(BAK.name) if BAK.exists() else None,
    "notes": "9/10 实盘持仓同步；备份前 holdings.json 仅含 9/8 旧持仓，已被本次覆盖写入新版本",
}

with open(HOLD, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"[write] {HOLD}")
print(f"  持仓数: {len(positions)}  市场价值: ¥{total_market:,.0f}  浮盈: ¥{total_pnl:,.0f} ({data['summary']['total_pnl_pct']}%)")
print(f"  9/10 当日损益: ¥{today_pnl:,.2f}  (银河 -676 + 东财 +611 + 中信 -3988.15)")
print(f"  backup: {BAK.name}")
