"""
feed.py —— 真实行情数据层（云端 Actions / 本机均可运行）
数据源策略（v2）：
  - 指数/美股个股：腾讯行情 qt.gtimg.cn 为主（对海外IP友好、毫秒级响应），akshare 兜底
  - 板块资金流/涨停板/个股资金流：akshare（东方财富源）+ 自动重试
所有函数带 try/except，单点失败不拖垮整体；结果缓存为 JSON 供看板读取。
本文件只负责“拿数据”，不含任何交易判断。
"""
from __future__ import annotations
import os
import json
import re
import time
import datetime as dt

# 北京时间（Asia/Shanghai, UTC+8）统一时间基准，避免 GitHub Actions runner(UTC) 时区偏差导致"更新时间"晚8小时及日期边界误判
try:
    from zoneinfo import ZoneInfo
    _BJ_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    _BJ_TZ = None


def beijing_now():
    return dt.datetime.now(_BJ_TZ) if _BJ_TZ else dt.datetime.now()


def beijing_today():
    return beijing_now().date()
from typing import Any, Callable

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _save(name: str, obj: Any) -> None:
    with open(os.path.join(CACHE_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def _load(name: str) -> Any | None:
    p = os.path.join(CACHE_DIR, f"{name}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- 模块冻结（逐模块固定，互不污染）
MODULES_JSON = os.path.join(REPO_ROOT, "config", "modules.json")

def load_module_status() -> dict:
    """读取 config/modules.json 的 modules 字段。每个模块含 status(frozen/active/draft) 与 data_file。"""
    if not os.path.exists(MODULES_JSON):
        return {}
    try:
        with open(MODULES_JSON, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("modules", {})
    except Exception:
        return {}

def is_frozen(key: str) -> bool:
    st = load_module_status().get(key, {})
    return str(st.get("status", "")).lower() == "frozen"

def _frozen_data(key: str):
    """已冻结模块：从独立静态 json 读取。该文件随仓库提交，云端可读，永不回退接口。"""
    st = load_module_status().get(key, {})
    fn = st.get("data_file")
    if not fn:
        return None
    name = fn[:-5] if fn.endswith(".json") else fn
    return _load(name)


def _retry(fn: Callable, attempts: int = 3, wait: float = 2.0):
    """东财接口在海外机房偶发断连，做指数退避重试。"""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(wait * (i + 1))
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------- 交易日历（tushare → akshare → 周末启发式 三级兜底）
def get_trade_context(today: dt.date | None = None) -> dict:
    """
    判断今天是否 A股交易日，并给出应使用的数据基准日（最近一个交易日）。
    返回 {"is_trade_day": bool, "trade_date": "YYYYMMDD", "today": "YYYYMMDD", "source": str}
    - 交易日   -> trade_date = 今天（显示实时数据）
    - 非交易日 -> trade_date = 最近一个交易日（显示该日收盘数据）
    """
    if today is None:
        today = beijing_today()
    today_s = today.strftime("%Y%m%d")
    start_s = (today - dt.timedelta(days=30)).strftime("%Y%m%d")

    # 1) tushare 官方交易日历（最准确，含节假日）
    pro = _tushare_pro()
    if pro:
        try:
            cal = pro.trade_cal(exchange="SSE", start_date=start_s, end_date=today_s)
            if cal is not None and not cal.empty:
                cal = cal.sort_values("cal_date")
                open_days = cal[cal["is_open"] == 1]["cal_date"].tolist()
                if open_days:
                    is_open = open_days[-1] == today_s
                    return {"is_trade_day": is_open,
                            "trade_date": open_days[-1],
                            "today": today_s, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            print(f"[trade_cal] tushare 失败: {e}")

    # 2) akshare 新浪交易日历
    try:
        import akshare as ak
        df = _retry(lambda: ak.tool_trade_date_hist_sina(), attempts=2, wait=1)
        if df is not None and not df.empty:
            days = sorted(str(x).replace("-", "")[:8] for x in df["trade_date"].tolist())
            past = [d for d in days if d <= today_s]
            if past:
                is_open = past[-1] == today_s
                return {"is_trade_day": is_open,
                        "trade_date": past[-1],
                        "today": today_s, "source": "akshare"}
    except Exception as e:  # noqa: BLE001
        print(f"[trade_cal] akshare 失败: {e}")

    # 3) 周末启发式（不含节假日，仅兜底）
    d = today
    while d.weekday() >= 5:  # 周六=5 周日=6
        d -= dt.timedelta(days=1)
    return {"is_trade_day": today.weekday() < 5,
            "trade_date": d.strftime("%Y%m%d"),
            "today": today_s, "source": "weekday"}


# ---------------------------------------------------------------- 技术指标（RSI / 量比）
def compute_rsi(closes, period: int = 14) -> float | None:
    """Wilder RSI。closes 为收盘价序列（旧→新）。不足 period+1 根返回 None。"""
    try:
        cs = [float(c) for c in closes if c is not None]
    except Exception:
        return None
    if len(cs) < period + 1:
        return None
    deltas = [cs[i] - cs[i - 1] for i in range(1, len(cs))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def to_tscode(code: str) -> str | None:
    """6 位 A股代码 -> tushare ts_code（如 600584 -> 600584.SH）。非法返回 None。"""
    s = str(code).strip()
    if len(s) != 6 or not s.isdigit():
        return None
    if s[0] == "6":
        return f"{s}.SH"
    if s[0] in ("0", "3"):
        return f"{s}.SZ"
    if s[0] in ("8", "4"):
        return f"{s}.BJ"
    return None


def compute_macd(closes, fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    """返回最新 {macd_dif, macd_dea, macd_hist}（四舍五入3位）。数据不足返回 None。"""
    try:
        cs = [float(c) for c in closes if c is not None]
    except Exception:
        return None
    if len(cs) < slow + signal:
        return None

    def _ema(data, n):
        k = 2 / (n + 1)
        out = []
        prev = data[0]
        for i, v in enumerate(data):
            if i == 0:
                out.append(v)
            else:
                prev = v * k + prev * (1 - k)
                out.append(prev)
        return out

    ema_f = _ema(cs, fast)
    ema_s = _ema(cs, slow)
    dif = [ema_f[i] - ema_s[i] for i in range(len(cs))]
    dea = _ema(dif, signal)
    hist = [2 * (dif[i] - dea[i]) for i in range(len(cs))]
    return {
        "macd_dif": round(dif[-1], 3),
        "macd_dea": round(dea[-1], 3),
        "macd_hist": round(hist[-1], 3),
    }


def _pct_change(closes, n: int) -> float | None:
    """n 个交易日前到现在的涨跌幅(%)，数据不足返回 None。"""
    try:
        cs = [float(c) for c in closes if c is not None]
    except Exception:
        return None
    if len(cs) <= n:
        return None
    base = cs[-1 - n]
    if not base:
        return None
    return round((cs[-1] - base) / base * 100, 2)


def _score(rsi, week_pct, month_pct, volume_ratio) -> int:
    """综合动量评分(0-100)：周/月涨幅动量为主，RSI 趋势质量 + 量能辅助。仅基于真实数据。"""
    try:
        w = 0 if week_pct is None else max(0.0, min(float(week_pct), 15.0)) / 15.0 * 30.0
        m = 0 if month_pct is None else max(0.0, min(float(month_pct), 30.0)) / 30.0 * 30.0
    except Exception:
        w, m = 0.0, 0.0
    r = 50.0 if rsi is None else float(rsi)
    if 40.0 <= r <= 70.0:
        trend = 20.0 - abs(r - 55.0) / 15.0 * 10.0
    else:
        trend = 5.0
    vr = volume_ratio
    v = 0.0 if vr is None else (10.0 if 1.2 <= vr <= 3.0 else (5.0 if vr > 1.0 else 0.0))
    return int(round(w + m + trend + v))


def _tushare_pro():
    """读取 TUSHARE_TOKEN 环境变量，返回 pro_api；缺 token 或库未装返回 None。"""
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        return None
    try:
        import tushare as ts
        ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def _ak_volume_ratio_map() -> dict:
    """名称 -> 量比（来自全市场快照，一次调用覆盖全部）。失败返回 {}。"""
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zh_a_spot_em(), attempts=2, wait=1)
        out: dict = {}
        if df is None or df.empty:
            return out
        for _, r in df.iterrows():
            name = r.get("名称")
            vr = r.get("量比")
            if name and vr is not None and str(vr) not in ("", "None", "nan"):
                try:
                    out[str(name)] = float(vr)
                except Exception:
                    pass
        return out
    except Exception:
        return {}


def _ak_rsi(em_code: str, end_date: str) -> float | None:
    """单只股票 RSI(14)，来自日线 qfq 收盘。失败返回 None。"""
    try:
        import akshare as ak
        start = (beijing_today() - dt.timedelta(days=75)).strftime("%Y%m%d")
        df = _retry(
            lambda: ak.stock_zh_a_hist(
                symbol=str(em_code), period="daily",
                start_date=start, end_date=end_date, adjust="qfq"),
            attempts=2, wait=0.5)
        if df is None or df.empty or "收盘" not in df.columns:
            return None
        return compute_rsi(df["收盘"].tolist(), 14)
    except Exception:
        return None


# ---------------------------------------------------------------- 批量技术指标（tushare 主力 + akshare 兜底）
def _tushare_indicators(pro, ts_codes: list[str]) -> dict:
    """tushare 批量取 RSI(14)/MACD/量比/换手/主力净流入/周月动量。3 次批量调用覆盖全部标的。"""
    out: dict = {c: {} for c in ts_codes}
    if not ts_codes:
        return out
    end = beijing_today().strftime("%Y%m%d")
    start = (beijing_today() - dt.timedelta(days=70)).strftime("%Y%m%d")
    # 1) RSI + MACD + 周/月动量来自 daily
    try:
        df = pro.daily(ts_code=",".join(ts_codes), start_date=start, end_date=end)
        if df is not None and not df.empty and "close" in df.columns:
            for code, g in df.groupby("ts_code"):
                if code not in out:
                    out[code] = {}
                closes = g.sort_values("trade_date")["close"].tolist()
                out[code]["rsi"] = compute_rsi(closes, 14)
                out[code]["rsi_6"] = compute_rsi(closes, 6)
                out[code]["rsi_12"] = compute_rsi(closes, 12)
                out[code]["rsi_24"] = compute_rsi(closes, 24)
                m = compute_macd(closes)
                if m:
                    out[code].update(m)
                out[code]["week_pct"] = _pct_change(closes, 5)
                out[code]["month_pct"] = _pct_change(closes, 21)
    except Exception as e:  # noqa: BLE001
        print(f"[tushare] daily 失败: {e}")
    # 2) 量比 + 换手来自 daily_basic
    try:
        dfb = pro.daily_basic(ts_code=",".join(ts_codes), start_date=start, end_date=end)
        if dfb is not None and not dfb.empty:
            for code, g in dfb.groupby("ts_code"):
                if code not in out:
                    out[code] = {}
                g = g.sort_values("trade_date")
                last = g.iloc[-1]
                try:
                    out[code]["volume_ratio"] = float(last.get("volume_ratio")) if last.get("volume_ratio") is not None else None
                except Exception:
                    out[code]["volume_ratio"] = None
                try:
                    out[code]["turnover_rate"] = float(last.get("turnover_rate")) if last.get("turnover_rate") is not None else None
                except Exception:
                    out[code]["turnover_rate"] = None
    except Exception as e:  # noqa: BLE001
        print(f"[tushare] daily_basic 失败: {e}")
    # 3) 主力净流入来自 moneyflow（net_mf_amount 单位千元 → 元）
    try:
        dfm = pro.moneyflow(ts_code=",".join(ts_codes), start_date=start, end_date=end)
        if dfm is not None and not dfm.empty and "net_mf_amount" in dfm.columns:
            for code, g in dfm.groupby("ts_code"):
                if code not in out:
                    out[code] = {}
                g = g.sort_values("trade_date")
                amt = g.iloc[-1].get("net_mf_amount")
                try:
                    out[code]["main_flow"] = float(amt) * 1000.0 if amt is not None else None
                except Exception:
                    out[code]["main_flow"] = None
    except Exception as e:  # noqa: BLE001
        print(f"[tushare] moneyflow 失败: {e}")
    # 综合动量评分
    for code, rec in out.items():
        rec["score"] = _score(rec.get("rsi"), rec.get("week_pct"), rec.get("month_pct"), rec.get("volume_ratio"))
    return out


def _akshare_indicators(items: list[tuple]) -> dict:
    """akshare 逐只兜底：RSI/MACD 用日线 qfq，量比/换手用全市场快照（一次）。"""
    out: dict = {}
    name_vr: dict = {}
    name_turn: dict = {}
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zh_a_spot_em(), attempts=2, wait=1)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                nm = r.get("名称")
                if not nm:
                    continue
                try:
                    name_vr[str(nm)] = float(r.get("量比"))
                except Exception:
                    pass
                try:
                    name_turn[str(nm)] = float(r.get("换手率"))
                except Exception:
                    pass
    except Exception:
        pass
    trade_date = beijing_today().strftime("%Y%m%d")
    start = (beijing_today() - dt.timedelta(days=75)).strftime("%Y%m%d")
    for name, ts_code in items:
        if not ts_code:
            out[ts_code] = {}
            continue
        em = ts_code.split(".")[0]
        rec: dict = {}
        try:
            import akshare as ak
            dfh = _retry(
                lambda: ak.stock_zh_a_hist(
                    symbol=em, period="daily",
                    start_date=start, end_date=trade_date, adjust="qfq"),
                attempts=2, wait=0.5)
            if dfh is not None and not dfh.empty and "收盘" in dfh.columns:
                closes = dfh["收盘"].tolist()
                rec["rsi"] = compute_rsi(closes, 14)
                rec["rsi_6"] = compute_rsi(closes, 6)
                rec["rsi_12"] = compute_rsi(closes, 12)
                rec["rsi_24"] = compute_rsi(closes, 24)
                m = compute_macd(closes)
                if m:
                    rec.update(m)
            if "换手率" in dfh.columns:
                try:
                    rec["turnover_rate"] = float(dfh["换手率"].iloc[-1])
                except Exception:
                    pass
            rec["week_pct"] = _pct_change(closes, 5)
            rec["month_pct"] = _pct_change(closes, 21)
        except Exception:
            pass
        rec["volume_ratio"] = name_vr.get(name)
        if rec.get("turnover_rate") is None:
            rec["turnover_rate"] = name_turn.get(name)
        rec["main_flow"] = None  # 主力净流入仅 tushare moneyflow 提供；无 token 时显示 —
        rec["score"] = _score(rec.get("rsi"), rec.get("week_pct"), rec.get("month_pct"), rec.get("volume_ratio"))
        out[ts_code] = rec
        time.sleep(0.05)
    return out


def get_indicators(items: list[tuple]) -> dict:
    """
    批量获取技术指标（RSI14 / MACD / 量比 / 换手 / 主力净流入 / 周月动量 / 评分）。
    items: list of (name, ts_code)，ts_code 形如 '600584.SH'。
    优先 tushare（3 次批量调用：daily / daily_basic / moneyflow）；否则 akshare 逐只兜底；
    最后腾讯 K线 fallback（仅 RSI/MACD/MA/量比）。少量缺失自动补齐。
    返回 {ts_code: {rsi, macd_dif, macd_dea, macd_hist, volume_ratio, turnover_rate,
                     main_flow(元), week_pct, month_pct, score(0-100)}}
    """
    valid = [(n, t) for n, t in items if t]
    if not valid:
        return {}
    pro = _tushare_pro()
    out = {}
    if pro:
        ts_codes = [t for _, t in valid]
        out = _tushare_indicators(pro, ts_codes)
        # 个别缺失（如北交所/退市）用 akshare 补
        missing = [(n, t) for n, t in valid if t not in out or not out.get(t)]
        if missing:
            filled = _akshare_indicators(missing)
            for t, rec in filled.items():
                base = out.get(t, {})
                base.update({k: v for k, v in rec.items() if v is not None})
                out[t] = base
            out = out or _akshare_indicators(valid)
    else:
        out = _akshare_indicators(valid)
    # 兜底：腾讯 K线（RSI/MACD/MA/量比）
    still_missing = [(n, t) for n, t in valid if t not in out or not out.get(t) or out.get(t, {}).get("rsi") is None]
    if still_missing:
        qt = _tencent_kline_indicators(still_missing)
        for t, rec in qt.items():
            base = out.get(t, {})
            base.update({k: v for k, v in rec.items() if v is not None})
            out[t] = base
    return out


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    ag = gains / period
    al = losses / period
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 2)


def _ema(values, period):
    if not values:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    fast_ema = []
    slow_ema = []
    kf = 2 / (fast + 1)
    ks = 2 / (slow + 1)
    ef = closes[0]
    es = closes[0]
    for c in closes:
        ef = c * kf + ef * (1 - kf)
        es = c * ks + es * (1 - ks)
        fast_ema.append(ef)
        slow_ema.append(es)
    dif = [f - s for f, s in zip(fast_ema, slow_ema)]
    dea = []
    kd = 2 / (signal + 1)
    ed = dif[0]
    for d in dif:
        ed = d * kd + ed * (1 - kd)
        dea.append(ed)
    hist = [d - e for d, e in zip(dif, dea)]
    return round(dif[-1], 4), round(dea[-1], 4), round(hist[-1], 4)


def _tencent_kline_indicators(items):
    """腾讯 K线 fallback：计算 RSI14/MACD/MA5-20/量比。换手率/主力净额不在K线中无法计算。"""
    out = {}
    UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    for name, ts in items:
        if not ts:
            continue
        # ts = '600584.SH' -> 'sh600584'
        code = ts.split(".")[0]
        mkt = ts.split(".")[1]
        prefix = "sh" if mkt == "SH" else ("sz" if mkt == "SZ" else "bj")
        full = f"{prefix}{code}"
        try:
            import requests as _req
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,60,qfq"
            r = _req.get(url, timeout=8, headers=UA)
            j = r.json()
            kl = (j.get("data", {}).get(full, {}).get("qfqday") or
                  j.get("data", {}).get(full, {}).get("day") or [])
            if len(kl) < 20:
                continue
            closes = [float(k[2]) for k in kl]
            vols = [float(k[5]) for k in kl]
            ma5 = round(sum(closes[-5:]) / 5, 3) if len(closes) >= 5 else None
            ma10 = round(sum(closes[-10:]) / 10, 3) if len(closes) >= 10 else None
            ma20 = round(sum(closes[-20:]) / 20, 3) if len(closes) >= 20 else None
            rsi = _rsi(closes, 14)
            rsi_6 = _rsi(closes, 6)
            rsi_12 = _rsi(closes, 12)
            rsi_24 = _rsi(closes, 24)
            macd_dif, macd_dea, macd_hist = _macd(closes)
            vol_ratio = None
            if len(vols) >= 6:
                avg5 = sum(vols[-6:-1]) / 5
                if avg5 > 0:
                    vol_ratio = round(vols[-1] / avg5, 2)
            out[ts] = {
                "rsi": rsi,
                "rsi_6": rsi_6, "rsi_12": rsi_12, "rsi_24": rsi_24,
                "macd_dif": macd_dif, "macd_dea": macd_dea, "macd_hist": macd_hist,
                "volume_ratio": vol_ratio,
                "ma5": ma5, "ma10": ma10, "ma20": ma20,
            }
        except Exception as e:
            print(f"[tencent_kline_indicators] {name} {ts}: {e}")
    return out


def enrich_heatmap(heat: list, trade_date: str | None = None) -> list:
    """给资金流前 N 名补上真实 RSI / 量比。失败的行留 None（看板显示 '—'），不拖垮整体。"""
    real = [x for x in heat if isinstance(x, dict) and "error" not in x]
    if not real:
        return heat
    if trade_date is None:
        trade_date = beijing_today().strftime("%Y%m%d")
    vr_map = _ak_volume_ratio_map()
    for x in real:
        name = x.get("名称")
        code = str(x.get("代码", "") or "")
        x["量比"] = vr_map.get(name)
        x["rsi"] = _ak_rsi(code, trade_date) if code else None
        time.sleep(0.05)  # 礼貌限速，避免东财风控
    return heat


# ---------------------------------------------------------------- 腾讯行情源
def tencent_quotes(codes: list[str]) -> dict[str, dict]:
    """批量获取腾讯行情。codes 如 ['sh000001','usIXIC','usNVDA']。
    返回 {code: {name, price, change_pct, change, date}}"""
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    resp = requests.get(url, headers=UA, timeout=15)
    resp.encoding = "gbk"
    out: dict[str, dict] = {}
    for m in re.finditer(r'v_(\w+)="(.*?)"', resp.text):
        code, raw = m.group(1), m.group(2)
        f = raw.split("~")
        if len(f) < 34 or not f[3]:
            continue
        try:
            out[code] = {
                "name": f[1],
                "price": float(f[3]),
                "change": float(f[31]) if f[31] else None,
                "change_pct": float(f[32]) if f[32] else None,
                "time": f[30],
            }
        except ValueError:
            continue
    return out


def tencent_index_amount(codes: list[str]) -> dict[str, float]:
    """
    从腾讯指数行情原始字段 f[35]（格式：价格/成交量/成交金额）提取成交金额（元）。
    用于两市总成交额等不会被东财风控影响的稳定数据源。
    返回 {code: amount_yuan}。
    """
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    resp = requests.get(url, headers=UA, timeout=15)
    resp.encoding = "gbk"
    out: dict[str, float] = {}
    for m in re.finditer(r'v_(\w+)="(.*?)"', resp.text):
        code, raw = m.group(1), m.group(2)
        f = raw.split("~")
        if len(f) < 36:
            continue
        try:
            combo = f[35]
            parts = combo.split("/")
            if len(parts) >= 3:
                out[code] = float(parts[2])
        except (ValueError, IndexError):
            continue
    return out


_US_INDEX_CODES = {"usIXIC": "纳斯达克", "usDJI": "道琼斯", "usINX": "标普500"}
_A_INDEX_CODES = {"sh000001": "上证指数", "sz399001": "深证成指",
                  "sz399006": "创业板指", "sh000688": "科创50"}


def get_us_indices() -> list[dict]:
    # 主力：腾讯源
    try:
        q = tencent_quotes(list(_US_INDEX_CODES))
        out = [{"name": _US_INDEX_CODES[c], "price": v["price"],
                "change_pct": v["change_pct"]} for c, v in q.items() if c in _US_INDEX_CODES]
        if out:
            return out
    except Exception:
        pass
    # 兜底：akshare 东财
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_us_spot_em())
        out = []
        for n in ["纳斯达克", "道琼斯", "标普500"]:
            row = df[df["名称"] == n]
            if not row.empty:
                r = row.iloc[0]
                out.append({"name": n, "price": r.get("最新价"), "change_pct": r.get("涨跌幅")})
        return out
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_us_stocks(symbols: list[str]) -> dict[str, dict]:
    """批量美股个股（腾讯源）：symbols 如 ['NVDA','TSLA'] -> {symbol: {...}}"""
    try:
        codes = ["us" + s.upper() for s in symbols]
        q = tencent_quotes(codes)
        return {c[2:]: {"symbol": c[2:], "name": v["name"],
                        "price": v["price"], "change_pct": v["change_pct"]}
                for c, v in q.items() if c.startswith("us")}
    except Exception:
        return {}


def get_us_stock(symbol: str) -> dict | None:
    got = get_us_stocks([symbol])
    if symbol.upper() in got:
        return got[symbol.upper()]
    # 兜底：akshare
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_us_spot_em())
        row = df[df["代码"].str.contains(symbol, na=False)]
        if row.empty:
            return None
        r = row.iloc[0]
        return {"symbol": symbol, "name": r.get("名称"),
                "price": r.get("最新价"), "change_pct": r.get("涨跌幅")}
    except Exception:
        return None


def get_a_indexes() -> list[dict]:
    try:
        q = tencent_quotes(list(_A_INDEX_CODES))
        out = [{"name": _A_INDEX_CODES[c], "price": v["price"],
                "change_pct": v["change_pct"], "change": v.get("change")} for c, v in q.items() if c in _A_INDEX_CODES]
        if out:
            return out
    except Exception:
        pass
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zh_index_spot_em())
        out = []
        for n in ["上证指数", "深证成指", "创业板指", "科创50"]:
            row = df[df["名称"] == n]
            if not row.empty:
                r = row.iloc[0]
                out.append({"name": n, "price": r.get("最新价"), "change_pct": r.get("涨跌幅")})
        return out
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_a_stocks(codes: list[str]) -> dict[str, dict]:
    """批量A股个股（腾讯源）：codes 如 ['sh600584','sz002156']"""
    try:
        return tencent_quotes(codes)
    except Exception:
        return {}


# --------------------------------------- 资金流（东财主力 / 同花顺兜底）
SECTOR_FLOW_OVERRIDES = [
    os.path.join(CACHE_DIR, "sector_flow_table.xls"),   # 用户可放置同花顺导出文件
    os.path.expanduser("~/Desktop/Table.xls"),          # 默认扫描桌面文件
]


def _parse_ths_table(path: str) -> list[dict] | None:
    """
    解析同花顺导出的 *.xls 板块资金表（实际为 GBK 编码、\t 分隔、\r 换行的文本）。
    返回统一字段：名称, 净流入(元), 流入资金(元), 流出资金(元), 涨跌幅(%), 领涨股。
    表头列名：板块名称、涨幅、主力净量、GS策略、主力资金、主力金额、涨停数、涨家数、跌家数、领涨股...
    其中『主力资金』视为当日主力净流入（元）。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("gbk", errors="replace")
        lines = text.strip().split("\r")
        if not lines:
            return None
        header = [c.strip() for c in lines[0].split("\t")]
        if "板块名称" not in header or "主力资金" not in header:
            return None
        name_idx = header.index("板块名称")
        net_idx = header.index("主力资金")
        pct_idx = header.index("涨幅") if "涨幅" in header else None
        leader_idx = header.index("领涨股") if "领涨股" in header else None

        def _num(v) -> float:
            s = str(v).replace(",", "").replace("+", "").replace("%", "").strip()
            try:
                return float(s)
            except Exception:
                return 0.0

        out = []
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) <= max(name_idx, net_idx):
                continue
            name = cols[name_idx].strip()
            net = _num(cols[net_idx])
            pct = _num(cols[pct_idx]) if pct_idx is not None else None
            leader = cols[leader_idx].strip() if leader_idx is not None and len(cols) > leader_idx else None
            # 本地表只有净流入（主力资金），流入/流出按净额方向拆分，仅供排序展示
            out.append({
                "名称": name,
                "净流入": net,
                "流入资金": net if net >= 0 else 0.0,
                "流出资金": -net if net < 0 else 0.0,
                "涨跌幅": pct,
                "领涨股": leader,
            })
        return out
    except Exception as e:
        print(f"[_parse_ths_table] 解析失败 {path}: {e}")
        return None


def get_sector_fund_flow() -> list[dict]:
    """
    行业板块资金流。统一输出字段：
      名称, 净流入(元), 流入资金(元), 流出资金(元), 涨跌幅
    1) 优先读取本地同花顺导出表（cache/sector_flow_table.xls 或 ~/Desktop/Table.xls），
       方便用户用客户端数据覆盖接口口径。
    2) 主源：同花顺 stock_fund_flow_industry（含完整的流入/流出/净额三列，不受东财风控）。
    3) 兜底：东财 stock_sector_fund_flow_rank（字段不齐时只保证净流入）。
    """
    # 1) 本地覆盖文件（最高优先级）
    for p in SECTOR_FLOW_OVERRIDES:
        ov = _parse_ths_table(p)
        if ov:
            print(f"[sector_flow] 使用本地覆盖文件: {p}")
            return ov

    # 2) 主源：同花顺（新浪源，稳定，含流入/流出/净额）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_fund_flow_industry(symbol="即时"), attempts=2)
        if df is not None and not df.empty and "行业" in df.columns and "净额" in df.columns:
            df = df.copy()
            # 列类型：净额/流入资金/流出资金 默认是亿元
            out = []
            for _, r in df.iterrows():
                net = float(r.get("净额", 0)) * 1e8   # 亿元 -> 元
                # 同花顺表通常自带流入/流出资金；缺失时按净额方向估算
                inflow = float(r.get("流入资金", (net + abs(net)) / 2)) * 1e8
                outflow = float(r.get("流出资金", (abs(net) - net) / 2)) * 1e8
                # 保证 净流入 = 流入 - 流出（当接口列缺失或微小误差时微调）
                if abs((inflow - outflow) - net) > 1e8:
                    inflow = max(inflow, net)
                    outflow = inflow - net
                out.append({
                    "名称": r.get("行业"),
                    "净流入": net,
                    "流入资金": inflow,
                    "流出资金": outflow,
                    "涨跌幅": r.get("行业-涨跌幅"),
                })
            return out
    except Exception as e:  # noqa: BLE001
        print(f"[sector_flow] 同花顺失败: {e}")

    # 3) 兜底：东财（只有净流入，流入/流出用简化估算）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_sector_fund_flow_rank(
            indicator="今日", sector_type="行业资金流"), attempts=2)
        if df is None or df.empty:
            return []
        cols = [c for c in ["名称", "今日主力净流入-净额", "今日主力净流入-净占比", "涨跌幅"] if c in df.columns]
        out = []
        for _, r in df.iterrows():
            net = float(r.get("今日主力净流入-净额", 0))
            out.append({
                "名称": r.get("名称"),
                "净流入": net,
                "流入资金": net if net >= 0 else 0,
                "流出资金": -net if net < 0 else 0,
                "涨跌幅": r.get("涨跌幅"),
            })
        return out
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)[:120]}]


def get_limit_up(date: str | None = None) -> list[dict]:
    """
    涨停板清单，口径与券商 APP 对齐（约121家）：
      1) 主体来自全市场快照 stock_zh_a_spot 的「曾触及涨停」全集（非ST，涨跌幅>=涨停板-1.8，
         含炸板），保证家数与券商APP一致且不受东财接口限流影响；
      2) 用东财涨停池 stock_zt_pool_em 按「名称」补连板数（封单资金东财接口无该列，显示—）。
    """
    if date is None:
        date = beijing_today().strftime("%Y%m%d")
    # 1) 曾触及涨停全集（快照口径，恒定约121）
    snap_hits: list[dict] = []
    try:
        import akshare as ak
        spot = _retry(lambda: ak.stock_zh_a_spot(), attempts=3, wait=1.5)
        if spot is not None and not spot.empty:
            sp = spot.copy()
            sp["_code"] = sp["代码"].astype(str).str[2:]
            sp["_is_st"] = sp["名称"].astype(str).str.contains("ST", case=False, na=False)

            def _lim(r):
                if r["_is_st"]:
                    return 5.0
                c = str(r["_code"])
                raw = str(r["代码"])
                if raw.startswith("bj") or c.startswith(("8", "4")):  # 北交所 30%
                    return 30.0
                if c.startswith("688") or c.startswith("30"):  # 科创/创业 20%
                    return 20.0
                return 10.0
            sp["_limit"] = sp.apply(_lim, axis=1)
            hit = sp[(~sp["_is_st"]) & (sp["涨跌幅"] >= sp["_limit"] - 1.8)]
            for _, r in hit.iterrows():
                # 不同 akshare 版本行业列名可能不同
                industry = None
                for col in ("所属行业", "行业", "板块", "细分行业"):
                    industry = r.get(col)
                    if industry and str(industry).strip() and str(industry).strip() != "nan":
                        industry = str(industry).strip()
                        break
                snap_hits.append({
                    "名称": r.get("名称"), "代码": str(r.get("代码", "")),
                    "涨跌幅": r.get("涨跌幅"), "成交额": r.get("成交额"),
                    "所属行业": industry or "—",
                })
    except Exception as e:
        print(f"[limit_up] 快照失败: {e}")
    # 2) 东财涨停池补连板数、封单资金与所属行业（按名称匹配，避免代码格式差异）
    board_map: dict = {}
    seal_map: dict = {}
    industry_map: dict = {}
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zt_pool_em(date=date), attempts=3, wait=1.5)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                nm = r.get("名称")
                if nm:
                    nm = str(nm)
                    try:
                        board_map[nm] = int(r.get("连板数", 1) or 1)
                    except Exception:
                        board_map[nm] = 1
                    # 尝试读取封单/封板资金（不同版本 akshare 列名可能不同）
                    for col in ("封板资金", "封单资金", "封单金额"):
                        val = r.get(col)
                        if val is not None:
                            try:
                                seal_map[nm] = float(val)
                            except Exception:
                                pass
                            break
                    # 尝试读取行业
                    for col in ("所属行业", "行业", "板块"):
                        val = r.get(col)
                        if val and str(val).strip() and str(val).strip() != "nan":
                            industry_map[nm] = str(val).strip()
                            break
    except Exception as e:
        print(f"[limit_up] 东财涨停池失败: {e}")
    # 3) 合并
    out: list[dict] = []
    for x in snap_hits:
        nm = str(x.get("名称"))
        b = board_map.get(nm)
        x["连板数"] = b if b else 1
        x["封单资金"] = seal_map.get(nm)
        if x.get("所属行业") in (None, "—") and nm in industry_map:
            x["所属行业"] = industry_map[nm]
        out.append(x)
    return out if out else [{"error": "no limit-up data"}]


def _board_limit(name: str, code: str) -> float:
    """按名称/代码判断涨跌停幅度(%)：ST=5，创业板/科创板/北交所=20，其余=10。"""
    if name and "ST" in str(name).upper():
        return 5.0
    lead = str(code)[:1]
    if lead in ("3", "8", "4") or str(code).startswith("688"):
        return 20.0
    return 10.0


def _to_tencent_full(code: str) -> str | None:
    """6位A股代码或带前缀代码 -> 腾讯完整代码如 sh600721"""
    s = str(code).strip().lower()
    if len(s) == 6 and s.isdigit():
        if s[0] in ("6", "9"):
            return f"sh{s}"
        if s[0] in ("0", "3", "8", "4"):
            return f"sz{s}"
        return None
    if s.startswith(("sh", "sz", "bj")) and len(s) == 8:
        return s
    return None


def _fetch_tencent_daily(full: str, count: int = 250) -> list[list]:
    """获取腾讯日K线，返回 [date, open, close, high, low, vol] 列表。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,{count},qfq"
    try:
        r = requests.get(url, timeout=8, headers=headers)
        j = r.json()
        kl = (j.get("data", {}).get(full, {}).get("qfqday") or
              j.get("data", {}).get(full, {}).get("day") or [])
        return [[str(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in kl]
    except Exception as e:
        print(f"[limit_up_klines] daily {full}: {e}")
        return []


def _fetch_tencent_intraday(full: str) -> dict | None:
    """获取腾讯分时数据，返回 {data: [[time, price, avg], ...]}。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={full}"
    try:
        r = requests.get(url, timeout=8, headers=headers)
        j = r.json()
        rows = (j.get("data", {}).get(full, {}).get("data", {}).get("data") or [])
        if not rows:
            return None
        cum_vol = 0.0
        cum_amt = 0.0
        data = []
        for line in rows:
            parts = line.split(" ")
            if len(parts) < 4:
                continue
            time_str = parts[0]
            price = float(parts[1])
            vol = float(parts[2])
            amt = float(parts[3])
            cum_vol += vol
            cum_amt += amt
            avg = cum_amt / cum_vol if cum_vol > 0 else price
            data.append([time_str, price, round(avg, 3)])
        return {"data": data}
    except Exception as e:
        print(f"[limit_up_klines] intraday {full}: {e}")
        return None


def get_limit_up_klines(limit_up: list[dict]) -> dict[str, dict]:
    """
    为涨停个股预拉取日K线与分时数据，用于详情弹窗离线渲染。
    返回 {code: {"daily": [...], "intraday": {...}, "name": ...}}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    real = [x for x in limit_up if isinstance(x, dict) and "error" not in x]
    codes = []
    for x in real:
        code = str(x.get("代码", ""))
        if code and _to_tencent_full(code):
            codes.append(code)
    codes = list(dict.fromkeys(codes))

    out: dict[str, dict] = {}
    if not codes:
        return out

    def _fetch_one(code: str):
        full = _to_tencent_full(code)
        if not full:
            return None
        name = next((x.get("名称") for x in real if str(x.get("代码", "")) == code), None)
        daily = _fetch_tencent_daily(full)
        intraday = _fetch_tencent_intraday(full)
        if not daily and not intraday:
            return None
        return code, {"name": name, "daily": daily, "intraday": intraday}

    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(_fetch_one, code): code for code in codes}
        for fut in as_completed(futures):
            try:
                result = fut.result()
                if result:
                    code, payload = result
                    out[code] = payload
            except Exception as e:
                print(f"[limit_up_klines] worker error: {e}")
    return out


def get_market_breadth() -> dict:
    """
    A股市场宽度：成交额、上涨/下跌家数、涨停/跌停家数。
    口径与同花顺 APP 保持一致：
      - 全部 A股（沪+深+北交所）参与统计
      - 涨停/跌停：非 ST 个股，且 最新价==最高/最低价 并达到对应板块涨跌停幅度
    来源：akshare 新浪源 stock_zh_a_spot()（稳定，海外/自动化环境均可用）。
    返回 {'amount'(元), 'up_count', 'down_count', 'limit_up_count', 'limit_down_count'}
         （缺失项为 None）。
    """
    out = {"amount": None, "up_count": None, "down_count": None,
           "limit_up_count": None, "limit_down_count": None}
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zh_a_spot(), attempts=3, wait=1.5)
        if df is None or df.empty or "涨跌幅" not in df.columns or "代码" not in df.columns:
            return out
        df = df.copy()
        # stock_zh_a_spot 代码格式：sh600000 / sz000001 / bj920000
        df["_code"] = df["代码"].astype(str).str[2:]
        df["_is_st"] = df["名称"].astype(str).str.contains("ST", case=False, na=False)
        def _lim(r):
            if r["_is_st"]:
                return 5.0
            c = str(r["_code"])
            raw = str(r["代码"])
            if raw.startswith("bj") or c.startswith(("8", "4")):  # 北交所 30%
                return 30.0
            if c.startswith("688") or c.startswith("30"):  # 科创/创业 20%
                return 20.0
            return 10.0
        df["_limit"] = df.apply(_lim, axis=1)

        # 1) 成交额：全部 A股求和（与 同花顺/东方财富 APP 口径一致）
        if "成交额" in df.columns:
            try:
                out["amount"] = round(float(df["成交额"].sum()), 2)
            except Exception:  # noqa: BLE001
                pass

        # 2) 上涨/下跌家数：全部 A股
        try:
            up = int((df["涨跌幅"] > 0).sum())
            down = int((df["涨跌幅"] < 0).sum())
            out["up_count"] = up
            out["down_count"] = down
        except Exception:  # noqa: BLE001
            pass

        # 3) 涨停/跌停家数：采用券商 APP 通用口径（与同花顺/东财 APP 对齐）
        #    涨停 = 曾触及涨停（非ST，涨跌幅 >= 涨停板-1.8，含炸板）→ 约121家
        #    跌停 = 封板（非ST，涨跌幅 <= -(涨停板-0.25)）→ 约6家
        try:
            main = df[~df["_is_st"]]
            zt = int((main["涨跌幅"] >= main["_limit"] - 1.8).sum())
            dt = int((main["涨跌幅"] <= -(main["_limit"] - 0.25)).sum())
            out["limit_up_count"] = zt
            out["limit_down_count"] = dt
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        print(f"[breadth] 全市场快照失败: {e}")
    return out


def _tushare_pro():
    """返回 tushare pro 实例（无 token 返回 None）。"""
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        return None
    try:
        import tushare as ts
        return ts.pro_api(token)
    except Exception:
        return None


def get_us_etf_kline(symbol: str, market: str = "O", start_date: str = "20250101",
                     end_date: str | None = None, freq: str = "D") -> list[list]:
    """Tushare 美股 ETF/股票 K 线（备用数据源，腾讯 API 失败时使用）。
    Args:
        symbol: 美股代码，如 SOXX、QQQ、AAPL
        market: 市场后缀 O=Nasdaq / N=NYSE / AMX=NYSE Arca（部分 ETF）
        start_date/end_date: YYYYMMDD
        freq: D=日 / W=周 / M=月（**Tushare 不支持分钟数据**）
    Returns:
        list of [date, open, close, high, low, volume] 列表；失败返回 []
    """
    if end_date is None:
        end_date = dt.date.today().strftime("%Y%m%d")
    pro = _tushare_pro()
    if pro is None:
        return []
    ts_code = f"{symbol}.{market}"
    try:
        df = pro.us_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        # Tushare us_daily 字段: ts_code, trade_date, open, high, low, close, vol
        df = df.sort_values("trade_date")
        rows = []
        for _, r in df.iterrows():
            rows.append([
                str(r["trade_date"]),
                float(r["open"]),
                float(r["close"]),
                float(r["high"]),
                float(r["low"]),
                float(r.get("vol", 0) or 0),
            ])
        return rows
    except Exception as e:
        print(f"[tushare] {ts_code} K线抓取失败: {e}")
        return []


# Tushare 美股 ETF K 线代码映射（symbol.market）
US_ETF_TUSHARE_CODES = {
    "SOXX": ("SOXX", "O"),       # iShares Semiconductor ETF (Nasdaq)
    "QQQ": ("QQQ", "O"),         # Invesco QQQ Trust (Nasdaq)
    "XLK": ("XLK", "O"),         # Technology Select Sector SPDR (NYSE, 用 O 也兼容)
    "SMH": ("SMH", "O"),         # VanEck Semiconductor ETF (Nasdaq)
    "KWEB": ("KWEB", "O"),       # KraneShares CSI China Internet (NYSE Arca, 用 O 兜底)
    "BOTZ": ("BOTZ", "O"),       # Global X Robotics & AI (Nasdaq)
    "ARKQ": ("ARKQ", "O"),       # ARK Autonomous Tech. & Robotics (NYSE Arca, 用 O 兜底)
    "COHR": ("COHR", "O"),       # Coherent Corp (NYSE)
    "LITE": ("LITE", "O"),       # Lumentum Holdings (Nasdaq)
}


# 东财行业名称 -> 代表性成分股（名称+代码），作为实时接口被风控时的兜底，
# 保证 ① 弹窗「每个板块 3-5 只个股」不会满屏显示 "—"。
_SECTOR_LEADERS: dict[str, list[dict]] = {
    "半导体": [{"name": "中芯国际", "code": "688981"}, {"name": "海光信息", "code": "688041"}, {"name": "北方华创", "code": "002371"}, {"name": "韦尔股份", "code": "603501"}, {"name": "兆易创新", "code": "603986"}],
    "电子化学品": [{"name": "江化微", "code": "603078"}, {"name": "晶瑞电材", "code": "300655"}, {"name": "飞凯材料", "code": "300398"}, {"name": "上海新阳", "code": "300236"}],
    "汽车服务及其他": [{"name": "中国汽研", "code": "601965"}, {"name": "特力A", "code": "000025"}, {"name": "广汇汽车", "code": "600297"}, {"name": "国机汽车", "code": "600335"}],
    "橡胶制品": [{"name": "赛轮轮胎", "code": "601058"}, {"name": "玲珑轮胎", "code": "601966"}, {"name": "贵州轮胎", "code": "000589"}, {"name": "三角轮胎", "code": "601163"}],
    "厨卫电器": [{"name": "老板电器", "code": "002508"}, {"name": "华帝股份", "code": "002035"}, {"name": "万和电气", "code": "002543"}, {"name": "火星人", "code": "300894"}],
    "小家电": [{"name": "美的集团", "code": "000333"}, {"name": "苏泊尔", "code": "002032"}, {"name": "九阳股份", "code": "002242"}, {"name": "新宝股份", "code": "002705"}],
    "环保设备": [{"name": "盈峰环境", "code": "000967"}, {"name": "伟明环保", "code": "603568"}, {"name": "瀚蓝环境", "code": "600323"}, {"name": "清新环境", "code": "002573"}],
    "贸易": [{"name": "厦门国贸", "code": "600755"}, {"name": "浙商中拓", "code": "000906"}, {"name": "苏美达", "code": "600710"}, {"name": "五矿发展", "code": "600058"}],
    "非金属材料": [{"name": "方大炭素", "code": "600516"}, {"name": "金博股份", "code": "688598"}, {"name": "索通发展", "code": "603612"}],
    "教育": [{"name": "中公教育", "code": "002607"}, {"name": "学大教育", "code": "000526"}, {"name": "科德教育", "code": "300192"}, {"name": "凯文教育", "code": "002659"}],
    "其他电子": [{"name": "立讯精密", "code": "002475"}, {"name": "歌尔股份", "code": "002241"}, {"name": "领益智造", "code": "002600"}, {"name": "蓝思科技", "code": "300433"}],
    "其他社会服务": [{"name": "宋城演艺", "code": "300144"}, {"name": "锋尚文化", "code": "300860"}, {"name": "科锐国际", "code": "300662"}, {"name": "米奥会展", "code": "300795"}],
    "电池": [{"name": "宁德时代", "code": "300750"}, {"name": "亿纬锂能", "code": "300014"}, {"name": "比亚迪", "code": "002594"}, {"name": "国轩高科", "code": "002074"}],
    "光伏设备": [{"name": "隆基绿能", "code": "601012"}, {"name": "通威股份", "code": "600438"}, {"name": "TCL中环", "code": "002129"}, {"name": "晶科能源", "code": "688223"}],
    "软件开发": [{"name": "金山办公", "code": "688111"}, {"name": "科大讯飞", "code": "002230"}, {"name": "恒生电子", "code": "600570"}, {"name": "宝信软件", "code": "600845"}],
    "通信设备": [{"name": "中兴通讯", "code": "000063"}, {"name": "亨通光电", "code": "600487"}, {"name": "中天科技", "code": "600522"}, {"name": "烽火通信", "code": "600498"}],
    "通用设备": [{"name": "汇川技术", "code": "300124"}, {"name": "埃斯顿", "code": "002747"}, {"name": "机器人", "code": "300024"}, {"name": "绿的谐波", "code": "688017"}],
    "专用设备": [{"name": "三一重工", "code": "600031"}, {"name": "中联重科", "code": "000157"}, {"name": "徐工机械", "code": "000425"}, {"name": "晶盛机电", "code": "300316"}],
    "汽车零部件": [{"name": "福耀玻璃", "code": "600660"}, {"name": "华域汽车", "code": "600741"}, {"name": "拓普集团", "code": "601689"}, {"name": "德赛西威", "code": "002920"}],
    "证券": [{"name": "中信证券", "code": "600030"}, {"name": "东方财富", "code": "300059"}, {"name": "中信建投", "code": "601066"}, {"name": "招商证券", "code": "600999"}],
    "银行": [{"name": "工商银行", "code": "601398"}, {"name": "招商银行", "code": "600036"}, {"name": "建设银行", "code": "601939"}, {"name": "农业银行", "code": "601288"}],
    "保险及其他": [{"name": "中国平安", "code": "601318"}, {"name": "中国人寿", "code": "601628"}, {"name": "中国太保", "code": "601601"}, {"name": "新华保险", "code": "601336"}],
    "房地产开发": [{"name": "万科A", "code": "000002"}, {"name": "保利发展", "code": "600048"}, {"name": "招商蛇口", "code": "001979"}, {"name": "金地集团", "code": "600383"}],
    "化学制品": [{"name": "万华化学", "code": "600309"}, {"name": "华鲁恒升", "code": "600426"}, {"name": "巨化股份", "code": "600160"}, {"name": "龙佰集团", "code": "002601"}],
    "化学制药": [{"name": "恒瑞医药", "code": "600276"}, {"name": "药明康德", "code": "603259"}, {"name": "复星医药", "code": "600196"}, {"name": "科伦药业", "code": "002422"}],
    "生物制品": [{"name": "智飞生物", "code": "300122"}, {"name": "长春高新", "code": "000661"}, {"name": "百济神州", "code": "688235"}, {"name": "沃森生物", "code": "300142"}],
    "医疗器械": [{"name": "迈瑞医疗", "code": "300760"}, {"name": "联影医疗", "code": "688271"}, {"name": "欧普康视", "code": "300595"}, {"name": "乐普医疗", "code": "300003"}],
    "医疗服务": [{"name": "爱尔眼科", "code": "300015"}, {"name": "通策医疗", "code": "600763"}, {"name": "泰格医药", "code": "300347"}, {"name": "凯莱英", "code": "002821"}],
    "中药": [{"name": "片仔癀", "code": "600436"}, {"name": "云南白药", "code": "000538"}, {"name": "同仁堂", "code": "600085"}, {"name": "华润三九", "code": "000999"}],
    "白酒": [{"name": "贵州茅台", "code": "600519"}, {"name": "五粮液", "code": "000858"}, {"name": "泸州老窖", "code": "000568"}, {"name": "山西汾酒", "code": "600809"}],
    "饮料制造": [{"name": "伊利股份", "code": "600887"}, {"name": "东鹏饮料", "code": "605499"}, {"name": "光明乳业", "code": "600597"}, {"name": "养元饮品", "code": "603156"}],
    "食品加工制造": [{"name": "海天味业", "code": "603288"}, {"name": "安井食品", "code": "603345"}, {"name": "中炬高新", "code": "600872"}, {"name": "洽洽食品", "code": "002557"}],
    "电力": [{"name": "长江电力", "code": "600900"}, {"name": "华能国际", "code": "600011"}, {"name": "中国核电", "code": "601985"}, {"name": "国投电力", "code": "600886"}],
    "电力设备": [{"name": "宁德时代", "code": "300750"}, {"name": "阳光电源", "code": "300274"}, {"name": "国电南瑞", "code": "600406"}, {"name": "特变电工", "code": "600089"}],
    "油气开采及服务": [{"name": "中国石油", "code": "601857"}, {"name": "中国海油", "code": "600938"}, {"name": "中国石化", "code": "600028"}, {"name": "广汇能源", "code": "600256"}],
    "煤炭开采加工": [{"name": "中国神华", "code": "601088"}, {"name": "陕西煤业", "code": "601225"}, {"name": "兖矿能源", "code": "600188"}, {"name": "中煤能源", "code": "601898"}],
    "工业金属": [{"name": "紫金矿业", "code": "601899"}, {"name": "洛阳钼业", "code": "603993"}, {"name": "江西铜业", "code": "600362"}, {"name": "云南铜业", "code": "000878"}],
    "贵金属": [{"name": "山东黄金", "code": "600547"}, {"name": "中金黄金", "code": "600489"}, {"name": "银泰黄金", "code": "000975"}, {"name": "赤峰黄金", "code": "600988"}],
    "钢铁": [{"name": "宝钢股份", "code": "600019"}, {"name": "包钢股份", "code": "600010"}, {"name": "华菱钢铁", "code": "000932"}, {"name": "中信特钢", "code": "000708"}],
    "造纸": [{"name": "太阳纸业", "code": "002078"}, {"name": "晨鸣纸业", "code": "000488"}, {"name": "博汇纸业", "code": "600966"}, {"name": "山鹰国际", "code": "600567"}],
    "家居用品": [{"name": "欧派家居", "code": "603833"}, {"name": "顾家家居", "code": "603816"}, {"name": "索菲亚", "code": "002572"}, {"name": "志邦家居", "code": "603801"}],
    "服装家纺": [{"name": "海澜之家", "code": "600398"}, {"name": "森马服饰", "code": "002563"}, {"name": "雅戈尔", "code": "600177"}, {"name": "太平鸟", "code": "603877"}],
    "化学纤维": [{"name": "桐昆股份", "code": "601233"}, {"name": "荣盛石化", "code": "002493"}, {"name": "恒力石化", "code": "600346"}, {"name": "新凤鸣", "code": "603225"}],
    "塑料": [{"name": "金发科技", "code": "600143"}, {"name": "普利特", "code": "002324"}, {"name": "国恩股份", "code": "002768"}],
    "包装印刷": [{"name": "裕同科技", "code": "002831"}, {"name": "劲嘉股份", "code": "002191"}, {"name": "奥瑞金", "code": "002701"}],
    "物流": [{"name": "顺丰控股", "code": "002352"}, {"name": "圆通速递", "code": "600233"}, {"name": "韵达股份", "code": "002120"}, {"name": "德邦股份", "code": "603056"}],
    "机场航运": [{"name": "上海机场", "code": "600009"}, {"name": "中国国航", "code": "601111"}, {"name": "南方航空", "code": "600029"}, {"name": "春秋航空", "code": "601021"}],
    "港口航运": [{"name": "中远海控", "code": "601919"}, {"name": "上港集团", "code": "600018"}, {"name": "宁波港", "code": "601018"}, {"name": "招商轮船", "code": "601872"}],
    "公路铁路运输": [{"name": "京沪高铁", "code": "601816"}, {"name": "大秦铁路", "code": "601006"}, {"name": "招商公路", "code": "001965"}, {"name": "宁沪高速", "code": "600377"}],
    "景点及旅游": [{"name": "中国中免", "code": "601888"}, {"name": "宋城演艺", "code": "300144"}, {"name": "中青旅", "code": "600138"}, {"name": "众信旅游", "code": "002707"}],
    "酒店及餐饮": [{"name": "锦江酒店", "code": "600754"}, {"name": "首旅酒店", "code": "600258"}, {"name": "君亭酒店", "code": "301073"}],
    "传媒": [{"name": "分众传媒", "code": "002027"}, {"name": "芒果超媒", "code": "300413"}, {"name": "三七互娱", "code": "002555"}, {"name": "完美世界", "code": "002624"}],
    "游戏": [{"name": "腾讯未上市", "code": ""}, {"name": "网易未上市", "code": ""}, {"name": "三七互娱", "code": "002555"}, {"name": "世纪华通", "code": "002602"}],
    "计算机应用": [{"name": "金山办公", "code": "688111"}, {"name": "用友网络", "code": "600588"}, {"name": "广联达", "code": "002410"}, {"name": "深信服", "code": "300454"}],
    "计算机设备": [{"name": "海康威视", "code": "002415"}, {"name": "大华股份", "code": "002236"}, {"name": "同方股份", "code": "600100"}, {"name": "浪潮信息", "code": "000977"}],
    "消费电子": [{"name": "立讯精密", "code": "002475"}, {"name": "歌尔股份", "code": "002241"}, {"name": "传音控股", "code": "688036"}, {"name": "蓝思科技", "code": "300433"}],
    "光学光电子": [{"name": "京东方A", "code": "000725"}, {"name": "TCL科技", "code": "000100"}, {"name": "三安光电", "code": "600703"}, {"name": "利亚德", "code": "300296"}],
    "国防军工": [{"name": "中国船舶", "code": "600150"}, {"name": "中航沈飞", "code": "600760"}, {"name": "中国重工", "code": "601989"}, {"name": "航发动力", "code": "600893"}],
    "自动化设备": [{"name": "汇川技术", "code": "300124"}, {"name": "埃斯顿", "code": "002747"}, {"name": "机器人", "code": "300024"}, {"name": "绿的谐波", "code": "688017"}],
    "仪器仪表": [{"name": "川仪股份", "code": "603100"}, {"name": "精测电子", "code": "300567"}, {"name": "汉威科技", "code": "300007"}, {"name": "柯力传感", "code": "603662"}],
    "金属新材料": [{"name": "宝钛股份", "code": "600456"}, {"name": "西部超导", "code": "688122"}, {"name": "有研新材", "code": "600206"}],
    "建筑材料": [{"name": "海螺水泥", "code": "600585"}, {"name": "东方雨虹", "code": "002271"}, {"name": "北新建材", "code": "000786"}, {"name": "华新水泥", "code": "600801"}],
    "建筑装饰": [{"name": "中国建筑", "code": "601668"}, {"name": "中国中铁", "code": "601390"}, {"name": "中国铁建", "code": "601186"}, {"name": "中国交建", "code": "601800"}],
    "养殖业": [{"name": "牧原股份", "code": "002714"}, {"name": "温氏股份", "code": "300498"}, {"name": "新希望", "code": "000876"}, {"name": "正邦科技", "code": "002157"}],
    "种植业与林业": [{"name": "隆平高科", "code": "000998"}, {"name": "大北农", "code": "002385"}, {"name": "北大荒", "code": "600598"}, {"name": "登海种业", "code": "002041"}],
    "农产品加工": [{"name": "金龙鱼", "code": "300999"}, {"name": "中粮糖业", "code": "600737"}, {"name": "道道全", "code": "002852"}],
    "零售": [{"name": "永辉超市", "code": "601933"}, {"name": "家家悦", "code": "603708"}, {"name": "重庆百货", "code": "600729"}, {"name": "红旗连锁", "code": "002697"}],
    "互联网电商": [{"name": "国联股份", "code": "603613"}, {"name": "壹网壹创", "code": "300792"}, {"name": "值得买", "code": "300785"}],
    "美容护理": [{"name": "爱美客", "code": "300896"}, {"name": "珀莱雅", "code": "603605"}, {"name": "贝泰妮", "code": "300957"}, {"name": "上海家化", "code": "600315"}],
    "汽车整车": [{"name": "比亚迪", "code": "002594"}, {"name": "长城汽车", "code": "601633"}, {"name": "长安汽车", "code": "000625"}, {"name": "上汽集团", "code": "600104"}],
    "工程机械": [{"name": "三一重工", "code": "600031"}, {"name": "中联重科", "code": "000157"}, {"name": "徐工机械", "code": "000425"}, {"name": "恒立液压", "code": "601100"}],
    "农产品加工": [{"name": "金龙鱼", "code": "300999"}, {"name": "东凌国际", "code": "000893"}, {"name": "京粮控股", "code": "000505"}],
}


def get_sector_constituents(sector: str, top: int = 5) -> list[dict]:
    """
    某行业板块的前 top 只成分股（名称+代码）。多层兜底：
      1) 内置龙头股映射表 _SECTOR_LEADERS（最快、最稳，覆盖常见东财行业）
      2) akshare stock_board_industry_cons_em（实时，东财风控时可能失败）
      3) tushare ths_member（同花顺板块，需 TUSHARE_TOKEN）
    失败返回 []。用于 ① 弹窗「每个板块 3-5 只个股」。
    """
    # 1) 内置龙头股兜底（优先，避免每个板块都等慢接口）
    if sector in _SECTOR_LEADERS:
        return _SECTOR_LEADERS[sector][:top]

    # 2) akshare 实时（可能被东财风控，用短重试快速跳过）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_board_industry_cons_em(symbol=sector), attempts=1, wait=0.5)
        if df is not None and not df.empty:
            name_c = "名称" if "名称" in df.columns else None
            code_c = next((c for c in ["代码", "股票代码", "个股代码"] if c in df.columns), None)
            if name_c:
                out = []
                for _, r in df.head(top).iterrows():
                    nm = r.get(name_c)
                    if nm is None:
                        continue
                    out.append({"name": str(nm), "code": str(r.get(code_c)) if code_c and r.get(code_c) is not None else ""})
                if out:
                    return out
    except Exception as e:  # noqa: BLE001
        print(f"[cons] {sector} akshare 失败: {e}")

    # 3) tushare 同花顺板块成分股（ths_member 需要 tushare token）
    pro = _tushare_pro()
    if pro:
        try:
            # ths_member 按同花顺代码查；先尝试用板块名作为 code 查
            df = pro.ths_member(ts_code="", name=sector)
            if df is None or df.empty:
                # 再尝试直接按 ts_code（板块名）查
                df = pro.ths_member(ts_code=sector)
            if df is not None and not df.empty:
                name_c = next((c for c in ["name", "股票名称"] if c in df.columns), None)
                code_c = next((c for c in ["code", "股票代码"] if c in df.columns), None)
                if code_c:
                    out = []
                    for _, r in df.head(top).iterrows():
                        nm = r.get(name_c) if name_c else ""
                        out.append({"name": str(nm), "code": str(r.get(code_c))})
                    if out:
                        return out
        except Exception as e:  # noqa: BLE001
            print(f"[cons] {sector} tushare 失败: {e}")
    return []


def get_sector_constituents_map(sector_flow: list, n: int = 30) -> dict:
    """对流入/流出 TOP n 板块，各取 3-5 只成分股。返回 {板块名: [{name,code}]}。
    排序口径与 build_dashboard._flow_in_out 保持一致：流入按「流入资金」降序，流出按「流出资金」降序。"""
    real = [x for x in (sector_flow or []) if isinstance(x, dict) and "error" not in x]
    if not real:
        return {}
    # 兼容新旧字段
    def _net(x):
        try:
            return float(x.get("净流入") or x.get("今日主力净流入-净额") or 0)
        except Exception:
            return 0.0
    def _in(x):
        try:
            return float(x.get("流入资金", _net(x) if _net(x) >= 0 else 0))
        except Exception:
            return max(_net(x), 0)
    def _out(x):
        try:
            return float(x.get("流出资金", -_net(x) if _net(x) < 0 else 0))
        except Exception:
            return max(-_net(x), 0)

    inp = sorted(real, key=lambda x: -_in(x))[:n]
    out = sorted(real, key=lambda x: -_out(x))[:n]
    names = set(x.get("名称") for x in inp) | set(x.get("名称") for x in out)
    out_map: dict = {}
    for s in names:
        if not s:
            continue
        out_map[s] = get_sector_constituents(s, top=5)
        time.sleep(0.08)  # 礼貌限速
    return out_map


def get_a_spot_sample() -> list[dict]:
    # 主力：东财个股资金流排行
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_individual_fund_flow_rank(indicator="今日"), attempts=2)
        cols = [c for c in ["名称", "代码", "最新价", "涨跌幅", "主力净流入-净额", "主力净流入-净占比", "换手率"] if c in df.columns]
        return df[cols].head(50).to_dict(orient="records")
    except Exception:
        pass
    # 兜底：同花顺个股资金流（字段归一为东财格式，净额从万元换算为元）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_fund_flow_individual(symbol="即时"), attempts=2)

        def _num(v):
            try:
                s = str(v).replace(",", "")
                if s.endswith("亿"):
                    return float(s[:-1]) * 1e8
                if s.endswith("万"):
                    return float(s[:-1]) * 1e4
                return float(s)
            except Exception:
                return 0.0
        df["_net"] = df["净额"].map(_num)
        df = df.sort_values("_net", ascending=False)
        out = []
        for _, r in df.head(50).iterrows():
            pct = str(r.get("涨跌幅", "")).rstrip("%")
            out.append({
                "名称": r.get("股票简称"),
                "代码": str(r.get("股票代码", "")),
                "最新价": r.get("最新价"),
                "涨跌幅": float(pct) if pct not in ("", "None") else None,
                "主力净流入-净额": r["_net"],
                "换手率": r.get("换手率"),
            })
        return out
    except Exception as e:
        return [{"error": str(e)[:120]}]


def _is_bad(rows) -> bool:
    """判断一份列表数据是否『不可用』：空、或全是 error 行。"""
    if not rows or not isinstance(rows, list):
        return True
    real = [x for x in rows if isinstance(x, dict) and "error" not in x]
    return len(real) == 0


def collect_all(date: str | None = None) -> dict:
    """
    数据基准日逻辑：
    - 交易日   -> 取当日实时/盘中数据
    - 非交易日 -> 按最近一个交易日取数（涨停板等按日期接口直接传该日）；
                  排行类接口若拿空，则回退上一次成功缓存（即最后交易日收盘时 Actions 提交的快照）
    """
    ctx = get_trade_context()
    trade_date = date or ctx["trade_date"]
    prev = _load("market_snapshot") or {}  # 上一次成功快照（回退用）

    def _pick(new_rows, key):
        """新数据可用就用新的；否则回退旧快照对应字段。"""
        if not _is_bad(new_rows):
            return new_rows, False
        old = prev.get(key)
        if not _is_bad(old):
            print(f"[fallback] {key} 取数失败，回退最近交易日缓存")
            return old, True
        return new_rows, False

    us_indices, _ = _pick(get_us_indices(), "us_indices")
    a_indexes, _ = _pick(get_a_indexes(), "a_indexes")
    # ① A股板块资金流：已冻结则直接读静态文件 a_sector_flow.json（云端也随仓库可读），绝不重新抓取/覆盖
    if is_frozen("global_a_sector_flow"):
        _sf = _frozen_data("global_a_sector_flow")
        if _sf is not None:
            sector_flow, sf_stale = _sf, False
            print("[frozen] global_a_sector_flow -> 读取 a_sector_flow.json，跳过实时抓取")
            _sc = _load("a_sector_constituents")
            sector_constituents = _sc if _sc is not None else get_sector_constituents_map(_sf, n=30)
        else:
            sector_flow, sf_stale = _pick(get_sector_fund_flow(), "sector_flow")
            sector_constituents = get_sector_constituents_map(sector_flow, n=30)
    else:
        sector_flow, sf_stale = _pick(get_sector_fund_flow(), "sector_flow")
    limit_up, lu_stale = _pick(get_limit_up(trade_date), "limit_up")
    # 预拉取涨停个股日K/分时数据，供看板详情弹窗离线渲染
    try:
        lu_klines = get_limit_up_klines(limit_up)
        _save("limit_up_klines", lu_klines)
    except Exception as e:
        print(f"[collect_all] limit_up_klines 失败: {e}")
    heatmap, hm_stale = _pick(get_a_spot_sample(), "heatmap")
    breadth, br_stale = _pick(get_market_breadth(), "market_breadth")
    # 板块成分股（①弹窗用）：frozen 且冻结文件存在时已用冻结值，否则实时计算
    if not (is_frozen("global_a_sector_flow") and _load("a_sector_constituents") is not None):
        sector_constituents = get_sector_constituents_map(sector_flow, n=30)

    data = {
        "updated_at": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_ctx": {
            "is_trade_day": ctx["is_trade_day"],
            "trade_date": trade_date,
            "source": ctx["source"],
            "stale_keys": [k for k, s in
                           [("sector_flow", sf_stale), ("limit_up", lu_stale),
                            ("heatmap", hm_stale), ("market_breadth", br_stale)] if s],
        },
        "us_indices": us_indices,
        "a_indexes": a_indexes,
        "sector_flow": sector_flow,
        "limit_up": limit_up,
        "heatmap": heatmap,
        "market_breadth": breadth,
        "sector_constituents": sector_constituents,
    }
    _save("market_snapshot", data)
    return data


if __name__ == "__main__":
    print(json.dumps(collect_all(), ensure_ascii=False, indent=2, default=str))
