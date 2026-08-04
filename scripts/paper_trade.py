#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地模拟交易 CLI（paper trading）

数据文件: cache/paper_trades.json
用法示例:
  python scripts/paper_trade.py buy 300308 中际旭创 185.20 100 "8/4备选池-算力硬件低吸"
  python scripts/paper_trade.py sell 300308 192.50 100 "部分止盈"
  python scripts/paper_trade.py mark 300308 188.30          # 更新标记价(用于盈亏计算)
  python scripts/paper_trade.py refresh                       # 调 westock-data 拉真实价更新标记价
  python scripts/paper_trade.py status                        # 持仓盈亏 + 总资产
  python scripts/paper_trade.py list                          # 交易流水
  python scripts/paper_trade.py reset --yes                   # 清空重置

buy/sell 后会自动重建看板(python scripts/build_full.py)，无需手动刷新。
所有数值四舍五入保留 2 位。盈亏百分比: 正成本用 (现价-成本)/成本；负成本(已分红/做T)
用 市值收益率 = 浮动盈亏 / 当前市值。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "cache")
DB = os.path.join(CACHE, "paper_trades.json")
BUILD = os.path.join(ROOT, "scripts", "build_full.py")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _round(x, n=2):
    try:
        return round(float(x), n)
    except Exception:
        return 0.0


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", ""))
    except Exception:
        return 0.0


def load():
    if not os.path.exists(DB):
        return {"meta": {"init_cash": 1000000, "cash": 1000000, "base": "CNY",
                          "created_at": _now(), "updated_at": _now(),
                          "note": "本地模拟交易账户"},
                "trades": [], "positions": []}
    with open(DB, encoding="utf-8") as f:
        return json.load(f)


def save(d):
    d["meta"]["updated_at"] = _now()
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _rebuild():
    """模拟交易变动后重建看板。失败不影响数据。"""
    try:
        subprocess.run([sys.executable, BUILD], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[OK] 看板已重建 (index.html)")
    except Exception as e:
        print(f"[!] 看板重建跳过: {e}（可稍后手动运行 python scripts/build_full.py）")


def _find_pos(d, code):
    for p in d["positions"]:
        if p["code"] == code:
            return p
    return None


def cmd_buy(d, args):
    code = args.code
    name = args.name or code
    price = _round(args.price)
    qty = int(args.qty)
    note = args.note or ""
    cost = price * qty
    if cost > d["meta"]["cash"] + 1e-6:
        print(f"[!] 现金不足: 需 {cost:.2f}, 可用 {d['meta']['cash']:.2f}")
        return
    pos = _find_pos(d, code)
    if pos:
        old_qty = pos["qty"]
        old_cost = pos["avg_cost"]
        new_qty = old_qty + qty
        pos["avg_cost"] = _round((old_cost * old_qty + price * qty) / new_qty)
        pos["qty"] = new_qty
    else:
        pos = {"code": code, "name": name, "qty": qty, "avg_cost": price,
               "open_ts": _now(), "last_price": price, "last_price_src": "open",
               "last_price_ts": _now()}
        d["positions"].append(pos)
    d["meta"]["cash"] = _round(d["meta"]["cash"] - cost)
    d["trades"].append({"id": len(d["trades"]) + 1, "action": "buy", "code": code,
                        "name": name, "price": price, "qty": qty, "ts": _now(), "note": note})
    save(d)
    print(f"[OK] 买入 {name}({code}) {qty}股 @ {price}  现金余额 {d['meta']['cash']:.2f}")
    _rebuild()


def cmd_sell(d, args):
    code = args.code
    price = _round(args.price)
    qty = int(args.qty)
    note = args.note or ""
    pos = _find_pos(d, code)
    if not pos:
        print(f"[!] 无 {code} 持仓，无法卖出")
        return
    if qty > pos["qty"]:
        print(f"[!] 卖出数量 {qty} 超过持仓 {pos['qty']}")
        return
    realized = _round((price - pos["avg_cost"]) * qty)
    pos["qty"] -= qty
    if pos["qty"] <= 0:
        d["positions"] = [p for p in d["positions"] if p["code"] != code]
    d["meta"]["cash"] = _round(d["meta"]["cash"] + price * qty)
    d["trades"].append({"id": len(d["trades"]) + 1, "action": "sell", "code": code,
                        "name": pos.get("name", code), "price": price, "qty": qty,
                        "realized_pnl": realized, "ts": _now(), "note": note})
    save(d)
    print(f"[OK] 卖出 {pos.get('name', code)}({code}) {qty}股 @ {price}  实现盈亏 {realized:+.2f}  现金余额 {d['meta']['cash']:.2f}")
    _rebuild()


def cmd_mark(d, args):
    pos = _find_pos(d, args.code)
    if not pos:
        print(f"[!] 无 {args.code} 持仓")
        return
    pos["last_price"] = _round(args.price)
    pos["last_price_src"] = "manual"
    pos["last_price_ts"] = _now()
    save(d)
    print(f"[OK] {pos.get('name', args.code)}({args.code}) 标记价 -> {pos['last_price']}")


def cmd_refresh(d, args):
    """调 westock-data CLI 拉真实行情更新全部持仓标记价。"""
    node = os.environ.get("NODE", "/Users/sky/.workbuddy/binaries/node/versions/22.22.2/bin/node")
    app = "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"
    candidates = [
        os.environ.get("WESTOCK_CLI", ""),
        app,
        os.path.expanduser("~/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"),
        "westock-data",
    ]
    ws = ""
    for c in candidates:
        if not c:
            continue
        if c == "westock-data" or os.path.exists(c):
            ws = c
            break
    if not ws:
        print("[!] 未找到 westock-data CLI。请设置环境变量 WESTOCK_CLI 指向 index.js，或用 `mark <code> <price>` 手动更新标记价")
        return
    updated = 0
    for p in d["positions"]:
        code = p["code"]
        sh = code if code.startswith("sh") or code.startswith("sz") else (
            "sh" + code if code.startswith("6") else "sz" + code)
        try:
            if ws == "westock-data":
                out = subprocess.run([ws, "quote", sh], capture_output=True, text=True, timeout=15)
            else:
                out = subprocess.run([node, ws, "quote", sh], capture_output=True, text=True, timeout=15)
            data = json.loads(out.stdout)
            price = _num(data.get("price") or data.get("最新价") or data.get("收盘价"))
            if price:
                p["last_price"] = _round(price)
                p["last_price_src"] = "realtime"
                p["last_price_ts"] = _now()
                updated += 1
        except Exception as e:
            print(f"[!] {code} 刷新失败: {e}")
    save(d)
    if updated:
        print(f"[OK] 刷新 {updated}/{len(d['positions'])} 个持仓标记价（来源 westock-data）")
        _rebuild()
    else:
        print("[!] 未刷新任何持仓（检查 westock-data 可用性或改用 mark）")


def _pos_pnl(p):
    qty = p["qty"]
    cost = p["avg_cost"]
    lp = p.get("last_price", cost)
    mv = _round(lp * qty)
    fp = _round((lp - cost) * qty)
    if cost > 0:
        pct = _round((lp / cost - 1) * 100, 2)
    else:
        pct = _round(fp / mv * 100, 2) if mv else 0.0
    return mv, fp, pct


def cmd_status(d, args):
    init = _num(d["meta"]["init_cash"])
    cash = _num(d["meta"]["cash"])
    mv_total = 0.0
    print(f"\n{'='*72}\n  本地模拟交易账户   (基准资金 {init:,.0f} {d['meta'].get('base','CNY')})\n{'='*72}")
    if not d["positions"]:
        print("  持仓: 暂无（用 `buy` 建仓）")
    else:
        print(f"  {'标的':<10}{'代码':<10}{'数量':>6}{'成本':>10}{'标记价':>10}{'市值':>12}{'浮动盈亏':>12}{'盈亏%':>9}")
        print("  " + "-" * 68)
        for p in d["positions"]:
            mv, fp, pct = _pos_pnl(p)
            mv_total += mv
            sign = "+" if fp >= 0 else ""
            psign = "+" if pct >= 0 else ""
            print(f"  {p.get('name',''):<10}{p['code']:<10}{p['qty']:>6}{p['avg_cost']:>10.2f}"
                  f"{p.get('last_price',p['avg_cost']):>10.2f}{mv:>12,.0f}{fp:>12,.0f}{psign}{pct:>7.2f}%")
    total_assets = cash + mv_total
    ret = _round((total_assets / init - 1) * 100, 2) if init else 0.0
    print("  " + "-" * 68)
    print(f"  可用现金: {cash:,.2f}   持仓市值: {mv_total:,.2f}   总资产: {total_assets:,.2f}")
    print(f"  总收益率: {('+' if ret>=0 else '')}{ret:.2f}%")
    print(f"  更新: {d['meta'].get('updated_at','')}")
    print("=" * 72 + "\n")


def cmd_list(d, args):
    if not d["trades"]:
        print("  暂无交易流水")
        return
    print(f"\n{'ID':>3}  {'方向':<4} {'代码':<10} {'名称':<10} {'价格':>10} {'数量':>6} {'实现盈亏':>12}  时间")
    print("  " + "-" * 70)
    for t in d["trades"]:
        rp = t.get("realized_pnl")
        rps = f"{rp:+,.0f}" if rp is not None else "  -"
        print(f"  {t['id']:>3}  {t['action']:<4} {t['code']:<10} {t.get('name',''):<10} "
              f"{t['price']:>10.2f} {t['qty']:>6} {rps:>12}  {t['ts']}")


def cmd_reset(d, args):
    if not args.yes:
        print("[!] 需加 --yes 确认清空所有模拟交易数据")
        return
    d2 = load()
    d2["meta"]["cash"] = _num(d2["meta"]["init_cash"])
    d2["trades"] = []
    d2["positions"] = []
    save(d2)
    print("[OK] 模拟交易账户已重置")
    _rebuild()


def main():
    ap = argparse.ArgumentParser(description="本地模拟交易 CLI")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("buy", help="模拟买入")
    b.add_argument("code"); b.add_argument("price", type=float)
    b.add_argument("qty", type=int); b.add_argument("name", nargs="?", default="")
    b.add_argument("--note", default=""); b.set_defaults(func=cmd_buy)

    s = sub.add_parser("sell", help="模拟卖出")
    s.add_argument("code"); s.add_argument("price", type=float)
    s.add_argument("qty", type=int); s.add_argument("--note", default=""); s.set_defaults(func=cmd_sell)

    m = sub.add_parser("mark", help="更新标记价")
    m.add_argument("code"); m.add_argument("price", type=float); m.set_defaults(func=cmd_mark)

    rf = sub.add_parser("refresh", help="拉真实行情更新标记价"); rf.set_defaults(func=cmd_refresh)
    st = sub.add_parser("status", help="账户概览"); st.set_defaults(func=cmd_status)
    ls = sub.add_parser("list", help="交易流水"); ls.set_defaults(func=cmd_list)
    rs = sub.add_parser("reset", help="重置账户"); rs.add_argument("--yes", action="store_true"); rs.set_defaults(func=cmd_reset)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    d = load()
    args.func(d, args)


if __name__ == "__main__":
    main()
