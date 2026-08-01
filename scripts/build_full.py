#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_full.py —— CI 用：先生成基础看板（含原生实时行情），再幂等注入三仓策略系统。

用法（在仓库根目录）：
  python scripts/build_full.py
"""
import os, sys, subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(cmd):
    print(">>", cmd)
    subprocess.run(cmd, cwd=REPO, shell=True, check=True)


def main():
    # 1) 基础看板（build_dashboard.py 已含 v2 实时行情）
    run(f'{PY} scripts/build_dashboard.py')
    # 2) 移除可能已存在的策略模块，保证幂等
    run(f'{PY} scripts/strip_strategy.py')
    # 3) 注入三仓策略执行系统
    run(f'{PY} scripts/inject_strategy_system.py')


if __name__ == "__main__":
    main()
