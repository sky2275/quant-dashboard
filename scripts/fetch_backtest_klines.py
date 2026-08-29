"""
fetch_backtest_klines.py —— 批量获取回测用日K线数据

数据来源：腾讯行情 web.ifzq.gtimg.cn（前复权日K）
覆盖范围：当前持仓股 + 最新每日备选池（scan_1430）+ 策略攻击池（attack_pool）
输出：cache/backtest_klines.json

增强：
- 默认拉取 500 个交易日（≈2 年），支持按年维度回测
- 为每只标的预计算常用技术指标与策略信号，供回测引擎与备选池直接使用
"""
from __future__ import annotations

import os
import sys
import json
import time
import math
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


def fetch_kline(full_code: str, days: int = 500) -> list:
    """
    获取腾讯前复权日K。返回 [[date, open, close, high, low, volume], ...] 旧→新。
    字段顺序与腾讯 fqkline 接口一致：row[3]=high, row[4]=low。
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


def _sma(values: list, n: int) -> list:
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(None)
            continue
        out.append(sum(values[i - n + 1 : i + 1]) / n)
    return out


def _ema(values: list, n: int) -> list:
    k = 2 / (n + 1)
    out = [values[0]]
    for i in range(1, len(values)):
        out.append(values[i] * k + out[-1] * (1 - k))
    return out


def _macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_f = _ema(closes, fast)
    ema_s = _ema(closes, slow)
    dif = [f - s for f, s in zip(ema_f, ema_s)]
    dea = _ema(dif, signal)
    hist = [2 * (d - a) for d, a in zip(dif, dea)]
    return dif, dea, hist


def _rsi(closes: list, n: int = 14) -> list:
    out = [50.0]
    gain = loss = 0.0
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        g = max(change, 0)
        l = max(-change, 0)
        if i <= n:
            gain = (gain * (i - 1) + g) / i
            loss = (loss * (i - 1) + l) / i
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l) / n
        out.append(100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    return out


def compute_signals(kline: list) -> dict:
    """
    基于日K计算机构/主力常用策略信号，返回最近一期信号与各指标当前值。
    kline: [[date, open, close, low, high, volume], ...]
    """
    if len(kline) < 60:
        return {}
    dates = [row[0] for row in kline]
    opens = [row[1] for row in kline]
    closes = [row[2] for row in kline]
    lows = [row[4] for row in kline]   # 修正：row[4]=low（此前误用 row[3]=high）
    highs = [row[3] for row in kline]  # 修正：row[3]=high（此前误用 row[4]=low）
    volumes = [row[5] for row in kline]

    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    dif, dea, hist = _macd(closes)
    rsi14 = _rsi(closes, 14)
    vol_ma20 = _sma(volumes, 20)

    # 最新一期索引
    i = len(kline) - 1
    prev = i - 1

    signals = {
        "date": dates[i],
        "close": round(closes[i], 3),
        "change_pct": round((closes[i] - closes[prev]) / closes[prev] * 100, 2) if prev >= 0 else 0,
        "ma5": round(ma5[i], 3) if ma5[i] else None,
        "ma10": round(ma10[i], 3) if ma10[i] else None,
        "ma20": round(ma20[i], 3) if ma20[i] else None,
        "ma60": round(ma60[i], 3) if ma60[i] else None,
        "macd_dif": round(dif[i], 4),
        "macd_dea": round(dea[i], 4),
        "macd_hist": round(hist[i], 4),
        "rsi14": round(rsi14[i], 2),
        "volume_ratio": round(volumes[i] / vol_ma20[i], 2) if vol_ma20[i] else 1.0,
    }

    # 1. MA5/10 金叉死叉（最新一期）
    if ma5[prev] is not None and ma10[prev] is not None:
        if ma5[i] > ma10[i] and ma5[prev] <= ma10[prev]:
            signals["ma_cross"] = "golden"
        elif ma5[i] < ma10[i] and ma5[prev] >= ma10[prev]:
            signals["ma_cross"] = "death"
        else:
            signals["ma_cross"] = "none"
    else:
        signals["ma_cross"] = "none"

    # 2. MACD 金叉死叉
    if dif[prev] <= dea[prev] and dif[i] > dea[i]:
        signals["macd_cross"] = "golden"
    elif dif[prev] >= dea[prev] and dif[i] < dea[i]:
        signals["macd_cross"] = "death"
    else:
        signals["macd_cross"] = "none"

    # 3. 放量突破：当日成交量 > 2 倍 20 日均量 + 涨幅 > 3%
    signals["volume_breakout"] = bool(volumes[i] > 2 * vol_ma20[i] and signals["change_pct"] > 3) if vol_ma20[i] else False

    # 4. 均线多头排列：MA5 > MA10 > MA20 > MA60
    signals["ma_bull_arrange"] = bool(
        ma5[i] and ma10[i] and ma20[i] and ma60[i] and ma5[i] > ma10[i] > ma20[i] > ma60[i]
    )

    # 5. RSI 超卖/超买
    signals["rsi_oversold"] = bool(rsi14[i] < 30)
    signals["rsi_overbought"] = bool(rsi14[i] > 70)

    # 6. 超跌反弹：近 5 日跌幅 > 8% 且 RSI < 35（寻短反）
    if len(closes) >= 6:
        drop_5d = (closes[i] - closes[i - 5]) / closes[i - 5] * 100
        signals["oversold_bounce"] = bool(drop_5d < -8 and rsi14[i] < 35)
    else:
        signals["oversold_bounce"] = False

    # 7. MACD 底背离简化：价格创新低但 DIF 未创新低（近 20 日）
    if len(closes) >= 21:
        recent_low_idx = min(range(i - 19, i + 1), key=lambda x: closes[x])
        prev_low_idx = min(range(i - 39, i - 19), key=lambda x: closes[x]) if len(closes) >= 40 else recent_low_idx
        if recent_low_idx != prev_low_idx:
            price_lower = closes[recent_low_idx] < closes[prev_low_idx] * 0.98
            dif_higher = dif[recent_low_idx] > dif[prev_low_idx]
            signals["macd_divergence"] = bool(price_lower and dif_higher)
        else:
            signals["macd_divergence"] = False
    else:
        signals["macd_divergence"] = False

    # 8. 主力吸筹简化信号：放量阳线 + 收盘在当日 upper 50% + 均线多头
    upper_half = closes[i] > (opens[i] + highs[i]) / 2
    signals["main_force_absorb"] = bool(
        signals["volume_breakout"] and upper_half and signals["ma_bull_arrange"]
    )

    return signals


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

    # 4) 全行业龙头（_SECTOR_LEADERS，扩池用于因子 IC 横截面计算）
    #    覆盖 71 个东财行业 × 3-4 只龙头，行业分散，是 IC 评估的代表性样本
    for sector, leaders in feed._SECTOR_LEADERS.items():
        for s in leaders:
            code = str(s.get("code", "")).strip()
            name = str(s.get("name", "")).strip()
            if code and name:
                targets[code] = name

    if not targets:
        print("[kline] 无目标股票")
        return

    print(f"[kline] 共 {len(targets)} 只标的待获取")
    out = {
        "updated_at": feed.beijing_now().isoformat(),
        "days": 500,
        "stocks": {},
    }

    def _fetch_one(code, name):
        full = _full_code(code)
        if not full:
            return None
        kline = fetch_kline(full, 500)
        if not kline:
            return None
        signals = compute_signals(kline)
        return code, {
            "name": name,
            "full_code": full,
            "kline": kline,
            "signals": signals,
        }

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=6) as exe:
        futures = {exe.submit(_fetch_one, c, n): c for c, n in targets.items()}
        for fut in as_completed(futures):
            try:
                result = fut.result()
                if result:
                    code, payload = result
                    out["stocks"][code] = payload
                    print(f"[kline] {code} {payload['name']}: {len(payload['kline'])} 天")
            except Exception as e:
                print(f"[kline] worker error: {e}")

    out["count"] = len(out["stocks"])
    out_path = os.path.join(CACHE_DIR, "backtest_klines.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[kline] 已保存 {out_path}，共 {out['count']} 只")


if __name__ == "__main__":
    main()
