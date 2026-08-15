#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_fetcher.py — 稳定的量化数据获取脚本（akshare / tushare 双后端）

目的
----
在「已安装 akshare 且已配置 TUSHARE_TOKEN」的目标环境下，稳定、可重复地执行
*指定的数据获取任务*。脚本对每一次调用都明确声明三件事：

  1. 数据源       --source akshare | tushare
  2. 所需参数      --task <任务名> 以及对应 --start/--end/--code/--date 等
  3. 输出格式      --format json（默认）| csv，写入 --out 文件

并内建以下可靠性机制，避免“每次执行结果不一致或报错”：

  * 重试退避        retry()：指数退避 + 抖动，覆盖网络/限流/空结果
  * 异常归一化      所有失败统一包装为 DataFetchError，附带上下文
  * 结果缓存        按 (task, source, 参数) 哈希落盘，TTL 内直接复用，
                    保证可重复、避免重复打 API 触发限流
  * 结构归一化      不同后端返回的字段名/类型差异统一成固定 schema
  * 确定性输出      JSON 排序键、记录按主键排序；--frozen-meta 可冻结时间戳
  * API 漂移容忍     akshare 多个候选函数名自动探测，缺失即明确报错

支持的 task
-----------
  trade_calendar   交易日历（tushare 权威 / akshare 备选）
  daily_kline      单只标的日线（tushare pro_bar / akshare stock_zh_a_hist）
  sector_fund_flow 行业板块资金流（主要 akshare；tushare 暂不支持）
  stock_spot       全 A 实时快照（主要 akshare；tushare 暂不支持）

离线自检（无需网络/依赖）
------------------------
  python data_fetcher.py --self-test

用法示例
--------
  # 交易日历（tushare 权威源），落库到 cache/trade_calendar.json
  python data_fetcher.py --task trade_calendar --source tushare \
      --start 20260101 --end 20261231 --out cache/trade_calendar.json

  # 单只股票日线（前复权）
  python data_fetcher.py --task daily_kline --source tushare \
      --code 600519.SH --start 20260101 --end 20260815 \
      --adj qfq --out cache/kline_600519.json

  # 行业板块资金流（akshare）
  python data_fetcher.py --task sector_fund_flow --source akshare \
      --date 20260814 --out cache/sector_fund_flow.json

  # 复用缓存、强制刷新、冻结元数据做字节级可重复输出
  python data_fetcher.py --task trade_calendar --source tushare \
      --start 20260101 --end 20261231 --out cache/trade_calendar.json \
      --no-cache --frozen-meta 2026-08-15T00:00:00
"""
from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import logging
import os
import random
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

LOG = logging.getLogger("data_fetcher")

SCHEMA_VERSION = 1
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE_DIR = os.path.join(REPO_ROOT, "cache", ".fetch_cache")


# --------------------------------------------------------------------------- #
# 异常与重试
# --------------------------------------------------------------------------- #
class DataFetchError(Exception):
    """所有数据获取失败的统一异常类型。"""


def retry(
    max_attempts: int = 4,
    base_delay: float = 1.5,
    max_delay: float = 30.0,
    jitter: float = 0.3,
    exceptions: Sequence[type] = (Exception,),
) -> Callable:
    """指数退避 + 抖动的重试装饰器。

    仅对 ``exceptions`` 中声明的异常重试；重试耗尽后抛出 DataFetchError，
    并保留最后一次原始异常作为 __cause__，便于排查根因。
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except tuple(exceptions) as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay *= 1.0 + random.uniform(-jitter, jitter)
                    LOG.warning(
                        "调用 %s 失败（第 %d/%d 次）：%s；%.1fs 后重试",
                        fn.__name__, attempt, max_attempts, exc, delay,
                    )
                    time.sleep(max(delay, 0.0))
            raise DataFetchError(
                f"{fn.__name__} 重试 {max_attempts} 次仍失败：{last_exc}"
            ) from last_exc

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# 通用工具：字段选取 / 类型归一
# --------------------------------------------------------------------------- #
def _pick(row: Dict[str, Any], names: Sequence[str]) -> Any:
    """按候选列名顺序取第一个存在且非空的值。"""
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def _to_num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == 1
    return str(v).strip().lower() in ("1", "1.0", "true", "t", "y", "yes", "open")


def _maybe_num(v: Any, key: str, hints: Sequence[str]) -> Any:
    """数值列转 float，否则原样保留。"""
    if isinstance(v, (int, float)):
        return _to_num(v)
    if any(h in str(key) for h in hints):
        return _to_num(v)
    return v


def _norm_date(v: Any) -> Optional[str]:
    """把各种日期形态归一成 YYYYMMDD（8 位字符串）。"""
    if v is None:
        return None
    s = str(v).strip().replace("-", "").replace("/", "").replace(" ", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else (digits if digits else None)


def _records_from(df: Any) -> List[Dict[str, Any]]:
    """akshare / tushare 返回 DataFrame；统一转成 list[dict]。"""
    if df is None:
        raise DataFetchError("数据源返回 None")
    if hasattr(df, "to_dict"):
        if getattr(df, "empty", False):
            raise DataFetchError("数据源返回空 DataFrame")
        return df.to_dict("records")
    if isinstance(df, list):
        if not df:
            raise DataFetchError("数据源返回空列表")
        return df
    raise DataFetchError(f"不支持的返回类型：{type(df)}")


# --------------------------------------------------------------------------- #
# 结构归一化：把不同后端差异统一成固定 schema
# --------------------------------------------------------------------------- #
def norm_trade_calendar(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        d = _norm_date(_pick(row, ["cal_date", "date", "trade_date",
                                   "calendar_date", "trading_date"]))
        if not d:
            continue
        out.append({"date": d, "is_open": _to_bool(_pick(row, ["is_open", "open"]))})
    out.sort(key=lambda x: x["date"])
    return out


def norm_kline(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        d = _norm_date(_pick(row, ["trade_date", "date", "datetime", "时间"]))
        if not d:
            continue
        out.append({
            "date": d,
            "open": _to_num(_pick(row, ["open", "开盘"])),
            "high": _to_num(_pick(row, ["high", "最高"])),
            "low": _to_num(_pick(row, ["low", "最低"])),
            "close": _to_num(_pick(row, ["close", "收盘"])),
            "volume": _to_num(_pick(row, ["vol", "volume", "成交量"])),
        })
    out.sort(key=lambda x: x["date"])
    return out


# 板块资金流：数值列统一转 float，板块名统一为 sector
_NUM_COL_HINTS = ("净流入", "净流出", "主力", "涨跌幅", "成交额", "成交量", "净额", "占比")


def norm_sector_fund_flow(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        name = _pick(row, ["名称", "板块名称", "sector", "name", "行业"])
        item: Dict[str, Any] = {"sector": str(name) if name is not None else f"row{idx}"}
        for k, v in row.items():
            if k in ("名称", "板块名称", "sector", "name", "行业"):
                continue
            item[k] = _maybe_num(v, k, _NUM_COL_HINTS)
        out.append(item)
    out.sort(key=lambda x: x.get("sector", ""))
    return out


def norm_stock_spot(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        code = _pick(row, ["代码", "code", "symbol", "ts_code"])
        name = _pick(row, ["名称", "name"])
        if code is None and name is None:
            continue
        item: Dict[str, Any] = {
            "code": str(code) if code is not None else "",
            "name": str(name) if name is not None else "",
        }
        for k, v in row.items():
            if k in ("代码", "code", "symbol", "ts_code", "名称", "name"):
                continue
            item[k] = _maybe_num(v, k, ("涨", "跌", "价", "量", "额", "幅", "pe", "pb"))
        out.append(item)
    out.sort(key=lambda x: x.get("code", "") or x.get("name", ""))
    return out


# --------------------------------------------------------------------------- #
# akshare 后端：候选函数名自动探测（容忍 API 改名）
# --------------------------------------------------------------------------- #
def _ak_func(*candidates: str) -> Tuple[Callable, str]:
    try:
        import akshare as ak  # 延迟导入：本环境未必安装
    except Exception as exc:  # pragma: no cover
        raise DataFetchError(f"无法导入 akshare：{exc}") from exc
    for name in candidates:
        fn = getattr(ak, name, None)
        if callable(fn):
            return fn, name
    raise DataFetchError(f"akshare 未找到可用函数（候选：{', '.join(candidates)}）")


def _require_tushare() -> Any:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise DataFetchError(
            "未配置 TUSHARE_TOKEN：请 `export TUSHARE_TOKEN=你的token` 后重试"
        )
    try:
        import tushare as ts
    except Exception as exc:  # pragma: no cover
        raise DataFetchError(f"无法导入 tushare：{exc}") from exc
    ts.set_token(token)
    return ts.pro_api()


# --------------------------------------------------------------------------- #
# 各任务的具体获取实现（均带重试）
# --------------------------------------------------------------------------- #
@retry()
def fetch_trade_calendar(source: str, start: str, end: str) -> Tuple[list, str]:
    if source == "tushare":
        pro = _require_tushare()
        df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
        rows = _records_from(df)
        return norm_trade_calendar(rows), "tushare.trade_cal"
    if source == "akshare":
        fn, name = _ak_func("tool_trade_cal", "trade_cal")
        df = fn(exchange="SSE", start_date=start, end_date=end)
        rows = _records_from(df)
        return norm_trade_calendar(rows), f"akshare.{name}"
    raise DataFetchError(f"不支持的 source：{source}")


@retry()
def fetch_daily_kline(source: str, code: str, start: str, end: str,
                      adj: str = "qfq") -> Tuple[list, str]:
    if source == "tushare":
        pro = _require_tushare()
        df = pro.bar(ts_code=code, start_date=start, end_date=end,
                     adj=adj or "", asset="E") if hasattr(pro, "bar") \
            else __import__("tushare").pro_bar(
                ts_code=code, start_date=start, end_date=end, adj=adj or "", asset="E")
        rows = _records_from(df)
        return norm_kline(rows), "tushare.pro_bar"
    if source == "akshare":
        sym = code.split(".")[0]
        fn, name = _ak_func("stock_zh_a_hist")
        adj_map = {"qfq": "qfq", "hfq": "hfq", "": "", "none": ""}
        df = fn(symbol=sym, period="daily", start_date=start, end_date=end,
                adjust=adj_map.get(adj, adj or ""))
        rows = _records_from(df)
        return norm_kline(rows), f"akshare.{name}"
    raise DataFetchError(f"不支持的 source：{source}")


@retry()
def fetch_sector_fund_flow(source: str, date: str) -> Tuple[list, str]:
    if source == "tushare":
        raise DataFetchError("sector_fund_flow 暂不支持 tushare 源，请改用 --source akshare")
    if source == "akshare":
        fn, name = _ak_func("stock_sector_fund_flow_rank")
        # indicator/取值在不同版本略有差异，按顺序尝试
        last_exc: Optional[BaseException] = None
        for indicator in ("今日", "最新"):
            try:
                df = fn(indicator=indicator, sector_type="行业资金流")
                rows = _records_from(df)
                return norm_sector_fund_flow(rows), f"akshare.{name}:{indicator}"
            except Exception as exc:  # 继续尝试下一个取值
                last_exc = exc
        raise DataFetchError(f"akshare 板块资金流获取失败：{last_exc}")
    raise DataFetchError(f"不支持的 source：{source}")


@retry()
def fetch_stock_spot(source: str, limit: Optional[int] = None) -> Tuple[list, str]:
    if source == "tushare":
        raise DataFetchError("stock_spot 暂不支持 tushare 源，请改用 --source akshare")
    if source == "akshare":
        fn, name = _ak_func("stock_zh_a_spot_em")
        rows = _records_from(fn())
        out = norm_stock_spot(rows)
        if limit:
            out = out[:limit]
        return out, f"akshare.{name}"
    raise DataFetchError(f"不支持的 source：{source}")


# --------------------------------------------------------------------------- #
# 任务注册表：声明每个任务所需的参数，便于 CLI 校验
# --------------------------------------------------------------------------- #
TASKS: Dict[str, Dict[str, Any]] = {
    "trade_calendar": {
        "fn": fetch_trade_calendar,
        "required": ["start", "end"],
        "optional": [],
        "help": "交易日历（tushare 权威 / akshare 备选）",
    },
    "daily_kline": {
        "fn": fetch_daily_kline,
        "required": ["code", "start", "end"],
        "optional": ["adj"],
        "help": "单只标的日线（tushare pro_bar / akshare stock_zh_a_hist）",
    },
    "sector_fund_flow": {
        "fn": fetch_sector_fund_flow,
        "required": [],
        "optional": ["date"],
        "help": "行业板块资金流（akshare）",
    },
    "stock_spot": {
        "fn": fetch_stock_spot,
        "required": [],
        "optional": ["limit"],
        "help": "全 A 实时快照（akshare）",
    },
}


# --------------------------------------------------------------------------- #
# 结果缓存：按 (task, source, 参数) 哈希落盘，保证可重复 + 限流保护
# --------------------------------------------------------------------------- #
def _cache_key(task: str, source: str, params: Dict[str, Any]) -> str:
    payload = json.dumps({"task": task, "source": source, "params": params},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_cache(cache_dir: str, key: str, ttl: int) -> Optional[Dict[str, Any]]:
    path = os.path.join(cache_dir, f"{key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except Exception:
        return None
    cached_at = blob.get("meta", {}).get("cached_at", 0)
    if ttl > 0 and (time.time() - cached_at) > ttl:
        return None
    return blob


def save_cache(cache_dir: str, key: str, blob: Dict[str, Any]) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{key}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# 输出：JSON / CSV，确定性
# --------------------------------------------------------------------------- #
def write_output(blob: Dict[str, Any], out_path: str, fmt: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if fmt == "json":
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2, sort_keys=True)
    elif fmt == "csv":
        data = blob.get("data", [])
        if not data:
            open(out_path, "w", encoding="utf-8").close()
            return
        cols: List[str] = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in data:
                w.writerow(r)
    else:
        raise DataFetchError(f"不支持的 --format：{fmt}（仅 json/csv）")


# --------------------------------------------------------------------------- #
# 编排：参数校验 → 缓存 → 获取 → 归一 → 输出
# --------------------------------------------------------------------------- #
def run_task(args: argparse.Namespace) -> Dict[str, Any]:
    task = args.task
    source = args.source
    spec = TASKS.get(task)
    if not spec:
        raise DataFetchError(f"未知 task：{task}（可用：{', '.join(TASKS)}）")

    # 收集参数
    params: Dict[str, Any] = {}
    for p in spec["required"] + spec["optional"]:
        val = getattr(args, p, None)
        if val is not None:
            params[p] = val
    missing = [p for p in spec["required"] if p not in params]
    if missing:
        raise DataFetchError(f"task={task} 缺少必需参数：{', '.join(missing)}")

    # 日期默认值（仅对带 date 的任务）：保持可重复，默认使用一个固定值而非“今天”
    if "date" in spec["optional"] and "date" not in params:
        params["date"] = "20260814"  # 固定默认，避免“今天”带来的不一致

    cache_dir = args.cache_dir or DEFAULT_CACHE_DIR
    key = _cache_key(task, source, params)

    if not args.no_cache:
        cached = load_cache(cache_dir, key, args.cache_ttl)
        if cached is not None:
            LOG.info("命中缓存 %s（task=%s source=%s）", key, task, source)
            cached["meta"]["from_cache"] = True
            if args.out:
                write_output(cached, args.out, args.format)
            return cached

    # 执行获取
    fn = spec["fn"]
    call_kwargs = dict(params)
    if task == "daily_kline":
        call_kwargs.setdefault("adj", args.adj or "qfq")
    if task == "stock_spot":
        call_kwargs["limit"] = args.limit

    data, provenance = fn(source, **call_kwargs) if task in (
        "trade_calendar", "sector_fund_flow", "stock_spot") \
        else fn(source, code=params.get("code"), start=params.get("start"),
                end=params.get("end"), adj=params.get("adj", "qfq"))

    if not data:
        LOG.warning("task=%s source=%s 返回空数据（仍按空结果输出）", task, source)

    fetched_at = args.frozen_meta or time.strftime("%Y-%m-%dT%H:%M:%S")
    blob = {
        "meta": {
            "task": task,
            "source": source,
            "params": params,
            "provenance": provenance,
            "fetched_at": fetched_at,
            "cached_at": int(time.time()),
            "count": len(data),
            "schema_version": SCHEMA_VERSION,
            "from_cache": False,
        },
        "data": data,
    }
    save_cache(cache_dir, key, blob)
    if args.out:
        write_output(blob, args.out, args.format)
        LOG.info("已写出 %s（%d 条，%s）", args.out, len(data), args.format)
    return blob


# --------------------------------------------------------------------------- #
# 离线自检：不依赖网络/akshare/tushare，验证重试+归一+缓存闭环
# --------------------------------------------------------------------------- #
def _self_test() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("=== data_fetcher 离线自检 ===")

    # 1) 重试：前两次失败，第三次成功
    calls = {"n": 0}

    @retry(max_attempts=4, base_delay=0.02, max_delay=0.1)
    def flaky() -> List[Dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("network blip")
        return [{"date": "20260814", "is_open": False}]

    out = flaky()
    assert out == [{"date": "20260814", "is_open": False}] and calls["n"] == 3, calls
    print(f"[OK] 重试机制：第 3 次成功，实际调用 {calls['n']} 次")

    # 2) 结构归一化（模拟 DataFrame.to_dict('records') 的 list[dict]）
    rows = [
        {"cal_date": "2026-08-17", "is_open": 1},
        {"cal_date": "20260814", "is_open": 0},
    ]
    recs = norm_trade_calendar(rows)
    assert recs[0]["date"] == "20260814" and recs[1]["is_open"] is True, recs
    print(f"[OK] 交易日历归一：{recs}")

    krows = [{"trade_date": "20260814", "open": "10.2", "close": "10.5", "vol": "12345"}]
    krecs = norm_kline(krows)
    assert krecs[0]["open"] == 10.2 and krecs[0]["volume"] == 12345.0, krecs
    print(f"[OK] 日线归一：{krecs}")

    # 3) 缓存可重复性：两次读取字节一致
    tmp = tempfile.mkdtemp()
    key = "selftest"
    sample = {"meta": {"task": "x"}, "data": recs}
    save_cache(tmp, key, sample)
    a = load_cache(tmp, key, ttl=99999)
    b = load_cache(tmp, key, ttl=99999)
    assert a == b and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    print("[OK] 结果缓存：两次读取字节级一致")

    # 4) TTL 过期
    old = {"meta": {"cached_at": int(time.time()) - 100000}, "data": []}
    save_cache(tmp, "expired", old)
    assert load_cache(tmp, "expired", ttl=10) is None
    print("[OK] 缓存 TTL：过期自动失效")

    # 5) 确定性 JSON 输出
    blob = {"meta": {"fetched_at": "2026-08-15T00:00:00", "count": len(recs)},
            "data": recs}
    p1 = os.path.join(tmp, "o1.json")
    p2 = os.path.join(tmp, "o2.json")
    write_output(blob, p1, "json")
    write_output(blob, p2, "json")
    assert open(p1, encoding="utf-8").read() == open(p2, encoding="utf-8").read()
    print("[OK] 确定性输出：相同输入两次写出完全一致")

    print("SELF-TEST PASSED ✅")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="稳定的量化数据获取脚本（akshare / tushare）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--task", help=f"任务名，可选：{', '.join(TASKS)}")
    p.add_argument("--source", choices=["akshare", "tushare"],
                   help="数据源（必须显式指定）")
    p.add_argument("--start", help="起始日期 YYYYMMDD")
    p.add_argument("--end", help="结束日期 YYYYMMDD")
    p.add_argument("--code", help="标的代码，如 600519.SH（tushare）或 600519（akshare）")
    p.add_argument("--date", help="统计日期 YYYYMMDD（板块资金流等）")
    p.add_argument("--adj", default="qfq", help="复权方式 qfq/hfq/''（默认 qfq）")
    p.add_argument("--limit", type=int, default=None, help="stock_spot 限量")
    p.add_argument("--out", help="输出文件路径（json/csv）")
    p.add_argument("--format", choices=["json", "csv"], default="json", help="输出格式")
    p.add_argument("--cache-dir", help=f"缓存目录（默认 {DEFAULT_CACHE_DIR}）")
    p.add_argument("--cache-ttl", type=int, default=86400,
                   help="缓存有效期秒（默认 86400；0=永不过期）")
    p.add_argument("--no-cache", action="store_true", help="跳过缓存，强制重新获取")
    p.add_argument("--frozen-meta", help="冻结 fetched_at 时间戳，保证字节级可重复")
    p.add_argument("--list-tasks", action="store_true", help="列出所有任务及所需参数")
    p.add_argument("--self-test", action="store_true", help="运行离线自检（无需网络）")
    p.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.self_test:
        return _self_test()
    if args.list_tasks:
        print("可用任务：")
        for name, spec in TASKS.items():
            req = ", ".join(spec["required"]) or "（无）"
            opt = ", ".join(spec["optional"]) or "（无）"
            print(f"  - {name}: {spec['help']}")
            print(f"      必需参数: {req} | 可选参数: {opt}")
        return 0
    if not args.task or not args.source:
        print("错误：必须指定 --task 与 --source（或用 --list-tasks / --self-test）。",
              file=sys.stderr)
        return 2
    try:
        blob = run_task(args)
        if not args.out:
            print(json.dumps(blob, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except DataFetchError as exc:
        print(f"[数据获取失败] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
