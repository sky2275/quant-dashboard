#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_holdings_analysis.py — 抓取持仓股复盘分析数据（供 portfolio-review / attack-picks 模板填充）
抓取：近30日日K + 8/28分时 + RSI(6/12/24) + 量比 + MA + Tushare主力资金流
输出：cache/holdings_analysis.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
TRADE_DATE = "2026-08-28"  # 复盘交易日

# 6 只持仓（去重；君正两账户合并计算，成本分开记录）
HOLDINGS = [
    {"tcode": "sz002156", "name": "通富微电", "code": "002156",
     "accts": [{"broker": "银河证券", "shares": 300, "cost": 57.165, "price": 63.75}],
     "theme": ["半导体封测", "先进封装"]},
    {"tcode": "sz300223", "name": "君正股份", "code": "300223",
     "accts": [{"broker": "东方财富", "shares": 1100, "cost": 142.484, "price": 135.7},
               {"broker": "中信建投", "shares": 700, "cost": 132.354, "price": 135.7}],
     "theme": ["存储芯片", "DRAM/NAND"]},
    {"tcode": "sz003033", "name": "征和工业", "code": "003033",
     "accts": [{"broker": "中信建投", "shares": 500, "cost": 56.274, "price": 68.37}],
     "theme": ["链传动", "人形机器人"]},
    {"tcode": "sz300499", "name": "高澜股份", "code": "300499",
     "accts": [{"broker": "中信建投", "shares": 300, "cost": 26.467, "price": 30.92}],
     "theme": ["数据中心液冷", "AI算力"]},
    {"tcode": "sz300579", "name": "数字认证", "code": "300579",
     "accts": [{"broker": "中信建投", "shares": 1000, "cost": 22.612, "price": 23.12}],
     "theme": ["电子认证", "网络安全"]},
    {"tcode": "sh600487", "name": "亨通光电", "code": "600487",
     "accts": [{"broker": "中信建投", "shares": 500, "cost": 62.515, "price": 68.7}],
     "theme": ["光通信", "海缆/光模块"]},
]


def wilder_rsi(closes, period):
    """Wilder 平滑 RSI"""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def ma(closes, n):
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 2)


def vol_ratio_5(volumes):
    """5日量比 = 当日量 / 前5日均量（不含当日）"""
    if len(volumes) < 6:
        return None
    base = sum(volumes[-6:-1]) / 5
    if base <= 0:
        return None
    return round(volumes[-1] / base, 2)


def rsi_state(v):
    if v is None:
        return ("—", "neu")
    if v >= 80:
        return ("🔴 严重超买", "rsi-warn")
    if v >= 70:
        return ("🟠 超买", "rsi-warn")
    if v >= 60:
        return ("🟡 偏强", "")
    if v >= 40:
        return ("🟢 健康", "")
    return ("🔵 偏弱", "")


def vol_state(v):
    if v is None:
        return "—"
    if v >= 2:
        return "🟠 放量"
    if v >= 1.2:
        return "🟡 温和放量"
    if v >= 0.8:
        return "🟢 正常"
    return "🔵 缩量"


def tushare_moneyflow(code, trade_date="20260828"):
    """{main_net_wan, buy_lg, sell_lg, buy_elg, sell_elg} 单位万元"""
    pro = feed._tushare_pro()
    if not pro:
        return None
    ts_code = feed.to_tscode(code) or (code + (".SH" if code.startswith(("6", "9")) else ".SZ"))
    try:
        df = pro.moneyflow(ts_code=ts_code, start_date=trade_date, end_date=trade_date)
        if df is not None and len(df):
            r = df.iloc[0]
            return {
                "main_net_wan": r.get("net_mf_amount"),
                "buy_lg_wan": r.get("buy_lg_amount"),
                "sell_lg_wan": r.get("sell_lg_amount"),
                "buy_elg_wan": r.get("buy_elg_amount"),
                "sell_elg_wan": r.get("sell_elg_amount"),
            }
    except Exception:
        pass
    return None


def main():
    out = {"trade_date": TRADE_DATE, "stocks": {}}

    for h in HOLDINGS:
        tcode = h["tcode"]
        # 近30日日K（腾讯：[date, open, close, high, low, volume]）
        kl = feed._fetch_tencent_daily(tcode, count=30)
        # 分时
        intraday = feed._fetch_tencent_intraday(tcode)
        # 资金流
        mf = tushare_moneyflow(h["code"], TRADE_DATE.replace("-", ""))

        rec = {
            "name": h["name"], "code": h["code"], "tcode": tcode,
            "theme": h["theme"], "accts": h["accts"],
        }
        if kl and len(kl) >= 21:
            closes = [float(k[2]) for k in kl]
            volumes = [float(k[5]) for k in kl]
            rec["kline"] = kl  # 完整日K
            rec["rsi6"] = wilder_rsi(closes, 6)
            rec["rsi12"] = wilder_rsi(closes, 12)
            rec["rsi24"] = wilder_rsi(closes, 24)
            rec["ma5"] = ma(closes, 5)
            rec["ma20"] = ma(closes, 20)
            rec["ma60"] = ma(closes, 60)
            rec["vol_ratio"] = vol_ratio_5(volumes)
            last = kl[-1]
            rec["last_date"] = last[0]
            rec["last_open"] = float(last[1])
            rec["last_close"] = float(last[2])
            rec["last_high"] = float(last[3])
            rec["last_low"] = float(last[4])
            rec["last_volume"] = float(last[5])
            # 前一日收盘（算当日涨跌幅）
            prev_close = float(kl[-2][2])
            rec["day_chg"] = round((rec["last_close"] / prev_close - 1) * 100, 2)
            # 近20日高点/低点（支撑压力）
            rec["high20"] = max(float(k[3]) for k in kl[-21:-1])
            rec["low20"] = min(float(k[4]) for k in kl[-21:-1])
        if intraday and intraday.get("data"):
            rec["intraday"] = intraday["data"]

        # 资金流
        if mf:
            rec["moneyflow"] = mf
        out["stocks"][h["code"]] = rec
        print(f"[ok] {h['name']} RSI6={rec.get('rsi6')} RSI12={rec.get('rsi12')} RSI24={rec.get('rsi24')} "
              f"量比={rec.get('vol_ratio')} 涨跌={rec.get('day_chg')}% 主力净流={mf.get('main_net_wan') if mf else None}")

    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "holdings_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n[done] 已写入 cache/holdings_analysis.json")


if __name__ == "__main__":
    main()
