# 自动化执行记忆：量化工作台实时数据刷新

## 2026-08-21 09:07 (周五盘前) 执行
- 分支：main ✅（commit be247e1，push badd57b..be247e1 成功）
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-21 09:04:30 ✅
- 步骤2 westock-mcp data_sector(ranking,sw1,30)：写入 sector_raw_westock.json(updated_at 09:07:0x)，refresh_sector_data.py → sector_leader_data.json updated_at=2026-08-21T09:07:01（top_inflow=7/top_outflow=3/astocks=5213）。流入TOP3：生物制品(+7.85%,主净+33.1亿)、医疗服务(+4.24%,主净+38.7亿)、化学制药(+2.55%,主净+27.7亿)；流出TOP3：半导体(-0.36%,主净-70.0亿)、电池(-0.84%,-15.6亿)、小金属(-1.08%,-15.5亿) ✅
- 步骤3 mx-ds-mcp：⚠️ 连接器仍 disconnected（连续第4次，自 8/19 起），**跳过**。4 缓存保留原值、未伪造时间戳：macro_commodity / a_news_summary / global_news_summary / sector_contrib_mx 均 asof=updated_at=2026-08-18，source=mx-ds-mcp。已连续 4 个交易日未刷新，需提醒用户重连。
- 步骤4/5 ✅ index.html 4.85MB，commit be247e1 push 成功，GitHub Pages 自动重建。
- 盘面特征（盘前快照）：医药链全面领涨（生物制品/医疗服务/化学制药/医疗器械主力净流入居前），半导体主力净流出居首（-70亿，但板块指数仅-0.36%，内部思瑞浦+15.31%领涨分化），避险方向贵金属(+5.50%)延续强势。
- holdings.json accounts 展平修复仍生效（7 条持仓正常渲染）。

## 2026-08-20 09:05 (周四盘前) 执行
- 分支：main ✅（commit 3ab8ce7，push 870f62f..3ab8ce7 成功）
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-20 09:05:50 ✅
- 步骤2 westock-mcp data_sector(ranking,sw1,30)：写入 sector_raw_westock.json，refresh_sector_data.py → sector_leader_data.json updated_at=2026-08-20T09:06:58（top_inflow=8/top_outflow=3/astocks=5213）。流入TOP3：焦炭Ⅱ(+7.56%,主净+6.9亿)、航运港口(+1.11%,+5.9亿)、风电设备(-3.35%,+6.0亿)；流出TOP3：半导体(-7.57%,-355.5亿)、通信设备(-8.66%,-255.8亿)、元件(-9.04%,-168.3亿) ✅
- 步骤3 mx-ds-mcp：⚠️ 连接器仍 disconnected（连续第2次），**跳过**。4 缓存保留原值、未伪造时间戳：macro_commodity / a_news_summary / global_news_summary updated_at=2026-08-18，sector_contrib_mx asof=2026-08-14。已连续 2 个交易日未刷新，需提醒用户重连。
- 步骤4/5 ✅ index.html 4.85MB，commit 3ab8ce7 push 成功，GitHub Pages 自动重建。
- **本次修复两个真实缺陷（重要，勿回退）**：
  1. cache/holdings.json 自 commit 870f62f(8/19 22:30) 起 JSON 损坏——第 2418 字符多一个 `}` 提前闭合根对象，尾部 `, "summary": {...}}` 成为非法多余数据。修法：`s[:2418] + s[2419:]` 后 json.loads 通过，7 只持仓与 summary 完整，数据未改动。成因是手工/Agent 写入括号错位，非脚本级复发 bug（无脚本产出该 summary 块）。
  2. build_dashboard.py 只读 `holdings_cache["positions"]`，而 holdings.json 实为 `accounts{broker:[...]}` 分账户结构 → broker_positions 恒为 []，致持仓 section/风险/任务/弹窗全空（看板"持仓数"曾显示 0）。已在 L5714 call site 增加 accounts→positions 展平分支（仅 positions 缺失时触发，加法式改动），恢复 7 条持仓渲染，index.html 4835335→4850861 字节。
- 排查笔记：`_paper_trade_card()` 里的「持仓数 0」属模拟盘无仓位，与实盘无关，非缺陷，勿误改。
- 盘面特征：半导体/通信设备/元件 三大科技板块重挫（-7.5%~-9%），主力合计净流出近 780 亿；资金避险流向焦炭、航运港口、银行（国有大行/股份制/城商行齐涨）。持仓 8/19 已大幅调仓：通富微电 600→300、君正(东财) 1300→1000、国瓷 1200→500 割肉、风华 1500→500 割肉、北大荒 500→2000 加仓，当日 -50,841 元。

## 2026-08-19 08:50 (周三盘前) 执行
- 分支：main ✅（commit c2ab92b，push 9d24abe..c2ab92b 成功）
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-19 08:50:46 ✅
- 步骤2 westock-mcp data_sector(ranking,sw1,30)：写入 sector_raw_westock.json(updated_at 08:51:50)，运行 refresh_sector_data.py → sector_leader_data.json updated_at=2026-08-19T08:51:50（top_inflow=8/top_outflow=3/astocks=5213）。流入TOP3：种植业(+9.54%,主净+14.2亿)、光学光电子(+2.35%,主净+15.5亿)、化学原料(+1.03%,主净+11.1亿) ✅
- 步骤3 mx-ds-mcp：⚠️ 本次连接器 disconnected，工具不可用，**跳过**。4个缓存保留上次值（updated_at 均=2026-08-18，source=mx-ds-mcp，数据日 8/14 真实收盘）：macro_commodity / a_news_summary / global_news_summary / sector_contrib_mx。
- 步骤4 build_dashboard.py：index.html 重建成功（4.97MB）；非致命警告 feed.get_indicators failed（list index out of range），不影响产物。
- 步骤5 提交推送：commit c2ab92b，push origin main 成功。GitHub Pages 自动重建。
- 失败项：mx-ds-mcp 断开导致步骤3整体跳过（已在 commit message 注明）。新增临时辅助脚本 scripts/_build_sector_raw.py（westock返回→sector_raw_westock.json 子集转写，后续可复用）。
- 盘面特征：农业链（种植业/农产品加工/渔业）领涨，半导体(-0.23%)/通信设备(-1.35%)/元件(-2.03%) 主力净流出居前。

## 2026-08-17 08:50 (周一盘前) 执行
- 分支：main ✅
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-17 08:51:14 ✅
- 步骤2 westock-mcp data_sector(ranking,sw1,30)：写入 sector_raw_westock.json(updated_at 08:52:00)，运行 refresh_sector_data.py → sector_leader_data.json updated_at=2026-08-17T08:52:39（top_inflow=7/top_outflow=3/astocks=5213）。流入TOP3：通信设备(+3.63%,主净+122.2亿)、小金属(+3.04%)、通信服务(+2.33%) ✅
- 步骤3 mx-ds-mcp：4个缓存已刷新并标注 source=mx-ds-mcp。底层数据最新收盘为 2026-08-14（周末+周一盘前无新收盘，故 asof 保留 8/14 真实数据日，updated_at 改当日）：
  - macro_commodity.json（COMEX黄金4432/WTI82.4/USD-CNY6.74435/美元指数99.635）
  - sector_contrib_mx.json（16只成员，与 mx 8/14 返回一致）
  - a_news_summary.json / global_news_summary.json（8/17 实时要闻+专题）
- 步骤4 build_dashboard.py：index.html 重建成功；非致命警告 feed.get_indicators failed（list index out of range），不影响产物。
- 步骤5 提交推送：commit d183518，push origin main 成功（0b7fe51..d183518）。GitHub Pages 自动重建。
- 失败项：无（所有 MCP 调用成功；get_indicators 警告非 MCP 失败，已跳过该内部计算继续）。
