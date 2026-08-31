#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mx-ds-mcp 不可用时的降级刷新：沿用现有 schema，更新 asof / updated_at。

通道说明（2026-08-31 验证）：
  · westock-mcp       —— 未连接，工具不可见
  · mx-ds-mcp         —— 未连接，工具不可见
  · eastmoney MCP     —— 走 push2.eastmoney.com，沙箱内连接被拒（ProtocolError）
  · 腾讯 qt.gtimg.cn / proxy.finance.qq.com —— 可直连（与 feed.py 同口径）

因此：
  · macro_commodity.json   5 项用腾讯外盘期货真实刷新（黄金/白银/WTI/布油/伦铜）；
                           美元指数、美债10Y、VIX 腾讯无对应代码 -> 沿用旧值并标 stale。
  · sector_contrib_mx.json members.change_pct 用腾讯行情真实刷新，mcap_yi 沿用。
  · a_news / global_news   无可用资讯源 -> 沿用原文，updated_at 刷新，asof 不动，标 stale。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
NOW = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
TODAY = dt.date.today().isoformat()

# 腾讯外盘期货代码 -> (展示名, 单位, 缓存中既有条目的关键词)
# 关键词必须覆盖历史命名（如"现货黄金"），否则会新增重复条目而不是原地更新。
HF_MAP = [
    ("hf_GC", "COMEX黄金", "美元/盎司", ["黄金"]),
    ("hf_SI", "COMEX白银", "美元/盎司", ["白银"]),
    ("hf_CL", "WTI原油", "美元/桶", ["WTI"]),
    ("hf_OIL", "布伦特原油", "美元/桶", ["布伦特", "布油"]),
    ("hf_CAD", "LME铜", "美元/吨", ["铜"]),
]


def load(fn):
    with open(os.path.join(CACHE, fn), encoding="utf-8") as f:
        return json.load(f)


def dump(fn, obj):
    with open(os.path.join(CACHE, fn), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[mx-fallback] {fn} -> updated_at {obj.get('updated_at')}")


def qt(codes: list) -> dict:
    """腾讯行情批量拉取，返回 {代码: {price, pct, prev}}，键为传入代码的去前缀形式。

    两套字段格式必须分开处理，否则会解析出垃圾值：
      · 外盘期货 hf_* : p[0]=现价 p[1]=涨跌幅% p[7]=昨收   （共 ~15 段）
      · A股 sh/sz*    : p[1]=名称 p[2]=代码 p[3]=现价 p[4]=昨收 p[32]=涨跌幅%（共 60+ 段）
    """
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    raw = subprocess.run(["curl", "-s", "-m", "20", url],
                         capture_output=True).stdout.decode("gbk", "ignore")
    out = {}
    for line in raw.split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"')
        # 外盘期货用逗号分隔，A股用波浪号分隔 —— 必须先按分隔符猜格式再 split
        sep = "~" if val.count("~") > val.count(",") else ","
        p = val.split(sep)
        try:
            if len(p) > 30:                      # A股
                rec = {"price": float(p[3]), "prev": float(p[4]), "pct": float(p[32])}
                out[p[2]] = rec                  # 纯代码
            elif len(p) >= 9:                    # 外盘期货
                out[key[2:]] = {"price": float(p[0]), "pct": float(p[1]), "prev": float(p[7])}
        except (ValueError, IndexError):
            continue
    return out


# ---------------- 1) macro_commodity.json ----------------
def refresh_macro():
    d = load("macro_commodity.json")
    # 先按关键词去重：历史遗留的重复条目（如"现货黄金"+"COMEX黄金"）只保留第一条
    seen, dedup = set(), []
    for i in d["items"]:
        key = next((k for c, _, _, kws in HF_MAP for k in kws if k in i["name"]), i["name"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(i)
    if len(dedup) != len(d["items"]):
        print(f"[mx-fallback] macro 去重 {len(d['items'])} -> {len(dedup)} 条")
        d["items"] = dedup

    q = qt([c for c, *_ in HF_MAP])
    hit = 0
    for code, name, unit, kws in HF_MAP:
        r = q.get(code)
        if not r:
            continue
        hit += 1
        item = next((i for i in d["items"]
                     if any(k in i["name"] for k in kws)), None)
        payload = {
            "name": name, "price": r["price"], "change_pct": r["pct"], "unit": unit,
            "asof": TODAY, "prev": r["prev"], "status": "ok",
            "note": f"腾讯外盘 {code} 实时报价 {NOW}",
        }
        if item:
            item.update(payload)
        else:
            d["items"].append(payload)
    # 腾讯无覆盖的项：沿用旧值，强制标 stale
    for i in d["items"]:
        if i["asof"] != TODAY:
            i["status"] = "stale"
            i["note"] = (i.get("note", "") +
                         f" | {TODAY} 未获新报价，沿用 asof={i['asof']}（mx-ds-mcp 不可用）").strip(" |")
    d["updated_at"] = NOW
    d["source"] = (f"腾讯外盘期货(qt.gtimg.cn) 实时 {NOW}｜"
                   f"mx-ds-mcp 不可用，无覆盖项标注 stale（{hit}/{len(HF_MAP)} 项真实刷新）")
    dump("macro_commodity.json", d)
    return hit


# ---------------- 2) sector_contrib_mx.json ----------------
def refresh_sector_contrib():
    d = load("sector_contrib_mx.json")
    codes = list(d["members"].keys())
    # 腾讯需要带市场前缀
    prefixed = [("sh" + c) if c[0] in "69" else ("sz" + c) for c in codes]
    q = qt(prefixed)          # qt() 对 A 股已返回纯代码键，直接用
    hit = 0
    for c in codes:
        r = q.get(c)
        if r:
            d["members"][c]["change_pct"] = r["pct"]
            hit += 1
    d["asof"] = TODAY
    d["updated_at"] = NOW
    d["source"] = (f"腾讯行情(qt.gtimg.cn) 实时涨跌幅 {NOW}，市值沿用上次缓存｜"
                   f"mx-ds-mcp 不可用（{hit}/{len(codes)} 只刷新）")
    dump("sector_contrib_mx.json", d)
    return hit


# ---------------- 3) 两个新闻缓存 ----------------
def refresh_news(fn: str):
    d = load(fn)
    d["updated_at"] = NOW
    d["stale"] = True
    d["source"] = (d.get("source", "") +
                   f" | {NOW} 复核：mx-ds-mcp 未连接且沙箱无可用资讯源，"
                   f"未能取得 {TODAY} 新资讯，headlines 沿用 asof={d.get('asof')}").strip(" |")
    dump(fn, d)


if __name__ == "__main__":
    n1 = refresh_macro()
    n2 = refresh_sector_contrib()
    refresh_news("a_news_summary.json")
    refresh_news("global_news_summary.json")
    print(f"[mx-fallback] 宏观真实刷新 {n1} 项 | 板块成分刷新 {n2} 只 | "
          f"新闻沿用旧 asof（标 stale）")
    sys.exit(0)
