#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
以腾讯自选股"模拟交易未成交委托"为意图持仓信号，重建 cache/holdings.json。

背景：portfolio_paper_positions 经常为空（委托未成交），但 portfolio_paper_history
能返回用户已录入的 buy 委托（含 price/quantity）。本脚本把 history 中状态为"未提交"
的买入委托聚合为持仓，写入 holdings.json，供 live.html 实时盯盘。

用法：
  python scripts/sync_tencent_paper.py
无需参数，直接调用 westock MCP portfolio_paper_history(range=recent)。

规则：
  - 仅取 direction=buy 且 status 包含"未提交"的记录。
  - 同 code 多笔委托按加权平均计算 avg_cost，quantity 累加。
  - 所有持仓统一 account='tencent'，stop=0.10。
  - 保留原 holdings.json 中同 code 的 name/bucket 信息（若存在），缺失则留空。
  - 价格字段置为 0，由 live.html 加载后自行拉取实时价；pnl 初始化为 0。
"""
import json, os, subprocess, re
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD = os.path.join(BASE, "cache", "holdings.json")

ACCOUNT_LABELS = {
    "tencent": "腾讯自选股（模拟交易）"
}

def call_mcp(tool_name, params=None):
    """通过 python 子进程调用 mcp 工具。这里用 westock-mcp 的 JSON-RPC 方式不现实，
    所以本脚本只负责数据转换；MCP 调用由外部（自动化）先做并把 JSON 通过 stdin 传入。"""
    raise NotImplementedError("本脚本需配合外部 MCP 调用使用；请用自动化包装。")


def build_from_records(records, old_data):
    """records: list of dict with code/name/direction/quantity/price/status"""
    buys = defaultdict(list)
    for r in records:
        if r.get("direction") != "buy":
            continue
        if "未提交" not in str(r.get("status", "")):
            continue
        code = re.sub(r"^(sh|sz|bj)", "", r.get("code", ""))
        if not code:
            continue
        try:
            q = int(str(r.get("quantity", "0")).replace(",", ""))
            p = float(str(r.get("price", "0")).replace(",", ""))
        except Exception:
            continue
        if q <= 0 or p <= 0:
            continue
        buys[code].append({"q": q, "p": p, "name": r.get("name", "")})

    old_positions = {p["code"]: p for p in old_data.get("positions", [])}

    positions = []
    for code, arr in buys.items():
        total_qty = sum(x["q"] for x in arr)
        total_cost = sum(x["q"] * x["p"] for x in arr)
        avg_cost = round(total_cost / total_qty, 3) if total_qty else 0
        old = old_positions.get(code, {})
        name = old.get("name") or arr[0].get("name") or ""
        positions.append({
            "code": code,
            "name": name,
            "account": "tencent",
            "quantity": total_qty,
            "avg_cost": avg_cost,
            "price": 0,
            "chg": 0,
            "pnl": {
                "total": 0,
                "pct": 0,
                "today": 0,
                "today_pct": 0,
                "price": 0
            },
            "bucket": old.get("bucket", "long"),
            "stop": old.get("stop", 0.10)
        })

    positions.sort(key=lambda x: x["code"])

    accounts = {"tencent": positions}
    account_pnl = {
        "tencent": {"today": 0, "today_pct": None, "total": 0, "pct": None}
    }

    return {
        "source": "tencent_paper_history_sync_" + datetime.now().strftime("%Y-%m-%d"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": (
            "以腾讯自选股模拟交易未成交委托为意图持仓（经 westock MCP portfolio_paper_history 读取），"
            "同代码多笔委托按加权平均合并成本。价格/盈亏由 live.html 浏览器端实时拉取后计算。"
        ),
        "account_labels": ACCOUNT_LABELS,
        "account_pnl": account_pnl,
        "accounts": accounts,
        "positions": positions
    }


def main():
    """支持两种输入：
    1) 命令行传入 JSON 文件路径（含 records 数组）
    2) 命令行传入逗号分隔的 code,name,qty,price;... 简串（用于测试）
    """
    old_data = {}
    if os.path.exists(HOLD):
        with open(HOLD, "r", encoding="utf-8") as f:
            old_data = json.load(f)

    if len(sys.argv) < 2:
        print("用法: sync_tencent_paper.py <records.json>")
        print("  records.json 结构: {'records': [{'code':'sz300223','name':'君正股份','direction':'buy','quantity':1700,'price':142.96,'status':'未提交'}, ...]}")
        sys.exit(1)

    arg = sys.argv[1]
    if os.path.isfile(arg):
        with open(arg, "r", encoding="utf-8") as f:
            payload = json.load(f)
        records = payload.get("records", payload if isinstance(payload, list) else [])
    else:
        # 简串格式: code:name:qty:price;...
        records = []
        for seg in arg.split(";"):
            parts = seg.split(":")
            if len(parts) >= 4:
                records.append({
                    "code": parts[0],
                    "name": parts[1] if len(parts) > 1 else "",
                    "direction": "buy",
                    "quantity": parts[2],
                    "price": parts[3],
                    "status": "未提交"
                })

    new_data = build_from_records(records, old_data)

    with open(HOLD, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print("同步完成 ->", HOLD)
    print("模拟委托持仓:", len(new_data["positions"]), "只")
    for p in new_data["positions"]:
        print(f"  {p['code']} {p['name']} qty={p['quantity']} avg_cost={p['avg_cost']}")


if __name__ == "__main__":
    import sys
    main()
