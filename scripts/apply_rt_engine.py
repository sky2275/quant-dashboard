#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 scripts/rt_engine.js（RT V3 通用实时引擎）注入 index.html 的 </body> 之前。

用途：
  1. 本地 build 因 OOM 无法跑通时，用它直接给现有 index.html 打补丁
  2. 幂等：重复执行会先移除旧的 V3 块再注入，不会叠加
用法：
  python3 scripts/apply_rt_engine.py
"""
import io
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO_ROOT, "index.html")
ENGINE = os.path.join(REPO_ROOT, "scripts", "rt_engine.js")
PLACEHOLDER = "/*__RT_NAME2CODE__*/{}/**/"


def build_name2code():
    """构建 股票名称 -> 6位代码 映射，供浏览器端解析只有名称的表格行。"""
    n2c = {}

    # 1) 持仓（唯一权威源）
    try:
        p = os.path.join(REPO_ROOT, "cache", "holdings.json")
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                for x in (json.load(f).get("positions") or []):
                    if x.get("name") and x.get("code"):
                        n2c[str(x["name"]).strip()] = str(x["code"]).strip()
    except Exception as e:
        print("[warn] holdings:", e)

    # 2) 自选池（仓库根或 cache 下）
    for p in (os.path.join(REPO_ROOT, "watchlist.json"),
              os.path.join(REPO_ROOT, "cache", "watchlist.json")):
        try:
            if os.path.exists(p):
                with io.open(p, encoding="utf-8") as f:
                    w = json.load(f)
                for x in (w.get("watch") or []):
                    if x.get("name") and x.get("code"):
                        n2c[str(x["name"]).strip()] = str(x["code"]).strip()
                break
        except Exception as e:
            print("[warn] watchlist:", e)

    # 3) 快照中的涨停池 / 热力图
    try:
        p = os.path.join(REPO_ROOT, "cache", "market_snapshot.json")
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                s = json.load(f)
            for key in ("limit_up", "heatmap"):
                for x in (s.get(key) or []):
                    if x.get("名称") and x.get("代码"):
                        n2c[str(x["名称"]).strip()] = str(x["代码"]).strip()
    except Exception as e:
        print("[warn] snapshot:", e)

    return n2c


def main():
    if not os.path.exists(ENGINE):
        print("FAIL: 缺少", ENGINE)
        return 1
    html = io.open(INDEX, encoding="utf-8").read()

    # 幂等：移除旧的 V3 块
    before = len(html)
    html = re.sub(
        r'\n?<script>\s*/\* =+\s*\n\s*RT V3.*?</script>\n?',
        '\n', html, flags=re.S)
    removed = before - len(html)

    n2c = build_name2code()
    js = io.open(ENGINE, encoding="utf-8").read()
    if PLACEHOLDER not in js:
        print("FAIL: rt_engine.js 缺少占位符", PLACEHOLDER)
        return 1
    js = js.replace(PLACEHOLDER, json.dumps(n2c, ensure_ascii=False))

    block = '<script>\n' + js + '\n</script>\n'
    if '</body>' not in html:
        print("FAIL: index.html 缺少 </body>")
        return 1
    html = html.replace('</body>', block + '</body>', 1)

    io.open(INDEX, "w", encoding="utf-8").write(html)
    print("OK: RT V3 已注入 index.html")
    print("    清理旧块: %d 字节 | 名称→代码映射: %d 条" % (removed, len(n2c)))
    sample = ", ".join("%s→%s" % kv for kv in list(n2c.items())[:6])
    print("    覆盖标的: %s ..." % sample)
    return 0


if __name__ == "__main__":
    sys.exit(main())
