"""
feed.py —— 真实行情数据层（云端 Actions / 本机均可运行）
数据源：akshare（东方财富+同花顺源，免积分）为主，tushare（基本面）为辅。
所有函数带 try/except，单点失败不拖垮整体；结果缓存为 JSON 供看板读取。
本文件只负责“拿数据”，不含任何交易判断。
"""
from __future__ import annotations
import os
import json
import datetime as dt
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


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


def get_us_indices() -> list[dict]:
    try:
        import akshare as ak
        df = ak.stock_us_spot_em()
        out = []
        for n in ["纳斯达克", "道琼斯", "标普500", "费城半导体"]:
            row = df[df["名称"] == n]
            if not row.empty:
                r = row.iloc[0]
                out.append({"name": n, "price": r.get("最新价"),
                            "change_pct": r.get("涨跌幅")})
        return out
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_us_stock(symbol: str) -> dict | None:
    try:
        import akshare as ak
        df = ak.stock_us_spot_em()
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
        import akshare as ak
        df = ak.stock_zh_index_spot_em()
        out = []
        for n in ["上证指数", "深证成指", "创业板指", "科创50"]:
            row = df[df["名称"] == n]
            if not row.empty:
                r = row.iloc[0]
                out.append({"name": n, "price": r.get("最新价"),
                            "change_pct": r.get("涨跌幅")})
        return out
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_sector_fund_flow() -> list[dict]:
    try:
        import akshare as ak
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        cols = [c for c in ["名称", "今日主力净流入-净额", "今日主力净流入-净占比", "涨跌幅"] if c in df.columns]
        return df[cols].head(30).to_dict(orient="records")
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_limit_up(date: str | None = None) -> list[dict]:
    if date is None:
        date = dt.date.today().strftime("%Y%m%d")
    try:
        import akshare as ak
        df = ak.stock_zt_pool_em(date=date)
        if df is None or df.empty:
            return []
        cols = [c for c in ["名称", "代码", "涨跌幅", "成交额", "连板数", "封单资金", "所属行业"] if c in df.columns]
        return df[cols].to_dict(orient="records")
    except Exception as e:
        return [{"error": str(e)[:120]}]


def get_a_spot_sample() -> list[dict]:
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        cols = [c for c in ["名称", "代码", "最新价", "涨跌幅", "主力净流入-净额", "主力净流入-净占比", "换手率"] if c in df.columns]
        return df[cols].head(30).to_dict(orient="records")
    except Exception as e:
        return [{"error": str(e)[:120]}]


def collect_all(date: str | None = None) -> dict:
    data = {
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "us_indices": get_us_indices(),
        "a_indexes": get_a_indexes(),
        "sector_flow": get_sector_fund_flow(),
        "limit_up": get_limit_up(date),
        "heatmap": get_a_spot_sample(),
    }
    _save("market_snapshot", data)
    return data


if __name__ == "__main__":
    print(json.dumps(collect_all(), ensure_ascii=False, indent=2, default=str))
