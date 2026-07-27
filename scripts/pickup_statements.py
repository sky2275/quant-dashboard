#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面取件：把 Mac 桌面上的券商交割单(.xls/.xlsx/.csv)搬进仓库对应目录并可选推送。

用法（在仓库目录下，终端里运行）：
    python3 scripts/pickup_statements.py            # 交互式：复制后询问是否推送
    python3 scripts/pickup_statements.py --push     # 复制后直接 git add/commit/push

逻辑：
  1. 扫描 ~/Desktop 下所有 .xls/.xlsx/.csv；
  2. 按文件名关键字自动判断券商（银河/海王星/双子星 → galaxy；东财/东方财富 → eastmoney）；
  3. 判断不了的，逐个让你选 1)银河 2)东财 3)跳过；
  4. 复制到 data/statements/{galaxy,eastmoney}/；
  5. 询问（或 --push 直接）提交并推送到 GitHub，触发看板自动合并更新。
"""
import os
import sys
import glob
import shutil
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = os.path.expanduser("~/Desktop")

GALAXY_KEYS = ["银河", "海王星", "双子星", "galaxy", "yh"]
EM_KEYS = ["东财", "东方财富", "eastmoney", "east"]


def detect(name):
    n = name.lower()
    if any(k in n for k in GALAXY_KEYS):
        return "galaxy"
    if any(k in n for k in EM_KEYS):
        return "eastmoney"
    return None


def main():
    files = []
    for pat in ("*.xls", "*.XLS", "*.xlsx", "*.XLSX", "*.csv", "*.CSV"):
        files += sorted(glob.glob(os.path.join(DESKTOP, pat)))
    if not files:
        print("桌面上没找到交割单文件（.xls / .xlsx / .csv 都没有）。")
        print("请先在两家券商客户端导出交割单并保存到桌面，再运行本脚本。")
        return

    print(f"在桌面找到 {len(files)} 个文件：")
    for fp in files:
        print("  - " + os.path.basename(fp))

    copied = []
    for fp in files:
        base = os.path.basename(fp)
        acc = detect(base)
        if acc is None:
            print(f"\n文件：{base}")
            print("  无法从文件名判断是哪家券商，请选择：")
            print("    1) 银河证券    2) 东方财富    3) 跳过")
            while True:
                c = input("  输入 1 / 2 / 3: ").strip()
                if c == "1":
                    acc = "galaxy"
                    break
                elif c == "2":
                    acc = "eastmoney"
                    break
                elif c == "3":
                    acc = None
                    break
                print("  请输入 1、2 或 3。")
        if acc:
            dst_dir = os.path.join(REPO_ROOT, "data", "statements", acc)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, base)
            shutil.copy2(fp, dst)
            copied.append((base, acc))
            label = "银河证券" if acc == "galaxy" else "东方财富"
            print(f"  ✓ 已复制 → data/statements/{acc}/  ({label})")

    if not copied:
        print("\n没有复制任何文件，已退出。")
        return

    do_push = "--push" in sys.argv
    if not do_push:
        a = input("\n是否提交并推送到 GitHub（触发看板自动合并更新）？ y/N: ").strip().lower()
        do_push = a in ("y", "yes", "是")

    if do_push:
        subprocess.run(["git", "add", "data/statements/"], cwd=REPO_ROOT)
        r = subprocess.run(
            ["git", "commit", "-m", "chore: 导入券商交割单(桌面取件)"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stdout.strip() or r.stderr.strip() or "（无变动可提交）")
        p = subprocess.run(["git", "push"], cwd=REPO_ROOT, capture_output=True, text=True)
        print(p.stdout.strip() or p.stderr.strip() or "")
        print("已推送，看板将在 1~2 分钟后自动更新。刷新页面即可看到双账号合并持仓。")
    else:
        print("\n已复制到仓库，但未推送。需要时运行：")
        print("  python3 scripts/pickup_statements.py --push")


if __name__ == "__main__":
    main()
