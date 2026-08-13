#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
以腾讯自选股 watchlist（经 westock MCP 读取）为"当前实仓清单"的权威信号，
匹配回 cache/holdings.json 取 数量/成本/账户/止损，重建持仓文件。

用法（由自动化或手动调用）：
  python scripts/sync_tencent_watchlist.py "003033,000636,300285,600664,002156,002747,300223"
参数为腾讯自选股自选列表里的 6 位代码（逗号分隔）。

规则：
  - 仅保留 code 在 watchlist 中的持仓条目（accounts 与 positions 同步过滤）。
  - 成本/数量/账户/止损沿用原 holdings.json 中匹配条目。
  - 重新汇总 account_pnl（total / today）。
  - 若某 watchlist 代码在原 holdings.json 中不存在：暂跳过并告警（需手动补成本）。
"""
import json, sys, os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD = os.path.join(BASE, "cache", "holdings.json")

def main():
    if len(sys.argv) < 2:
        print("用法: sync_tencent_watchlist.py <逗号分隔6位代码>")
        sys.exit(1)
    wl = set(c.strip() for c in sys.argv[1].split(",") if c.strip())
    with open(HOLD, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_positions = data.get("positions", [])
    old_accounts = data.get("accounts", {})

    # 过滤 positions
    new_positions = [p for p in old_positions if p["code"] in wl]
    dropped = [p["name"] + "(" + p["code"] + ")" for p in old_positions if p["code"] not in wl]
    missing = [c for c in wl if not any(p["code"] == c for p in old_positions)]

    # 过滤 accounts（按 code 交集）
    new_accounts = {}
    for acc, arr in old_accounts.items():
        kept = [p for p in arr if p["code"] in wl]
        if kept:
            new_accounts[acc] = kept

    # 重新汇总 account_pnl
    new_ap = {}
    for acc, arr in new_accounts.items():
        tot = sum(p["pnl"]["total"] for p in arr if "pnl" in p)
        td = sum(p["pnl"]["today"] for p in arr if "pnl" in p)
        new_ap[acc] = {
            "today": round(td, 2),
            "today_pct": None,
            "total": round(tot, 2),
            "pct": None,
        }

    data["accounts"] = new_accounts
    data["positions"] = new_positions
    data["account_pnl"] = new_ap
    data["source"] = "tencent_watchlist_sync_" + datetime.now().strftime("%Y-%m-%d")
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["note"] = (
        "以腾讯自选股 watchlist 为当前实仓清单（经 westock MCP 读取），"
        "匹配回原 holdings 取 数量/成本/账户/止损 重建。"
        "已排除未列入自选的：" + (",".join(dropped) if dropped else "无")
        + "。成本/数量为最近一次人工口径，价格由 live.html 浏览器端实时拉取。"
    )

    with open(HOLD, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("同步完成 ->", HOLD)
    print("保留持仓:", len(new_positions), "只（来自", len(new_accounts), "个账户）")
    print("排除(未加入自选):", dropped if dropped else "无")
    print("自选中有但holdings缺失(需补成本):", missing if missing else "无")
    print("账户汇总:")
    for a, v in new_ap.items():
        print(f"  {a}: total={v['total']} today={v['today']}")

if __name__ == "__main__":
    main()
