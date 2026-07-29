"""
fetch_backtest_klines.py —— 批量获取回测用日K线数据

数据来源：腾讯行情 web.ifzq.gtimg.cn（前复权日K）
覆盖范围：当前持仓股 + 最新每日备选池（scan_1430）+ 策略攻击池（attack_pool）
输出：cache/backtest_klines.json
"""
from __future__ import annotations

import os
import sys
import json
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402
import build_dashboard as bd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
CFG_PATH = os.path.join(REPO_ROOT, "config", "strategy.yaml")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _full_code(code: str) -> str:
    s = str(code).strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if len(s) != 6 or not s.isdigit():
        return ""
    if s.startswith("6"):
        return f"sh{s}"
    if s[:2] in ("00", "30", "39"):
        return f"sz{s}"
    if s[:1] in ("8", "4"):
        return f"bj{s}"
    return f"sh{s}"


def fetch_kline(full_code: str, days: int = 120) -> list:
    """
    获取腾讯前复权日K。返回 [[date, open, close, low, high, volume], ...] 旧→新。
    """
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,,,{days},qfq"
    try:
        r = requests.get(url, headers=UA, timeout=20)
        data = r.json()
        arr = data.get("data", {}).get(full_code, {}).get("qfqday", [])
        out = []
        for row in arr:
            if len(row) >= 6:
                out.append([
                    row[0],
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ])
        return out
    except Exception as e:
        print(f"[kline] {full_code} 获取失败: {e}")
        return []


def _load_yaml(path: str):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def main():
    targets: dict[str, str] = {}  # code -> name

    # 1) 持仓股
    holdings = feed._load("holdings") or {}
    for pos in holdings.get("positions", []):
        code = pos.get("code")
        name = pos.get("name")
        if code and name:
            targets[code] = name

    # 2) 最新每日备选池
    for key in ("scan_1430", "scan_0926"):
        scan = feed._load(key)
        if scan:
            for s in scan.get("stocks", []):
                code = s.get("code")
                name = s.get("name")
                if code and name:
                    targets[code] = name

    # 3) 策略攻击池
    cfg = _load_yaml(CFG_PATH)
    name_code = bd.NAME_CODE
    for name in cfg.get("attack_pool", []):
        code = name_code.get(name)
        if code:
            targets[code.replace("sh", "").replace("sz", "")] = name

    if not targets:
        print("[kline] 无目标股票")
        return

    print(f"[kline] 共 {len(targets)} 只标的待获取")
    out = {"updated_at": feed.beijing_now().isoformat(), "stocks": {}}
    for code, name in targets.items():
        full = _full_code(code)
        if not full:
            continue
        kline = fetch_kline(full, 120)
        if kline:
            out["stocks"][code] = {
                "name": name,
                "full_code": full,
                "kline": kline,
            }
            print(f"[kline] {code} {name}: {len(kline)} 天")
        time.sleep(0.15)  # 礼貌限速

    out["count"] = len(out["stocks"])
    out_path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[kline] 已保存 {out_path}，共 {out['count']} 只")


if __name__ == "__main__":
    main()
