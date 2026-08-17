#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_snapshot_16h.py — 每个交易日 16:00 收盘后重建量化看板核心缓存。

职责（对应自动化任务 1~5 步，第6步 T+1 回测独立处理）：
  1) 板块资金流 sector_flow：本脚本不覆盖——若 mx-ds-mcp 返回空/失败，保留现有
     cache/a_sector_flow.json 与 market_snapshot.sector_flow（由调用方保证）。
  3) 大盘快照：用 data_changedist（当日）刷新 market_breadth；用 data_kline 校验
     a_indexes（已确认为当日，本脚本保留）；保留 limit_up（当日名单）。
  4) A股扫描 heatmap：用 mx_stocks_screener 当日 TOP50 重写（格式与旧 heatmap 一致）。
  2) 涨停板：由现有 market_snapshot.limit_up（当日）导出 cache/zt_screen_YYYYMMDD.json。

输入（MCP 原始响应，已由 agent 落盘）：
  cache/heatmap_raw_screener.json
  cache/breadth_raw_changedist.json
输出：
  cache/market_snapshot.json（原地更新，保留 sector_flow / a_indexes / limit_up）
  cache/zt_screen_YYYYMMDD.json
"""
import json
import os
import sys
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")


def _load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_amount(s):
    """把 '36.78亿' / '3632.57万' / '4.13万亿' 解析为元（float）。"""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    units = {"万亿": 1e12, "亿": 1e8, "万": 1e4}
    num, mult = None, 1.0
    for u, m in units.items():
        if s.endswith(u):
            try:
                num = float(s[: -len(u)])
            except ValueError:
                num = None
            mult = m
            break
    if num is None:
        try:
            num = float(s)
        except ValueError:
            return None
    return num * mult


def build_heatmap(raw):
    cols = raw.get("columns", [])
    items = raw.get("items", [])
    # 列索引（兼容列名变化）
    idx = {c: i for i, c in enumerate(cols)}
    ci = lambda key: next((idx[k] for k in idx if key in k), None)
    i_code = ci("代码")
    i_name = ci("名称")
    i_price = ci("最新价")
    i_chg = ci("涨跌幅")
    i_net = ci("主力净额")
    i_turn = ci("换手率")
    out = []
    for it in items:
        out.append({
            "名称": it[i_name],
            "代码": it[i_code],
            "最新价": float(it[i_price]) if it[i_price] not in (None, "") else None,
            "涨跌幅": float(it[i_chg]) if it[i_chg] not in (None, "") else None,
            "主力净流入-净额": _parse_amount(it[i_net]),
            "换手率": it[i_turn],
        })
    return out


def main():
    today = dt.datetime.now()
    ymd = today.strftime("%Y%m%d")
    snap_path = os.path.join(CACHE, "market_snapshot.json")
    snap = _load(snap_path)

    log = []

    # ---- 3) market_breadth 当日刷新 ----
    cd = _load(os.path.join(CACHE, "breadth_raw_changedist.json"))
    snap["market_breadth"] = {
        "amount": cd.get("totalAmount"),
        "up_count": cd.get("upCount"),
        "down_count": cd.get("downCount"),
        "limit_up_count": cd.get("upLimitCount"),
        "limit_down_count": cd.get("downLimitCount"),
        "flat_count": cd.get("flatCount"),
    }
    log.append(f"market_breadth 已刷新: 涨停{cd.get('upLimitCount')} 跌停{cd.get('downLimitCount')} "
               f"上涨{cd.get('upCount')} 下跌{cd.get('downCount')} 成交{cd.get('totalAmount'):.2e}")

    # ---- 4) heatmap 当日 TOP50 ----
    raw = _load(os.path.join(CACHE, "heatmap_raw_screener.json"))
    hm = build_heatmap(raw)
    snap["heatmap"] = hm
    log.append(f"heatmap 已重写: {len(hm)} 只（当日主力净流入 TOP50）")

    # ---- 1) sector_flow / a_indexes / limit_up 保留（当日已校验） ----
    sf = snap.get("sector_flow") or []
    log.append(f"sector_flow 保留: {len(sf)} 个板块（MCP 当日为空，按规则不覆盖）")
    ai = snap.get("a_indexes") or []
    log.append(f"a_indexes 保留: {len(ai)} 个指数（data_kline 校验为当日）")
    lu = snap.get("limit_up") or []
    log.append(f"limit_up 保留: {len(lu)} 只（当日名单）")

    # ---- updated_at ----
    snap["updated_at"] = today.strftime("%Y-%m-%d 16:00:00")
    log.append(f"updated_at -> {snap['updated_at']}")

    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    log.append(f"已写回 {os.path.relpath(snap_path, ROOT)}")

    # ---- 2) zt_screen_YYYYMMDD.json ----
    zt = {
        "date": ymd,
        "total": len(lu),
        "source": "market_snapshot.limit_up（当日 15:29 刷新，westock/腾讯自选股）",
        "stocks": [
            {k: x.get(k) for k in ["名称", "代码", "涨跌幅", "成交额", "所属行业", "连板数", "封单资金"]}
            for x in lu
        ],
    }
    zt_path = os.path.join(CACHE, f"zt_screen_{ymd}.json")
    with open(zt_path, "w", encoding="utf-8") as f:
        json.dump(zt, f, ensure_ascii=False, indent=2)
    log.append(f"已生成 {os.path.relpath(zt_path, ROOT)}（{len(lu)} 只：含连板数/题材/封单强度）")

    print("\n".join(log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
