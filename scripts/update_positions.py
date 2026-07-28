#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓盈亏快照更新工具（券商后台口径）

用途：
    把「来源券商后台导出的权威持仓盈亏」写入 cache/holdings.json，
    并重建 index.html。看板在检测到 holdings.json 含 account_pnl 时会：
      1) 跳过自动合并（不会用交割单覆盖快照）；
      2) 持仓行直接用快照里的 总盈亏/盈亏%/当日盈亏 覆盖实时行情计算；
      3) 分账户汇总使用 account_pnl（账户总额含已平仓盈亏，≠个股市值之和）。

输入格式（JSON，默认 data/positions_spec.json，可用 -s 指定）：
{
  "date": "2026-07-28",
  "accounts": {
    "galaxy": {
      "summary": {"today": 4628, "today_pct": 4.82, "total": -24719.82, "pct": 30.66},
      "positions": [
        {"code":"003033","name":"征和工业","quantity":100,"avg_cost":51.745,
         "pnl":{"total":1051.52,"pct":20.321,"today":503,"today_pct":2.602}}
      ]
    },
    "eastmoney": {
      "summary": {"today": 36442.51, "today_pct": 6.82, "total": 86009.22, "pct": 71.6},
      "positions": [
        {"code":"003033","name":"征和工业","quantity":500,"avg_cost":32.326,
         "pnl":{"total":14966.87,"pct":92.6,"today":1085,"today_pct":3.368}},
        {"code":"300223","name":"北京君正","quantity":2500,"avg_cost":143.507,
         "pnl":{"total":41018.72,"pct":11.433,"today":30537.98,"today_pct":8.768}}
      ]
    },
    "csc": {
      "summary": {"today": null, "today_pct": null, "total": 21933.29, "pct": 6.99},
      "positions": []   // 仅账户级盈亏、无个股明细时留空
    }
  }
}

说明：
  - pnl.total / pct / today / today_pct 直接取自券商后台；
  - 现价 price 若未给出，则按  avg_cost + total/quantity  推算（负成本也成立）；
  - 账户级 summary 必填（即使 positions 为空，如中信建投只有账户盈亏）；
  - 未列出的账户请保留 {"summary": {...}, "positions": []} 占位。

用法：
    python scripts/update_positions.py [-s data/positions_spec.json] [--no-build]
"""
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ACCOUNT_LABELS = {"galaxy": "银河证券", "eastmoney": "东方财富", "csc": "中信建投"}


def derive_price(avg_cost, total, qty):
    """现价 = 成本 + 总盈亏/数量（负成本同样成立）。"""
    try:
        if qty and float(qty) > 0:
            return round(float(avg_cost) + float(total) / float(qty), 4)
    except Exception:
        pass
    return None


def build_holdings(spec):
    date = spec.get("date") or datetime.now().strftime("%Y-%m-%d")
    updated_at = f"{date} {datetime.now().strftime('%H:%M:%S')}"
    accounts = {}
    positions = []
    account_pnl = {}
    for acc_key in ("galaxy", "eastmoney", "csc"):
        ad = (spec.get("accounts") or {}).get(acc_key) or {}
        summary = ad.get("summary") or {}
        acc_positions = []
        for p in (ad.get("positions") or []):
            qty = p.get("quantity")
            cost = p.get("avg_cost")
            pnl = dict(p.get("pnl") or {})
            # 补全现价
            if pnl.get("price") is None:
                pnl["price"] = derive_price(cost, pnl.get("total"), qty)
            acc_positions.append({
                "code": p.get("code"),
                "name": p.get("name"),
                "account": acc_key,
                "quantity": qty,
                "avg_cost": cost,
                "pnl": pnl,
            })
            positions.append({
                "code": p.get("code"),
                "name": p.get("name"),
                "account": acc_key,
                "quantity": qty,
                "avg_cost": cost,
                "pnl": pnl,
            })
        accounts[acc_key] = acc_positions
        account_pnl[acc_key] = {
            "today": summary.get("today"),
            "today_pct": summary.get("today_pct"),
            "total": summary.get("total"),
            "pct": summary.get("pct"),
        }
    return {
        "source": f"broker_pnl_snapshot_{date}",
        "updated_at": updated_at,
        "note": "权威盈亏快照：成本/现价/盈亏均以来源券商后台口径，含分红与已平仓盈亏；"
                "账户级总额含已平仓盈亏，不等于个股市值之和。后续每日据此更新。",
        "account_labels": ACCOUNT_LABELS,
        "account_pnl": account_pnl,
        "accounts": accounts,
        "positions": positions,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-s", "--spec", default=os.path.join(ROOT, "data", "positions_spec.json"))
    ap.add_argument("--no-build", action="store_true", help="只写 holdings.json，不重建 index.html")
    args = ap.parse_args()

    if not os.path.exists(args.spec):
        print(f"[error] 找不到规格文件: {args.spec}")
        sys.exit(1)
    spec = json.load(open(args.spec, encoding="utf-8"))
    holdings = build_holdings(spec)

    out_path = os.path.join(ROOT, "cache", "holdings.json")
    json.dump(holdings, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[ok] 写入 {out_path}（{len(holdings['positions'])} 只个股，3 个账户）")

    if args.no_build:
        print("[skip] 已跳过看板重建")
        return
    sys.path.insert(0, HERE)
    try:
        import build_dashboard
        build_dashboard.build()
        print("[ok] 看板已重建 index.html（含账户_pnl 快照模式）")
    except Exception as e:
        print(f"[warn] 看板重建失败: {e}（holdings.json 已更新，可稍后手动构建）")


if __name__ == "__main__":
    main()
