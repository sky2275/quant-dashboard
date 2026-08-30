#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双券商交割单 → 合并持仓 (cache/holdings.json)

读取 data/statements/{galaxy,eastmoney} 下的交割单文件，支持格式：
  - CSV        (.csv)
  - Excel      (.xls / .xlsx，银河海王星多为 .xls，东财多为 .xlsx)
按 config/broker_maps.yaml 的列映射归一化，按 (账号, 代码) 聚合买卖记录、
还原当前持仓（数量 / 成本价），输出 cache/holdings.json。纯本地计算，不联网
（避开沙箱行情限流），由 build_dashboard.py 在生成看板时调用并按账户展示、
再补实时价与技术指标。

用法：
    python scripts/ingest_statements.py
build_dashboard.py 也会在生成时自动调用本模块（若 data/statements 下有交割单）。
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

ACCOUNT_LABELS = {"galaxy": "银河证券", "eastmoney": "东方财富", "csc": "中信建投"}


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


def _read_excel(path):
    """读取 .xls / .xlsx 交割单，返回 [ {列名: 字符串值}, ... ]。"""
    try:
        import pandas as pd
    except Exception as e:
        print(f"[ingest] 缺少 pandas，无法解析 Excel({path}): {e}")
        return []
    try:
        df = pd.read_excel(path, header=0)
    except Exception as e:
        print(f"[ingest] read_excel 失败({path}): {e}")
        return []
    df = df.fillna("")
    rows = []
    for rec in df.to_dict(orient="records"):
        rows.append({str(k): ("" if v is None else str(v)) for k, v in rec.items()})
    return [] if not rows else rows


def _read_tsv(path):
    """读取 GBK 制表符分隔的文本文件（部分券商导出 .xls 实为 TSV）。
    返回 [ {列名: 字符串值}, ... ]。首行作为表头。"""
    try:
        raw = open(path, "rb").read()
    except Exception as e:
        print(f"[ingest] 读取失败({path}): {e}")
        return []
    txt = None
    for enc in ("gb18030", "gbk", "utf-8-sig", "utf-8"):
        try:
            txt = raw.decode(enc)
            break
        except Exception:
            continue
    if txt is None:
        txt = raw.decode("latin-1", errors="ignore")
    lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
    if len(lines) < 2:
        return []
    hdr = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for ln in lines[1:]:
        cols = ln.split("\t")
        if len(cols) < len(hdr):
            cols += [""] * (len(hdr) - len(cols))
        rows.append({hdr[i]: (cols[i].strip() if i < len(cols) else "") for i in range(len(hdr))})
    return rows


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


def _extract_trades(rows, m, account):
    """提取每一笔买卖的原始记录（含已清仓股），用于历史交易回测。

    与 _aggregate 不同：这里不聚合成当前持仓，而是保留逐笔 buy/sell
    的日期/代码/方向/数量/价格/金额/费用，输出到 cache/trades_history.json。
    """
    trades = []
    for r in rows:
        code = str(r.get(m.get("code"), "") or "").strip()
        name = str(r.get(m.get("name"), "") or "").strip()
        if not code and not name:
            continue
        side = _side(r, m)
        if side not in ("buy", "sell"):
            continue
        qty = abs(_num(r.get(m.get("qty"))))
        if qty <= 0:
            continue
        price = _num(r.get(m.get("price")))
        if price == 0:
            amt = _num(r.get(m.get("amount")))
            if amt > 0:
                price = amt / qty
        amt = _num(r.get(m.get("amount")))
        if amt <= 0:
            amt = price * qty
        fee = _fees(r, m)
        dt = _parse_date(r.get(m.get("date")))
        trades.append({
            "date": dt.strftime("%Y-%m-%d") if dt else "",
            "code": code,
            "name": name,
            "account": account,
            "side": side,           # buy / sell
            "qty": int(round(qty)),
            "price": round(price, 4),
            "amount": round(amt, 2),
            "fees": round(fee, 2),
        })
    trades.sort(key=lambda t: (t["date"], t["code"], t["side"]))
    return trades


def build():
    maps = _load_maps()
    brokers = maps.get("brokers") or {}
    accounts = {}
    positions = []
    all_trades = []
    found_any = False
    for acc, m in brokers.items():
        d = os.path.join(STATEMENT_DIR, acc)
        files = []
        if os.path.isdir(d):
            for pat in ("*.csv", "*.CSV", "*.xls", "*.XLS", "*.xlsx", "*.XLSX"):
                files += sorted(glob.glob(os.path.join(d, pat)))
        if files:
            found_any = True
        rows = []
        for fp in files:
            low = fp.lower()
            if low.endswith(".csv"):
                rows += _read_csv(fp, m.get("encoding", "utf-8-sig"))
            else:
                r = _read_excel(fp)
                if not r:
                    r = _read_tsv(fp)
                rows += r
        if rows:
            acc_pos = _aggregate(rows, m, acc)
            acc_trades = _extract_trades(rows, m, acc)
            accounts[acc] = acc_pos
            positions += acc_pos
            all_trades += acc_trades
    # 未检测到任何交割单文件（如云端仓库未含原始文件）：保留现有 holdings.json，避免清空
    if not found_any:
        existing = os.path.join(CACHE_DIR, "holdings.json")
        if os.path.exists(existing):
            print("[ingest] 未检测到交割单文件，保留现有 holdings.json（不覆盖）")
            return json.load(open(existing, encoding="utf-8"))
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

    # 逐笔买卖点历史（含已清仓股）→ cache/trades_history.json，供历史交易回测
    trades_result = {
        "source": "broker_statements",
        "updated_at": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_labels": ACCOUNT_LABELS,
        "trades": all_trades,
        "summary": {
            "total_trades": len(all_trades),
            "buy_count": sum(1 for t in all_trades if t["side"] == "buy"),
            "sell_count": sum(1 for t in all_trades if t["side"] == "sell"),
            "distinct_codes": sorted({t["code"] for t in all_trades if t["code"]}),
        },
    }
    trades_path = os.path.join(CACHE_DIR, "trades_history.json")
    with open(trades_path, "w", encoding="utf-8") as f:
        json.dump(trades_result, f, ensure_ascii=False, indent=2)
    print(f"[ingest] 逐笔买卖点 {len(all_trades)} 笔（买 {trades_result['summary']['buy_count']} / "
          f"卖 {trades_result['summary']['sell_count']}），写入 {trades_path}")

    print(f"[ingest] 合并持仓 {len(positions)} 只 "
          f"（银河 {len(accounts.get('galaxy', []))} / 东财 {len(accounts.get('eastmoney', []))}），"
          f"写入 {out_path}")
    return result


if __name__ == "__main__":
    build()
