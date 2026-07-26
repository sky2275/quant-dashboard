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
        today = dt.date.today()
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
        start = (dt.date.today() - dt.timedelta(days=75)).strftime("%Y%m%d")
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
    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=70)).strftime("%Y%m%d")
    # 1) RSI + MACD + 周/月动量来自 daily
    try:
        df = pro.daily(ts_code=",".join(ts_codes), start_date=start, end_date=end)
        if df is not None and not df.empty and "close" in df.columns:
            for code, g in df.groupby("ts_code"):
                if code not in out:
                    out[code] = {}
                closes = g.sort_values("trade_date")["close"].tolist()
                out[code]["rsi"] = compute_rsi(closes, 14)
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
    trade_date = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=75)).strftime("%Y%m%d")
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
    优先 tushare（3 次批量调用：daily / daily_basic / moneyflow）；否则 akshare 逐只兜底；少量缺失自动补齐。
    返回 {ts_code: {rsi, macd_dif, macd_dea, macd_hist, volume_ratio, turnover_rate,
                     main_flow(元), week_pct, month_pct, score(0-100)}}
    """
    valid = [(n, t) for n, t in items if t]
    if not valid:
        return {}
    pro = _tushare_pro()
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
        return out
    return _akshare_indicators(valid)


def enrich_heatmap(heat: list, trade_date: str | None = None) -> list:
    """给资金流前 N 名补上真实 RSI / 量比。失败的行留 None（看板显示 '—'），不拖垮整体。"""
    real = [x for x in heat if isinstance(x, dict) and "error" not in x]
    if not real:
        return heat
    if trade_date is None:
        trade_date = dt.date.today().strftime("%Y%m%d")
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
                "change_pct": v["change_pct"]} for c, v in q.items() if c in _A_INDEX_CODES]
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
def get_sector_fund_flow() -> list[dict]:
    # 主力：东财（海外机房易断连，带重试）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_sector_fund_flow_rank(
            indicator="今日", sector_type="行业资金流"), attempts=2)
        cols = [c for c in ["名称", "今日主力净流入-净额", "今日主力净流入-净占比", "涨跌幅"] if c in df.columns]
        return df[cols].head(50).to_dict(orient="records")
    except Exception:
        pass
    # 兜底：同花顺行业资金流（字段归一为东财格式，净额从亿元换算为元）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_fund_flow_industry(symbol="即时"), attempts=2)
        df = df.sort_values("净额", ascending=False)
        out = []
        for _, r in df.head(50).iterrows():
            out.append({
                "名称": r.get("行业"),
                "今日主力净流入-净额": float(r.get("净额", 0)) * 1e8,
                "涨跌幅": r.get("行业-涨跌幅"),
                "领涨股": r.get("领涨股"),
            })
        return out
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_limit_up(date: str | None = None) -> list[dict]:
    if date is None:
        date = dt.date.today().strftime("%Y%m%d")
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zt_pool_em(date=date))
        if df is None or df.empty:
            return []
        cols = [c for c in ["名称", "代码", "涨跌幅", "成交额", "连板数", "封单资金", "所属行业"] if c in df.columns]
        return df[cols].to_dict(orient="records")
    except Exception as e:
        return [{"error": str(e)[:120]}]


def _board_limit(name: str, code: str) -> float:
    """按名称/代码判断涨跌停幅度(%)：ST=5，创业板/科创板/北交所=20，其余=10。"""
    if name and "ST" in str(name).upper():
        return 5.0
    lead = str(code)[:1]
    if lead in ("3", "8", "4") or str(code).startswith("688"):
        return 20.0
    return 10.0


def get_market_breadth() -> dict:
    """
    两市(沪+深，不含北交所) 总成交额、上涨/下跌家数、跌停家数。
    - 成交额：沪(上证指数)+深(深证成指) 指数成交额之和（轻量接口，最稳）
    - 涨跌家数/跌停：全市场快照 stock_zh_a_spot_em() 一次调用，按板块真实涨跌幅判定跌停
    返回 {'amount'(元), 'up_count', 'down_count', 'limit_down_count'}（缺失项为 None）。
    """
    out = {"amount": None, "up_count": None, "down_count": None, "limit_down_count": None}
    # 1) 成交额：指数快照（轻量，几乎不会失败）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zh_index_spot_em(), attempts=2, wait=1)
        if df is not None and not df.empty:
            amt_cols = [c for c in ["成交额", "成交金额"] if c in df.columns]
            name_col = "名称" if "名称" in df.columns else "指数名称"
            if amt_cols and name_col in df.columns:
                amt = 0.0
                for _, r in df.iterrows():
                    nm = str(r.get(name_col, ""))
                    if nm in ("上证指数", "深证成指"):
                        try:
                            amt += float(r.get(amt_cols[0]))
                        except Exception:
                            pass
                if amt:
                    out["amount"] = round(amt, 2)
    except Exception as e:  # noqa: BLE001
        print(f"[breadth] 指数成交额失败: {e}")
    # 2) 涨跌家数 + 跌停：全市场快照（按板块真实幅度判定跌停）
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_zh_a_spot_em(), attempts=3, wait=1.5)
        if df is not None and not df.empty and "涨跌幅" in df.columns and "代码" in df.columns:
            df = df.copy()
            df["_lead"] = df["代码"].astype(str).str[:1]
            main = df[df["_lead"].isin(["6", "0", "3"])]  # 沪(6)+深(0/3)，剔除北交所
            up = down = dt_count = 0
            for _, r in main.iterrows():
                try:
                    p = float(r.get("涨跌幅"))
                except Exception:
                    continue
                code = str(r.get("代码", ""))
                name = str(r.get("名称", ""))
                if p > 0:
                    up += 1
                elif p < 0:
                    down += 1
                lim = _board_limit(name, code)
                if p <= -(lim - 0.25):
                    dt_count += 1
            out["up_count"] = up
            out["down_count"] = down
            out["limit_down_count"] = dt_count
    except Exception as e:  # noqa: BLE001
        print(f"[breadth] 全市场快照失败: {e}")
    return out


def get_sector_constituents(sector: str, top: int = 5) -> list[dict]:
    """
    某行业板块的前 top 只成分股（名称+代码）。来源 akshare stock_board_industry_cons_em。
    失败返回 []。用于 ① 弹窗「每个板块 3-5 只个股」。
    """
    try:
        import akshare as ak
        df = _retry(lambda: ak.stock_board_industry_cons_em(symbol=sector), attempts=2, wait=1)
        if df is None or df.empty:
            return []
        name_c = "名称" if "名称" in df.columns else None
        code_c = next((c for c in ["代码", "股票代码", "个股代码"] if c in df.columns), None)
        if not name_c:
            return []
        out = []
        for _, r in df.head(top).iterrows():
            nm = r.get(name_c)
            if nm is None:
                continue
            out.append({"name": str(nm), "code": str(r.get(code_c)) if code_c and r.get(code_c) is not None else ""})
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[cons] {sector} 成分股失败: {e}")
        return []


def get_sector_constituents_map(sector_flow: list, n: int = 30) -> dict:
    """对流入/流出 TOP n 板块，各取 3-5 只成分股。返回 {板块名: [{name,code}]}。"""
    real = [x for x in (sector_flow or []) if isinstance(x, dict) and "error" not in x]
    if not real:
        return {}
    inp, out = [], []
    for x in real:
        try:
            nv = float(x.get("今日主力净流入-净额") or 0)
        except Exception:
            nv = 0
        (inp if nv >= 0 else out).append(x.get("名称"))
    names = set(inp[:n]) | set(out[:n])
    out_map: dict = {}
    for s in names:
        if not s:
            continue
        out_map[s] = get_sector_constituents(s, top=5)
        time.sleep(0.15)  # 礼貌限速，避免东财风控
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
    sector_flow, sf_stale = _pick(get_sector_fund_flow(), "sector_flow")
    limit_up, lu_stale = _pick(get_limit_up(trade_date), "limit_up")
    heatmap, hm_stale = _pick(get_a_spot_sample(), "heatmap")
    breadth, br_stale = _pick(get_market_breadth(), "market_breadth")
    # 板块成分股（①弹窗用）：对流入/流出 TOP30 板块各取 3-5 只个股
    sector_constituents = get_sector_constituents_map(sector_flow, n=30)

    data = {
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
