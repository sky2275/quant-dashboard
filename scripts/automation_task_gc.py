#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
automation_task_gc.py — 定时任务运行记录去重（同一时间节点只保留最新一条）

背景
----
WorkBuddy 每次定时任务执行，都会在左侧「空间」任务列表里新建一条任务记录。
于是同一个时间节点跑 N 天，列表里就会出现 N 条同名任务（量化工作台·15:10因子纪律检查 ×N …）。
平台本身没有「运行记录覆盖/复用同一任务」的开关（automation 配置表与应用包内均无此字段），
所以用本脚本做等效实现：把「同名（= 同一时间节点）的自动化任务记录」裁剪为只保留最新一条。

实现方式
--------
软删除：把 sessions 表中旧记录的 deleted_at 置为当前时间戳毫秒。
这与 App 界面里「右键 → 删除」是同一个字段，效果一致，且可逆
（恢复 = 把 deleted_at 置回 NULL）。automation 配置表 automations 完全不动。

用法
----
  python3 scripts/automation_task_gc.py --dry-run   # 只预览，不改数据
  python3 scripts/automation_task_gc.py             # 执行（保留每个时间节点最新 1 条）
  python3 scripts/automation_task_gc.py --keep 2    # 每个时间节点保留最新 2 条
  python3 scripts/automation_task_gc.py --prefix 量化工作台   # 自定义标题前缀
  python3 scripts/automation_task_gc.py --restore-hours 2     # 撤销最近 2 小时内的软删除

输出
----
stdout 打印一行 JSON 汇总，便于自动化任务如实汇报：
  {"ok": true, "kept": 5, "deleted": 11, "backup": "...", "nodes": {...}}
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict

HOME = os.path.expanduser("~")
WB_DIR = os.path.join(HOME, ".workbuddy")
DB_PATH = os.path.join(WB_DIR, "workbuddy.db")
BACKUP_ROOT = os.path.join(WB_DIR, "automation-backups", "task-gc")


def _backup_db() -> str:
    """用 sqlite 在线备份 API 做一致性快照（含 WAL 内容）。失败返回空串。"""
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_dir = os.path.join(BACKUP_ROOT, stamp)
        os.makedirs(out_dir, exist_ok=True)
        dst_path = os.path.join(out_dir, "workbuddy.db")
        src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=15)
        dst = sqlite3.connect(dst_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return dst_path
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 备份失败（不影响去重）：{e}", file=sys.stderr)
        return ""


def _restore(hours: float) -> int:
    """撤销误删：把最近 N 小时内被本脚本软删的自动化任务记录恢复（deleted_at=NULL）。"""
    if not os.path.exists(DB_PATH):
        print(json.dumps({"ok": False, "reason": "DB not found"}, ensure_ascii=False))
        return 1
    since = int((time.time() - hours * 3600) * 1000)
    con = sqlite3.connect(DB_PATH, timeout=15)
    with con:
        cur = con.execute(
            """
            UPDATE sessions SET deleted_at = NULL
             WHERE is_background_automation = 1
               AND deleted_at IS NOT NULL
               AND deleted_at >= ?
            """,
            (since,),
        )
    con.close()
    print(json.dumps({"ok": True, "restored": cur.rowcount, "within_hours": hours}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预览，不修改")
    ap.add_argument("--keep", type=int, default=1, help="每个时间节点保留最新几条（默认 1）")
    ap.add_argument("--prefix", default="量化工作台", help="任务标题前缀，默认「量化工作台」")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    ap.add_argument("--restore-hours", type=float, default=None, help="撤销最近 N 小时内的软删除后退出")
    args = ap.parse_args()

    if args.restore_hours is not None:
        return _restore(args.restore_hours)

    if not os.path.exists(DB_PATH):
        print(json.dumps({"ok": False, "reason": f"DB not found: {DB_PATH}"}, ensure_ascii=False))
        return 0  # 不阻塞主流程

    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT id, title, created_at, status
              FROM sessions
             WHERE is_background_automation = 1
               AND deleted_at IS NULL
               AND title LIKE ?
             ORDER BY created_at DESC
            """,
            (f"{args.prefix}%",),
        ).fetchall()
    except sqlite3.Error as e:
        con.close()
        print(json.dumps({"ok": False, "reason": f"query failed: {e}"}, ensure_ascii=False))
        return 0

    by_title = defaultdict(list)
    for r in rows:
        by_title[r["title"]].append(r)

    now_ms = int(time.time() * 1000)
    to_delete = []
    kept = {}
    for title, items in by_title.items():
        items.sort(key=lambda x: x["created_at"] or 0, reverse=True)
        kept[title] = [it["id"][:8] for it in items[: args.keep]]
        to_delete.extend(it["id"] for it in items[args.keep :])

    if args.dry_run or not to_delete:
        con.close()
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "kept": sum(len(v) for v in kept.values()),
                    "deleted": 0 if args.dry_run else 0,
                    "would_delete": len(to_delete),
                    "nodes": kept,
                },
                ensure_ascii=False,
            )
        )
        return 0

    backup = "" if args.no_backup else _backup_db()
    try:
        with con:
            con.executemany(
                "UPDATE sessions SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                [(now_ms, sid) for sid in to_delete],
            )
    except sqlite3.Error as e:
        con.close()
        print(json.dumps({"ok": False, "reason": f"write failed: {e}", "backup": backup}, ensure_ascii=False))
        return 0
    con.close()

    print(
        json.dumps(
            {
                "ok": True,
                "kept": sum(len(v) for v in kept.values()),
                "deleted": len(to_delete),
                "backup": backup,
                "nodes": kept,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
