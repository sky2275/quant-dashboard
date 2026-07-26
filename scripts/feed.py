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
    """tushare 批量取 RSI(14)/MACD/量比/换手。2 次调用覆盖全部标的。"""
    out: dict = {c: {} for c in ts_codes}
    if not ts_codes:
        return out
    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=70)).strftime("%Y%m%d")
    # 1) RSI + MACD 来自 daily
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
        except Exception:
            pass
        rec["volume_ratio"] = name_vr.get(name)
        if rec.get("turnover_rate") is None:
            rec["turnover_rate"] = name_turn.get(name)
        out[ts_code] = rec
        time.sleep(0.05)
    return out


def get_indicators(items: list[tuple]) -> dict:
    """
    批量获取技术指标（RSI14 / MACD / 量比 / 换手）。
    items: list of (name, ts_code)，ts_code 形如 '600584.SH'。
    优先 tushare（2 次批量调用）；否则 akshare 逐只兜底；少量缺失自动补齐。
    返回 {ts_code: {rsi, macd_dif, macd_dea, macd_hist, volume_ratio, turnover_rate}}
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


def collect_all(date: str | None = None) -> dict:
    trade_date = (date or dt.date.today().strftime("%Y%m%d"))
    heatmap = get_a_spot_sample()
    data = {
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "us_indices": get_us_indices(),
        "a_indexes": get_a_indexes(),
        "sector_flow": get_sector_fund_flow(),
        "limit_up": get_limit_up(date),
        "heatmap": heatmap,
    }
    _save("market_snapshot", data)
    return data


if __name__ == "__main__":
    print(json.dumps(collect_all(), ensure_ascii=False, indent=2, default=str))
