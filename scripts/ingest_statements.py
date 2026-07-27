#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双券商交割单 → 合并持仓 (cache/holdings.json)

读取 data/statements/{galaxy,eastmoney}/*.csv，按 config/broker_maps.yaml 的列映射
归一化，按 (账号, 代码) 聚合买卖记录、还原当前持仓（数量 / 成本价），输出
cache/holdings.json。纯本地计算，不联网（避开沙箱行情限流），由 build_dashboard.py
在生成看板时调用并按账户展示、再补实时价与技术指标。

用法：
    python scripts/ingest_statements.py
build_dashboard.py 也会在生成时自动调用本模块（若 data/statements 下有 CSV）。
"""
import os
import sys
import csv
import glob
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml
import feed  # noqa: E402

REPO_ROOT = feed.REPO_ROOT
STATEMENT_DIR = os.path.join(REPO_ROOT, "data", "statements")
CACHE_DIR = feed.CACHE_DIR
MAP_PATH = os.path.join(REPO_ROOT, "config", "broker_maps.yaml")

ACCOUNT_LABELS = {"galaxy": "银河证券", "eastmoney": "东方财富"}


def _bj_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def _load_maps():
    if os.path.exists(MAP_PATH):
        try:
            return yaml.safe_load(open(MAP_PATH, encoding="utf-8")) or {}
        except Exception as e:
            print(f"[ingest] 读取 broker_maps.yaml 失败: {e}")
    return {}


def _parse_date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _num(s):
    if s is None:
        return 0.0
    s = str(s).replace(",", "").replace("%", "").replace(" ", "").strip()
    if s in ("", "-", "--", "None", "nan", "NaN"):
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _read_csv(path, enc):
    encodings = [enc, "utf-8-sig", "gb18030", "gbk", "utf-8"]
    seen = set()
    for e in encodings:
        if e in seen:
            continue
        seen.add(e)
        try:
            with open(path, encoding=e, errors="ignore", newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _side(row, m):
    raw = str(row.get(m.get("side"), "") or "")
    for k in m.get("buy_keywords", []):
        if k and k in raw:
            return "buy"
    for k in m.get("sell_keywords", []):
        if k and k in raw:
            return "sell"
    return "unknown"


def _fees(row, m):
    total = 0.0
    for col in (m.get("fees", []) or []):
        if col and col in row:
            total += _num(row.get(col))
    return total


def _aggregate(rows, m, account):
    """按 (代码) 聚合买卖，还原当前持仓。返回 [{code,name,account,quantity,avg_cost}]。"""
    pos = {}
    for r in rows:
        code = str(r.get(m.get("code"), "") or "").strip()
        name = str(r.get(m.get("name"), "") or "").strip()
        if not code and not name:
            continue
        side = _side(r, m)
        if side == "unknown":
            continue
        qty = abs(_num(r.get(m.get("qty"))))
        if qty <= 0:
            continue
        price = _num(r.get(m.get("price")))
        if price == 0:
            amt = _num(r.get(m.get("amount")))
            if amt > 0:
                price = amt / qty
        fee = _fees(r, m)
        key = code or name
        p = pos.setdefault(key, {"name": name, "code": code, "qty": 0.0, "cost": 0.0})
        if name:
            p["name"] = name
        if side == "buy":
            p["cost"] += price * qty + fee
            p["qty"] += qty
        else:
            avg = (p["cost"] / p["qty"]) if p["qty"] > 0 else price
            p["cost"] -= avg * qty
            p["qty"] -= qty
    out = []
    for key, p in pos.items():
        if p["qty"] > 0.5:  # 仍有持仓（A股整数股，留 0.5 容差）
            avg_cost = (p["cost"] / p["qty"]) if p["qty"] > 0 else 0.0
            out.append({
                "code": p["code"],
                "name": p["name"] or p["code"],
                "account": account,
                "quantity": int(round(p["qty"])),
                "avg_cost": round(avg_cost, 4),
            })
    out.sort(key=lambda x: (x["account"], x["name"]))
    return out


def build():
    maps = _load_maps()
    brokers = maps.get("brokers") or {}
    accounts = {}
    positions = []
    for acc, m in brokers.items():
        d = os.path.join(STATEMENT_DIR, acc)
        files = sorted(glob.glob(os.path.join(d, "*.csv"))) if os.path.isdir(d) else []
        rows = []
        for fp in files:
            rows += _read_csv(fp, m.get("encoding", "utf-8-sig"))
        if rows:
            acc_pos = _aggregate(rows, m, acc)
            accounts[acc] = acc_pos
            positions += acc_pos
    result = {
        "source": "broker_statements",
        "updated_at": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_labels": ACCOUNT_LABELS,
        "accounts": accounts,
        "positions": positions,
    }
    os.makedirs(CACHE_DIR, exist_ok=True)
    out_path = os.path.join(CACHE_DIR, "holdings.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[ingest] 合并持仓 {len(positions)} 只 "
          f"（银河 {len(accounts.get('galaxy', []))} / 东财 {len(accounts.get('eastmoney', []))}），"
          f"写入 {out_path}")
    return result


if __name__ == "__main__":
    build()
