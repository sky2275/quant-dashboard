#!/usr/bin/env python3
"""
同步 cache/holdings.json 至 2026-09-08 用户券商实盘截图（9 只持仓）。
银河/东财/中信三账户拆分；君正股份两账户独立条目。
仓位档位：300223=long/15%（东财+中信）、其他=short/8%。
"""
import json
import shutil
from pathlib import Path

ROOT = Path("/Users/sky/WorkBuddy/2026-07-26-12-28-32/quant-dashboard")
HOLDINGS = ROOT / "cache" / "holdings.json"

# 三账户持仓（按用户 9/8 截图）
ACCOUNTS = {
    "galaxy": [   # 银河证券
        {"code": "002779", "name": "中坚科技", "quantity": 100,  "avg_cost": 81.650},
        {"code": "301217", "name": "铜冠铜箔", "quantity": 100,  "avg_cost": 107.450},
        {"code": "601606", "name": "长城军工", "quantity": 1000, "avg_cost": 34.634},
    ],
    "eastmoney": [  # 东方财富证券
        {"code": "300223", "name": "君正股份", "quantity": 1300, "avg_cost": 141.321},
    ],
    "csc": [  # 中信建投
        {"code": "300223", "name": "君正股份", "quantity": 700,  "avg_cost": 129.382},
        {"code": "003033", "name": "征和工业", "quantity": 500,  "avg_cost": 56.948},
        {"code": "300499", "name": "高澜股份", "quantity": 500,  "avg_cost": 32.170},
        {"code": "300579", "name": "数字认证", "quantity": 1000, "avg_cost": 22.877},
        {"code": "600664", "name": "哈药股份", "quantity": 3000, "avg_cost": 7.765},
        {"code": "601138", "name": "工业富联", "quantity": 800,  "avg_cost": 62.851},
    ],
}

BUCKET_CFG = {
    "300223": "long",    # 君正股份：长线，止损 15%
    "_default": "short", # 其它：短线，止损 8%
}

def main():
    # 备份（如调用方没备份过）
    bak = HOLDINGS.with_suffix(".json.bak.pre_20260908")
    if not bak.exists():
        shutil.copy2(HOLDINGS, bak)
        print(f"✅ 备份原 holdings.json → {bak.name}")

    # 构建 positions 列表（带 bucket / stop_loss_pct）
    positions = []
    for account, items in ACCOUNTS.items():
        for it in items:
            bucket = BUCKET_CFG.get(it["code"], BUCKET_CFG["_default"])
            stop_pct = {"short": 0.08, "mid": 0.12, "long": 0.15}[bucket]
            positions.append({
                **it,
                "account": account,
                "bucket": bucket,
                "stop_loss_pct": stop_pct,
            })

    out = {
        "source": "broker_statements",
        "updated_at": "2026-09-08 23:04:00",
        "note": "9/8 截图同步：通富微电(002156)/亨通光电(600487)已清仓；新增中坚科技/铜冠铜箔/长城军工（银河）、哈药股份（中信）；君正股份两账户合计 2000 股（长线）",
        "account_labels": {
            "galaxy": "银河证券",
            "eastmoney": "东方财富",
            "csc": "中信建投",
        },
        "accounts": ACCOUNTS,
        "positions": positions,
        "bucket_config": {
            "300223": {"bucket": "long", "stop_loss_pct": 0.15, "note": "君正股份两账户合并长线 15% 止损"},
            "_default": {"bucket": "short", "stop_loss_pct": 0.08, "note": "其余 8 只短线 8% 止损"},
        },
    }

    HOLDINGS.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"✅ 写入新 holdings.json：{len(positions)} 条持仓")
    print("   - 银河 3 只：中坚科技/铜冠铜箔/长城军工")
    print("   - 东财 1 只：君正股份 1300 股 @141.321")
    print("   - 中信 6 只：君正 700@129.382 + 征和/高澜/数字认证/哈药/工业富联")
    print(f"   - 总市值估算：")
    # 现价（按 9/8 收盘）
    px = {"002779":82.76,"301217":105.50,"601606":35.20,"300223":133.79,
          "003033":71.33,"300499":33.96,"300579":23.88,"600664":7.75,"601138":64.75}
    total_mv = 0; total_cost = 0
    for p in positions:
        q = p["quantity"]; c = p["avg_cost"]; cur = px.get(p["code"], 0)
        mv = q*cur; tc = q*c; total_mv += mv; total_cost += tc
        print(f"     {p['name']:8s} ({p['account']:9s}) {q:>5}股  成本{c:7.3f} 现价{cur:7.2f} 市值{mv:>10,.0f} 浮盈{(mv-tc):>+10,.0f}")
    print(f"   - 合计市值约 {total_mv:,.0f} 元 / 成本 {total_cost:,.0f} / 浮盈 {(total_mv-total_cost):+,.0f}（{(total_mv-total_cost)/total_cost*100:+.2f}%）")

if __name__ == "__main__":
    main()