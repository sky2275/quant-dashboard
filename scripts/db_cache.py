"""
db_cache.py -- SQLite 统一缓存层
为数据源层提供统一的缓存接口，减少重复 API 调用（目标命中率 60%+）。

表结构：
  - trade_calendar : 交易日历（TTL 7天）
  - quote_cache    : 实时行情快照（TTL 5分钟）
  - kline_cache    : 日K线数据（TTL 1天，收盘后不变）
  - fund_flow_cache: 资金流向（TTL 1天）
  - adj_factor     : 复权因子（TTL 7天）

使用方式：
  from scripts.db_cache import DBCache
  cache = DBCache()
  cache.put_quote("600584", {"price": 85.2, ...})
  quote = cache.get_quote("600584")  # 5分钟内有效
"""
from __future__ import annotations

import os
import json
import sqlite3
import datetime as dt
from typing import Any

try:
    from zoneinfo import ZoneInfo
    _BJ_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    _BJ_TZ = None

def _bj_now() -> dt.datetime:
    return dt.datetime.now(_BJ_TZ) if _BJ_TZ else dt.datetime.now()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, "cache", "quant_cache.db")

# TTL 表（秒）
TTL = {
    "trade_calendar": 7 * 86400,   # 7天
    "quote_cache": 300,             # 5分钟
    "kline_cache": 86400,           # 1天
    "fund_flow_cache": 86400,       # 1天
    "adj_factor": 7 * 86400,       # 7天
}


class DBCache:
    """SQLite 缓存读写器，线程安全（每次操作独立连接）。"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_tables(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS trade_calendar (
                    trade_date TEXT PRIMARY KEY,
                    is_open    INTEGER,
                    source     TEXT,
                    cached_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS quote_cache (
                    symbol    TEXT,
                    trade_date TEXT,
                    payload   TEXT,
                    cached_at TEXT,
                    PRIMARY KEY (symbol, trade_date)
                );

                CREATE TABLE IF NOT EXISTS kline_cache (
                    symbol  TEXT,
                    date    TEXT,
                    open    REAL,
                    close   REAL,
                    high    REAL,
                    low     REAL,
                    volume  REAL,
                    amount  REAL,
                    pct_chg REAL,
                    cached_at TEXT,
                    PRIMARY KEY (symbol, date)
                );

                CREATE TABLE IF NOT EXISTS fund_flow_cache (
                    symbol     TEXT,
                    trade_date TEXT,
                    main_net   REAL,
                    super_large_net REAL,
                    large_net  REAL,
                    medium_net REAL,
                    small_net  REAL,
                    cached_at  TEXT,
                    PRIMARY KEY (symbol, trade_date)
                );

                CREATE TABLE IF NOT EXISTS adj_factor (
                    symbol     TEXT,
                    trade_date TEXT,
                    adj_factor REAL,
                    cached_at  TEXT,
                    PRIMARY KEY (symbol, trade_date)
                );

                CREATE INDEX IF NOT EXISTS idx_kline_symbol ON kline_cache(symbol);
                CREATE INDEX IF NOT EXISTS idx_fund_symbol ON fund_flow_cache(symbol);
            """)

    # ------------------------------------------------------------------ 交易日历
    def get_trade_calendar(self) -> list[dict] | None:
        """返回最近60天的交易日历，如果缓存过期返回 None。"""
        with self._conn() as c:
            row = c.execute(
                "SELECT MIN(cached_at) AS oldest FROM trade_calendar"
            ).fetchone()
            if not row or not row["oldest"]:
                return None
            age = (_bj_now() - dt.datetime.fromisoformat(row["oldest"])).total_seconds()
            if age > TTL["trade_calendar"]:
                return None
            rows = c.execute(
                "SELECT trade_date, is_open FROM trade_calendar "
                "ORDER BY trade_date DESC LIMIT 90"
            ).fetchall()
            return [{"trade_date": r["trade_date"], "is_open": r["is_open"]} for r in rows]

    def put_trade_calendar(self, entries: list[dict], source: str = "akshare"):
        """批量写入交易日历。entries: [{"trade_date": "20260801", "is_open": 1}, ...]"""
        now = _bj_now().isoformat()
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO trade_calendar (trade_date, is_open, source, cached_at) "
                "VALUES (?, ?, ?, ?)",
                [(e["trade_date"], e.get("is_open", 1), source, now) for e in entries]
            )
            c.commit()

    def is_trade_day(self, date_str: str | None = None) -> bool:
        """快速判断某天是否交易日（优先查缓存）。"""
        if date_str is None:
            date_str = _bj_now().strftime("%Y%m%d")
        with self._conn() as c:
            row = c.execute(
                "SELECT is_open FROM trade_calendar WHERE trade_date = ?", (date_str,)
            ).fetchone()
            if row:
                return bool(row["is_open"])
        return None  # 缓存未命中，需调 API

    # ------------------------------------------------------------------ 实时行情
    def get_quote(self, symbol: str, trade_date: str | None = None) -> dict | None:
        if trade_date is None:
            trade_date = _bj_now().strftime("%Y%m%d")
        with self._conn() as c:
            row = c.execute(
                "SELECT payload, cached_at FROM quote_cache WHERE symbol=? AND trade_date=?",
                (symbol, trade_date)
            ).fetchone()
            if not row:
                return None
            age = (_bj_now() - dt.datetime.fromisoformat(row["cached_at"])).total_seconds()
            if age > TTL["quote_cache"]:
                return None
            return json.loads(row["payload"])

    def put_quote(self, symbol: str, data: dict, trade_date: str | None = None):
        if trade_date is None:
            trade_date = _bj_now().strftime("%Y%m%d")
        now = _bj_now().isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO quote_cache (symbol, trade_date, payload, cached_at) "
                "VALUES (?, ?, ?, ?)",
                (symbol, trade_date, json.dumps(data, ensure_ascii=False), now)
            )
            c.commit()

    def put_quotes_batch(self, quotes: list[dict]):
        """批量写入行情。quotes: [{"symbol": "600584", "price": 85.2, ...}, ...]"""
        now = _bj_now().isoformat()
        td = _bj_now().strftime("%Y%m%d")
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO quote_cache (symbol, trade_date, payload, cached_at) "
                "VALUES (?, ?, ?, ?)",
                [(q["symbol"], td, json.dumps(q, ensure_ascii=False), now) for q in quotes]
            )
            c.commit()

    # ------------------------------------------------------------------ K线数据
    def get_klines(self, symbol: str, days: int = 250) -> list[dict] | None:
        """获取最近 N 天K线。如果缓存全命中返回列表，否则返回 None。"""
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(cached_at) AS latest FROM kline_cache WHERE symbol=?", (symbol,)
            ).fetchone()
            if not row or not row["latest"]:
                return None
            age = (_bj_now() - dt.datetime.fromisoformat(row["latest"])).total_seconds()
            if age > TTL["kline_cache"]:
                return None
            rows = c.execute(
                "SELECT date, open, close, high, low, volume, amount, pct_chg "
                "FROM kline_cache WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (symbol, days)
            ).fetchall()
            if not rows:
                return None
            return [{"date": r["date"], "open": r["open"], "close": r["close"],
                     "high": r["high"], "low": r["low"], "volume": r["volume"],
                     "amount": r["amount"], "pct_chg": r["pct_chg"]} for r in reversed(rows)]

    def put_klines(self, symbol: str, klines: list[dict]):
        """批量写入K线。klines: [{"date": "2026-08-01", "open": ..., "close": ..., ...}, ...]"""
        now = _bj_now().isoformat()
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO kline_cache "
                "(symbol, date, open, close, high, low, volume, amount, pct_chg, cached_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(symbol, k["date"], k.get("open"), k.get("close"), k.get("high"),
                  k.get("low"), k.get("volume"), k.get("amount"), k.get("pct_chg"), now)
                 for k in klines]
            )
            c.commit()

    # ------------------------------------------------------------------ 资金流向
    def get_fund_flow(self, symbol: str, trade_date: str | None = None) -> dict | None:
        if trade_date is None:
            trade_date = _bj_now().strftime("%Y%m%d")
        with self._conn() as c:
            row = c.execute(
                "SELECT main_net, super_large_net, large_net, medium_net, small_net, cached_at "
                "FROM fund_flow_cache WHERE symbol=? AND trade_date=?",
                (symbol, trade_date)
            ).fetchone()
            if not row:
                return None
            age = (_bj_now() - dt.datetime.fromisoformat(row["cached_at"])).total_seconds()
            if age > TTL["fund_flow_cache"]:
                return None
            return {"main_net": row["main_net"], "super_large_net": row["super_large_net"],
                    "large_net": row["large_net"], "medium_net": row["medium_net"],
                    "small_net": row["small_net"]}

    def put_fund_flow(self, symbol: str, data: dict, trade_date: str | None = None):
        if trade_date is None:
            trade_date = _bj_now().strftime("%Y%m%d")
        now = _bj_now().isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO fund_flow_cache "
                "(symbol, trade_date, main_net, super_large_net, large_net, medium_net, small_net, cached_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (symbol, trade_date, data.get("main_net"), data.get("super_large_net"),
                 data.get("large_net"), data.get("medium_net"), data.get("small_net"), now)
            )
            c.commit()

    # ------------------------------------------------------------------ 复权因子
    def get_adj_factor(self, symbol: str, trade_date: str | None = None) -> float | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT adj_factor, cached_at FROM adj_factor WHERE symbol=? AND trade_date=?",
                (symbol, trade_date or _bj_now().strftime("%Y%m%d"))
            ).fetchone()
            if not row:
                return None
            age = (_bj_now() - dt.datetime.fromisoformat(row["cached_at"])).total_seconds()
            if age > TTL["adj_factor"]:
                return None
            return row["adj_factor"]

    def put_adj_factor(self, symbol: str, trade_date: str, adj: float):
        now = _bj_now().isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO adj_factor (symbol, trade_date, adj_factor, cached_at) "
                "VALUES (?, ?, ?, ?)",
                (symbol, trade_date, adj, now)
            )
            c.commit()

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict:
        """返回各表行数和数据库大小。"""
        tables = ["trade_calendar", "quote_cache", "kline_cache", "fund_flow_cache", "adj_factor"]
        result = {}
        with self._conn() as c:
            for t in tables:
                row = c.execute(f"SELECT COUNT(*) AS cnt FROM {t}").fetchone()
                result[t] = row["cnt"]
        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        result["db_size_kb"] = round(db_size / 1024, 1)
        return result

    def cleanup(self, days: int = 90):
        """清理超过 N 天的旧数据。"""
        cutoff = (_bj_now() - dt.timedelta(days=days)).strftime("%Y%m%d")
        with self._conn() as c:
            for t in ["quote_cache", "kline_cache", "fund_flow_cache", "adj_factor"]:
                c.execute(f"DELETE FROM {t} WHERE trade_date < ?", (cutoff,))
            c.commit()


# 全局单例
_cache: DBCache | None = None

def get_cache() -> DBCache:
    global _cache
    if _cache is None:
        _cache = DBCache()
    return _cache
