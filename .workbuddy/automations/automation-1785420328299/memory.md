# 量化看板·午后扫描 自动化执行记录

## 2026-07-31 14:25 (BYHOUR=14, BYMINUTE=30 触发)
- 运行方式: `refresh_dashboard.sh` 包装器,命中 14:30 窗口 → 后台 `run`(pid 49587),`scan=1430`,约 130s 完成。
- **结果:部分成功,非完全成功。**
  - ✅ feed 拉取行情成功(快照 `updated_at=2026-07-31 14:26:50`):上证 +1.05% / 深成指 +3.08% / 创业板 +4.39% / 科创50 +4.80%;美股纳指 +2.78%。板块资金流已更新。
  - ✅ `build_dashboard.py` 重建 HTML 成功(`written: index.html`)。
  - ❌ **14:30 全A股扫描失败**:`scan_a_shares.py --mode 1430` 调用 `ak.stock_zh_a_spot_em()`(东方财富全A实时行情)时,远端连接被中断 `RemoteDisconnected('Remote end closed connection without response')` → `requests.exceptions.ConnectionError`,akshare 重试后仍抛异常。属东方财富接口临时性限流/连接重置,**非代码问题**;看板扫描结果为上次成功值(或空)。
  - ❌ git 推送(deploy)失败:`cannot pull with rebase: You have unstaged changes`,rebase 失败。属仓库工作树未提交改动(历次运行均出现的独立问题),与本次扫描无关。
- 注:脚本内部对 scan 失败有 WARN 容错(不阻断 build/deploy),故 HTML 仍重建。本次未修改任何看板代码/配置/数据。

## 2026-08-01 14:25 (周六, 自动化被触发)
- 运行 `refresh_dashboard.sh`:退出码 0,正常执行。
- **结果:跳过(设计内)。** 包装器判定 `dow>=6`(周六) → `skip: weekend (14:25)`,未拉取行情、未扫描、未重建 HTML、未 deploy。
- 未改动任何看板代码/配置/数据文件。下个交易日(周一)14:30 窗口才会真正刷新。

## 观察/建议(供参考,未改动)
- East Money 接口偶发连接重置导致 spot 扫描失败,可考虑在 `scan_a_shares.py` 的 `_load_spot()` 增加退避重试,或换用腾讯自选股/MCP 行情源。属代码改动,需用户确认后再做。
- git deploy 反复因 unstaged changes 失败,建议检查工作树为何有未暂存改动(可能先于脚本生成了 index.html/cache 产物)。
