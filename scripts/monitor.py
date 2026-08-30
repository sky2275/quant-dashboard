#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py — 实时变化检测引擎（Phase 1）
================================================
职责：轮询「持仓 + 自选池」的实时行情，检测量价异动，输出异动事件流。

数据源：腾讯 qt.gtimg.cn（秒级实时，含量比/换手/成交额/高低价）
输出：cache/live_events.json（供看板「实时异动」模块 + signal.py 消费）

异动类型：
  - 放量异动  量比 >= 2.0（成交量突然放大）
  - 急拉      当日涨幅 >= 5%
  - 急跌      当日跌幅 <= -5%
  - 突破      现价 >= 20 日最高（站上平台）
  - 高换手    换手率 >= 15%（筹码剧烈交换）
  - 触止损    现价跌破止损线（防守信号原料）

用法：
  python3 scripts/monitor.py           # 单次扫描
  python3 scripts/monitor.py --loop 60 # 每60秒轮询（盘中由定时任务调用单次）
"""
import json
import os
import sys
import time
import datetime
import re

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# ── 监控清单 ──────────────────────────────────────────────
# 持仓（含止损线，用于触止损检测）
HOLDINGS = [
    {"code": "sz002156", "name": "通富微电", "avg_cost": 59.805, "stop_pct": 0.08, "bucket": "short"},
    {"code": "sz300223", "name": "北京君正", "avg_cost": 138.48, "stop_pct": 0.10, "bucket": "mid"},
    {"code": "sz300285", "name": "国瓷材料", "avg_cost": 75.379, "stop_pct": 0.15, "bucket": "long"},
    {"code": "sz300223", "name": "北京君正", "avg_cost": 134.265, "stop_pct": 0.10, "bucket": "mid"},
    {"code": "sz003033", "name": "征和工业", "avg_cost": 58.241, "stop_pct": 0.08, "bucket": "short"},
    {"code": "sz000636", "name": "风华高科", "avg_cost": 62.427, "stop_pct": 0.15, "bucket": "long"},
    {"code": "sh600598", "name": "北大荒",   "avg_cost": 13.249, "stop_pct": 0.10, "bucket": "mid"},
]
# 自选/观察池
WATCHLIST = [
    {"code": "sz002371", "name": "北方华创"},
    {"code": "sh601138", "name": "工业富联"},
    {"code": "sz300596", "name": "利安隆"},
    {"code": "sz000063", "name": "中兴通讯"},
    {"code": "sz301183", "name": "东田微"},
    {"code": "sh688037", "name": "芯源微"},
    {"code": "sz300433", "name": "蓝思科技"},
]
# 注意：WATCHLIST（自选观察池）当前无单一权威源（config/strategy.yaml 只有 attack_pool/sector_mapping），
# 故保留硬编码；持仓（HOLDINGS）已收敛到 cache/holdings.json，见 _load_holdings_from_json()。

# ── 异动阈值 ──────────────────────────────────────────────
VOL_RATIO_TH = 2.0     # 量比阈值（放量）
RALLY_TH = 5.0         # 急拉涨幅%
PLUNGE_TH = -5.0       # 急跌跌幅%
TURNOVER_TH = 15.0     # 高换手率%
HIGH20_LOOKBACK = 20   # 突破近N日高点


def _to_tencent_full(code: str) -> str:
    """sz300223 -> sz300223（腾讯已用完整前缀，直接返回）"""
    return code


def _load_holdings_from_json():
    """从 cache/holdings.json（单一权威源）读持仓，替代硬编码 HOLDINGS。
    返回 [{code(tcode), name, avg_cost, stop_pct, bucket}, ...]。
    读取失败或 positions 为空时回退硬编码 HOLDINGS（兜底，保证监控不中断）。"""
    try:
        path = os.path.join(CACHE, "holdings.json")
        if not os.path.exists(path):
            return HOLDINGS
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        positions = data.get("positions") or []
        out = []
        for p in positions:
            if not isinstance(p, dict):
                continue
            tcode = p.get("tcode")
            if not tcode:
                code = str(p.get("code") or "")
                if not code:
                    continue
                tcode = ("sh" if code.startswith(("6", "9")) else "sz") + code
            out.append({
                "code": tcode,
                "name": p.get("name") or tcode,
                "avg_cost": p.get("avg_cost"),
                "stop_pct": p.get("stop", 0.10),
                "bucket": p.get("bucket", "mid"),
            })
        return out if out else HOLDINGS
    except Exception as e:
        print(f"[monitor] 读 holdings.json 失败，回退硬编码持仓: {e}")
        return HOLDINGS


def enhanced_quotes(codes):
    """增强版实时行情：名称/现价/昨收/今开/最高/最低/成交量/换手/量比/涨跌幅/时间"""
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    out = {}
    try:
        resp = requests.get(url, headers=UA, timeout=15)
        resp.encoding = "gbk"
        for m in re.finditer(r'v_(\w+)="(.*?)"', resp.text):
            code, raw = m.group(1), m.group(2)
            f = raw.split("~")
            if len(f) < 50 or not f[3]:
                continue
            try:
                out[code] = {
                    "name": f[1],
                    "price": float(f[3]),
                    "prev_close": float(f[4]) if f[4] else None,
                    "open": float(f[5]) if f[5] else None,
                    "volume_hand": float(f[6]) if f[6] else None,
                    "high": float(f[33]) if f[33] else None,
                    "low": float(f[34]) if f[34] else None,
                    "turnover": float(f[38]) if f[38] else None,
                    "vol_ratio": float(f[49]) if f[49] else None,
                    "change_pct": float(f[32]) if f[32] else None,
                    "time": f[30],
                }
            except (ValueError, IndexError):
                continue
    except Exception as e:
        print(f"[monitor] 行情获取失败: {e}")
    return out


def _kline_high20(codes):
    """返回 {code: 近20日最高价}，用 feed 的腾讯日K接口"""
    out = {}
    for code in codes:
        try:
            full = _to_tencent_full(code)
            kl = feed._fetch_tencent_daily(full, count=30)
            if kl and len(kl) >= 2:
                highs = [float(x[3]) for x in kl[-HIGH20_LOOKBACK:]]  # 腾讯日K: [date,open,close,high,low,...]
                out[code] = max(highs)
        except Exception:
            continue
    return out


def detect(stock, q, high20, is_holding):
    """对单只股票做异动检测，返回事件列表"""
    events = []
    code = stock["code"]
    name = stock.get("name", q.get("name", code))
    price = q.get("price")
    chg = q.get("change_pct")
    vr = q.get("vol_ratio")
    to = q.get("turnover")

    def ev(etype, msg, severity):
        return {
            "code": code, "name": name, "type": etype,
            "price": price, "change_pct": chg, "vol_ratio": vr, "turnover": to,
            "msg": msg, "severity": severity,
            "is_holding": is_holding,
            "time": datetime.datetime.now().strftime("%m-%d %H:%M"),
        }

    if price is None:
        return events

    # 放量异动
    if vr is not None and vr >= VOL_RATIO_TH:
        events.append(ev("放量异动", f"量比 {vr:.1f} 倍，成交量突然放大", "high" if chg and chg > 0 else "warn"))
    # 急拉
    if chg is not None and chg >= RALLY_TH:
        events.append(ev("急拉", f"涨幅 {chg:+.2f}%，快速拉升", "high"))
    # 急跌
    if chg is not None and chg <= PLUNGE_TH:
        events.append(ev("急跌", f"跌幅 {chg:+.2f}%，快速跳水", "critical"))
    # 高换手
    if to is not None and to >= TURNOVER_TH:
        events.append(ev("高换手", f"换手率 {to:.1f}%，筹码剧烈交换", "warn"))
    # 突破20日高点
    if high20 and price >= high20 * 0.995:
        events.append(ev("突破", f"站上20日高点 {high20:.2f}，趋势转强", "high"))

    # 触止损（仅持仓）
    if is_holding:
        cost = stock.get("avg_cost")
        stop = stock.get("stop_pct", 0.10)
        if cost and price <= cost * (1 - stop):
            events.append(ev("触止损", f"跌破止损线 {cost*(1-stop):.2f}（-{stop*100:.0f}%）", "critical"))

    return events


def run_once():
    """单次扫描：拉行情 → 检测 → 写事件"""
    holdings = _load_holdings_from_json()  # 持仓收敛到 holdings.json 单一权威源
    stocks = holdings + WATCHLIST
    codes = list(dict.fromkeys(s["code"] for s in stocks))
    q = enhanced_quotes(codes)
    high20 = _kline_high20(codes)

    holding_codes = {s["code"] for s in holdings}
    events = []
    for s in stocks:
        code = s["code"]
        qq = q.get(code)
        if not qq:
            continue
        evs = detect(s, qq, high20.get(code), code in holding_codes)
        events.extend(evs)

    # 按严重度排序：critical > high > warn
    order = {"critical": 0, "high": 1, "warn": 2}
    events.sort(key=lambda e: order.get(e["severity"], 3))

    out = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanned": len(stocks),
        "quote_count": len(q),
        "events": events,
    }
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "live_events.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[monitor] 扫描 {len(stocks)} 只，行情 {len(q)} 条，异动 {len(events)} 条")
    for e in events:
        print(f"  [{e['severity']}] {e['name']} {e['type']}: {e['msg']}")
    return out


def main():
    if "--loop" in sys.argv:
        interval = 60
        for a in sys.argv:
            if a.startswith("--loop="):
                interval = int(a.split("=")[1])
        print(f"[monitor] 进入轮询模式，间隔 {interval}s")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[monitor] 异常: {e}")
            time.sleep(interval)
    else:
        run_once()


if __name__ == "__main__":
    main()
