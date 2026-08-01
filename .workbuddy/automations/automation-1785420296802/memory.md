# 量化看板·开盘前刷新 — 执行记录

## 2026-07-31 07:53 (CST) 执行（08:00 盘前窗口：feed=1, us=1, scan=空）
- **数据拉取 + 重建 HTML：成功。** 本地 `index.html` 更新至 2026-07-31 07:56，含当日行情/美股隔夜/回测K线；`cache/market_snapshot.json`(07:54)、`cache/us_overnight.json`(07:53) 同步刷新。后台进程 pid 44957，约 210s 完成，日志见 `cache/refresh.log` 末尾 `[run] DONE`。
- **自动部署(git push)失败：** 工作区存在**预置未暂存修改** `scripts/build_dashboard.py`（非本次刷新产生），导致 `deploy()` 内 `git pull --rebase` 被拒（"cannot pull with rebase: You have unstaged changes"），脚本在 rebase-continue 失败后 return，**未执行 push**。本地提交 `dbd5a38` 已生成但**未推送**，远端/GitHub Pages 未更新。
- **调用方式注意：** 第一调用误用相对名 `bash refresh_dashboard.sh`，使 `$0` 无路径，nohup 后台拉起失败（"No such file or directory"）。改用**绝对路径** `bash /abs/refresh_dashboard.sh` 后正常。自动化配置本身用的是绝对路径，无需改。
- **后续影响：** 只要 `scripts/build_dashboard.py` 仍有脏改动，每次 `deploy()` 的 rebase 都会失败、无法推送。需先处理该文件（stash/commit/checkout）才能恢复远端更新。本次未改动任何代码/配置/数据文件。

## 2026-08-01 11:32 (CST) 执行（周六，手动触发）
- **脚本运行成功（exit 0），但实际刷新被跳过：** 当天为周六，包装器命中 `skip: weekend (11:32)` 分支直接退出，未拉取行情/美股、未重建 HTML、未触发 git 部署。未改动任何代码/配置/数据文件。日志末尾确认 `2026-08-01 11:32:54 skip: weekend (11:32)`。
- **说明：** 自动化调度规则为工作日 MO–FR 08:00 才真正刷新；非交易日即使手动运行也会跳过（除非改用 `run` 子命令或绕过窗口判断）。如需非交易日强制刷新，需另行处理。
