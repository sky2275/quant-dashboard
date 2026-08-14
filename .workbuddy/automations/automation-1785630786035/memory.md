# 量化看板 08:00 开盘前刷新 — 执行记忆

## 2026-08-03 08:03 (周一, 交易日, 命中 08:00 窗口)
- 触发命中：`TRIGGER feed=1 us=1 scan=`，后台刷新 pid 26378，退出码 0。
- 数据拉取阶段成功：美股隔夜 us_overnight.json 已成功暂存（git status 显示 `M  cache/us_overnight.json`）。
- **部署阶段失败**：脚本内 git rebase 自动提交看板时发生合并冲突，日志：
  - `CONFLICT (content): Merge conflict in index.html`
  - `CONFLICT (content): Merge conflict in cache/backtest_klines.json`
  - `CONFLICT (content): Merge conflict in cache/market_snapshot.json`
  - `2026-08-03 08:14:53 [deploy] rebase failed` → `[run] DONE`
- 当前工作树处于**中途 rebase 冲突状态**（`.git/rebase-merge` 存在，`UU` 冲突文件：index.html / cache/backtest_klines.json / cache/market_snapshot.json）。
- 用户指令：不修改任何看板代码/配置/数据文件 → 未执行 rebase --abort / --continue / 冲突解决，仅如实汇报，交由用户决策。

## 历史观察
- 2026-08-02（周日及非交易日）：多次被脚本跳过（skip: weekend / non-trade day），属正常。
- 冲突根因疑似：本地分支已有新提交（如 8/3 作战策略、手机端双券商持仓刷新），与脚本自动生成提交间的历史分叉，rebase 时产生内容冲突。

## 2026-08-04 07:53 (周二, 交易日, 命中 08:00 窗口)
- 首次以相对路径 `bash refresh_dashboard.sh` 运行 → 命中窗口、后台 pid 34565 立即报 `nohup: refresh_dashboard.sh: No such file or directory`（$0 为相对名，PATH 不含 `.`），真正刷新未启动；并残留孤儿锁 cache/refresh.lock。
- 改用用户给定的**绝对路径**重跑 `bash /abs/path/refresh_dashboard.sh` → $0 为绝对路径，nohup 成功，后台 pid 34661 真正执行并清理锁。
- 核心刷新成功：us_overnight(美股隔夜传导) + feed + 回测K线(44只) + build_dashboard 重建 index.html；本地提交 `ad4df97`（auto update dashboard 2026-08-04 07:57）。
- 部署仍失败：deploy 的 `git pull --rebase` 报 `cannot pull with rebase: You have unstaged changes`。根因：工作树存在脚本 git add 集合之外的未暂存改动（scripts/build_dashboard.py、两个 automation memory.md）→ 未 push，远端/GitHub Pages 未更新。与 8/3 同根因。
- 锁已正常清理。未修改任何代码/配置/数据文件，未手动解决 rebase（交用户决策）。
- ⚠️ **经验**：本脚本必须用绝对路径调用；相对路径会让 `nohup "$0"` 找不到脚本，导致后台刷新静默失败（包装器仍返回 0）。

## 2026-08-05 07:51 (周三, 交易日, 命中 08:00 窗口)
- 绝对路径运行包装器 → 命中窗口 `TRIGGER feed=1 us=1 scan=`，后台 pid 48659（[run] start 07:51:35）。
- 全程无 WARN/失败：us_overnight(美股隔夜传导, stale=false) + feed + 回测K线(41只) + build_dashboard 重建 index.html 均成功。
- **部署成功**：本次 `git pull --rebase` 顺利，commit `0dcbd5f`（auto update dashboard 2026-08-05 07:54）→ push 至 github.com:sky2275/quant-dashboard.git 成功（07:54:51 [deploy] pushed），GitHub Pages 应已更新。
- 与 8/3、8/4 不同：本次工作树无脚本 git add 集合外的未暂存改动，rebase 未冲突，部署链路完整跑通。
- 数据文件 mtime 均为 07:54:4x；锁已正常清理。未修改任何代码/配置/数据文件。

## 2026-08-07 07:52 (周五, 交易日, 命中 08:00 窗口, 含美股隔夜 us=1)
- 绝对路径运行包装器 → 命中窗口 `TRIGGER feed=1 us=1 scan=`，后台 pid 75627（[run] start 07:52:38）。
- 全程无 WARN/失败：美股隔夜传导 us_overnight 成功刷新（updated_at 07:52:41 / 07:54:30，stale=false）+ feed + 回测K线(41只) + build_dashboard 重建 index.html 均成功。
- **部署成功**：本地提交 `52034e4`（auto update dashboard 2026-08-07 07:56）→ push 至 github.com:sky2275/quant-dashboard.git 成功（07:56:47 [deploy] pushed），GitHub Pages 应已更新。
- 与 8/3、8/4、8/6 不同：本次工作树无脚本 git add 集合外的未暂存改动/无 rebase 冲突，部署链路完整跑通。
- 锁已正常清理（进程结束后无 refresh.lock）。未修改任何代码/配置/数据文件，未写入腾讯文档空间。

## 2026-08-08 07:51 (周六, 非交易日, 跳过)
- 绝对路径运行包装器 → 退出码 0，无 WARN/失败。
- 命中判断：`2026-08-08 07:51:59 skip: non-trade day (07:51)` —— 周六非交易日，脚本正常跳过，未触发后台刷新、未覆写 index.html / cache。
- 与 8/2、8/3(周日) 同属非交易日跳过，属预期行为。未修改任何代码/配置/数据文件，未写入腾讯文档空间。

## 2026-08-09 07:51 (周日, 非交易日, 跳过)
- 绝对路径运行包装器 → 退出码 0，无 WARN/失败；锁已正常清理（无 refresh.lock 残留）。
- 命中判断：`2026-08-09 07:51:23 skip: non-trade day (07:51)` —— 周日非交易日，脚本正常跳过，未触发后台刷新、未覆写 index.html / cache，美股隔夜传导也未执行。
- 与 8/2、8/8 同属非交易日跳过，属预期行为。未修改任何代码/配置/数据文件，未写入腾讯文档空间。
- 最近一次完整成功部署仍为 8/7（周五）`52034e4` → GitHub Pages 已更新；下个交易日（周一 8/10）08:00 窗口将正常触发。

## 2026-08-11 20:24 (周二, 交易日, 但非窗口时间, 跳过)
- 绝对路径运行包装器 → 退出码 0，无 WARN/失败。
- 窗口判定：`2026-08-11 20:24:17 skip: no window (20:24)` —— 当前 20:24 不在脚本定义窗口（08:00/09:26/10:30/12:00/14:30/22:00）内，脚本正确跳过；后台刷新未启动，未覆写 index.html / cache，美股隔夜传导也未执行，未写腾讯文档空间。属预期行为（本次自动化在 20:24 触发，而非 08:00）。
- 只读核验：无残留锁（无 refresh.lock）；工作树存在脚本 git add 集合外的既有未暂存改动（M scripts/feed.py、多个未跟踪 scripts/*.py 与 cache/quant_cache.db）——这些非本次运行产生（skip 路径不改动文件），但性质同 8/4、8/7 21:59 的部署 rebase 冲突根因，若未来窗口内触发且未先清理，deploy 仍可能报 `cannot pull with rebase: You have unstaged changes`。
- 最近一次成功部署提交为 `b958c01`（8/11 收盘，含持仓调整与 build_dashboard 修复）。未修改任何代码/配置/数据文件。
