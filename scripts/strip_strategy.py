#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""strip_strategy.py —— 移除已注入的三仓策略模块，便于 CI 重建后幂等重注入。"""
import re, os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(REPO, "index.html")

html = open(HTML, encoding="utf-8").read()
orig = html

# 1) 移除策略卡片（从 id=strategyCard 到「全球大盘行情」卡片之前）
start = html.find('    <div class="card card-full" id="strategyCard">')
if start != -1:
    end = html.find('    <div class="card card-full" onclick="openModal(\'market\')">', start)
    if end != -1:
        html = html[:start] + html[end:]

# 2) 移除策略 CSS
html = re.sub(r'<style>\s*\.strat-wrap.*?</style>', '', html, flags=re.DOTALL)

# 3) 移除策略 JS
html = re.sub(r'<script>\s*\(function\(\)\{\s*function toEmSecid.*?</script>', '', html, flags=re.DOTALL)

if html != orig:
    open(HTML, "w", encoding="utf-8").write(html)
    print("OK: 已移除三仓策略模块")
else:
    print("WARN: 未找到策略模块，无需移除")
