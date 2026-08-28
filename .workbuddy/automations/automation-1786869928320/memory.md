## 2026-08-28 09:20 (周五盘前) 执行
- 分支：main ✅（commit c96a9fb，push 7dad1f1..c96a9fb 成功）
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-28 09:05:44 ✅
- 步骤2 monitor.py：live_events.json updated_at=2026-08-28 09:05:49，扫描14只异动6条（北京君正/国瓷材料/征和工业/风华高科/工业富联急拉 +5%~+9%）✅
- 步骤3 signal.py：signals.json 信号5条（进攻5：北京君正/国瓷材料/征和工业/风华高科/工业富联；防守0）✅
- 步骤4 westock-mcp data_sector(ranking,sw1) 返回申万一级全行业124条→sector_raw_westock.json(updated_at 09:10)→refresh_sector_data.py→sector_leader_data.json(updated_at 09:10, top_inflow=57/top_outflow=67/astocks=5213)。流入TOP：非金属材料Ⅱ(+9.63%,主净+7.6亿)、电子化学品Ⅱ(+5.56%,+31.3亿)、玻璃玻纤(+5.36%,+17.0亿) ✅
- 步骤5 mx-ds-mcp：本次连接器已恢复(connected)，4缓存全部以真实数据刷新：macro_commodity(09:18, 金4594.49/-1.38%、银69.22/+1.66%、WTI83.54/+1.99%、布油89.56/+0.82%、伦铜14490/-0.28%、美元99.13/-0.01%、10Y4.65%、VIX stale)、a_news_summary/global_news_summary(09:18, asof 08-28, 7条headlines+analysis)、sector_contrib_mx(09:20, 16只成分股change_pct/mcap_yi来自mx_ashare_finance_data 8/27) ✅
- 步骤6 build_dashboard.py：index.html 重建成功(3.8MB)；非致命警告 feed.get_indicators(list index out of range) 与 tushare us_daily 无权限，已回退腾讯API成功拉取美股ETF K线。
- 步骤7 提交推送：commit c96a9fb，push origin main 成功（7dad1f1..c96a9fb）。GitHub Pages 自动重建。
- 失败项：无（全链路通过）。
- 盘面特征：半导体链全爆发（前日科创50 +3.77%），非金属材料Ⅱ/电子化学品Ⅱ/元件/玻璃玻纤领涨；黄金高位4600+；美股纳指+1.57%、英伟达+8.7%催化A股科技修复。持仓端北京君正/国瓷/征和/风华/工业富联急拉触发进攻信号。

# 自动化执行记忆：量化工作台实时数据刷新

## 2026-08-26 09:16 (周三盘前) 执行
- 分支：main ✅（commit 7dad1f1，push 04d5ad2..7dad1f1 成功，GitHub Pages 自动重建）
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-26 09:06:18 ✅
- 步骤2 monitor.py：live_events.json updated_at=2026-08-26 09:06:27，扫描14只行情13条，异动2条（均为 critical 触止损：国瓷材料跌破64.07/-15%、风华高科跌破53.06/-15%）✅
- 步骤3 signal.py：signals.json updated_at=2026-08-26 09:06:35，信号2条（进攻0/防守2，均 long仓纪律止损：国瓷材料@63.24、风华高科@51.33）✅
- 步骤4 westock-mcp data_sector(ranking,sw1,limit=30)：**实际返回全量124个申万一级行业（limit未截断）**，已落盘 _westock_rank_raw.json 再转写为 sector_raw_westock.json（新增 scripts/_transcribe_sector.py，按净流入>0取前30 / <0取前20，避免看板TOP30表过长）。→ sector_raw_westock.json updated_at=2026-08-26T09:11:43 → refresh_sector_data.py → sector_leader_data.json updated_at=2026-08-26T09:11:43（top_inflow=30/top_outflow=20/astocks=5213）。净流入TOP3：通信设备(+23.4亿)/元件(+20.8亿)/专用设备(+20.3亿)；净流出TOP3：工业金属(-26.3亿)/电池(-25.4亿)/半导体(-18.2亿)。贵金属(-3.83%)/能源金属(-3.84%)领跌（油价暴跌拖累）。
- 步骤5 mx-ds-mcp：**本次已连通（前次8/24 OAuth过期，本次正常）**，4缓存全部真刷新（updated_at 均 2026-08-26 09:15，asof 2026-08-25 真实数据日）：macro_commodity(WTI81.11/-4.59%、布油88.58/-3.9%、COMEX金4715.9/+0.39%、DXY98.914、10Y美债4.635)、a_news_summary(7条，十五五新型工业化/芯片设计高光/脑机接口政策等)、global_news_summary(7条+analysis dict，霍尔木兹停火致油价暴跌/英伟达财报/中概+1.11%)、sector_contrib_mx(16只成分股市值+涨跌幅，600570恒生电子 mx未返回沿用旧值)。新增 scripts/_refresh_mx_caches.py。
- **修复 build_dashboard.py 崩溃**：_news_hotspot_card 期望 global_news_summary.json 的 analysis 为 dict{title,subtitle,points,conclusion}，首版误填 list 导致 AttributeError；改为 dict 后重建成功（index.html 3.74MB）。非致命：tushare us_daily 无权限，已回退腾讯API抓取9只美股ETF K线(各251点)。
- 盘面特征（盘前快照）：油价因霍尔木兹临时航道+美伊停火预期重挫(WTI破82/布油跌近4%)，避险资产(贵金属/能源金属)跟跌；持仓国瓷材料/风华高科触发long仓-15%纪律止损信号；半导体主力净流出-18.2亿但板块仅-0.2%分化；科技股隔夜反弹(英伟达+2%止步七连跌)待今晚财报与核心PCE验证。

## 2026-08-24 09:06 (周一盘前) 执行
- 分支：main ✅（commit c9b1b11，push 646a570..c9b1b11 成功，GitHub Pages 自动重建）
- 步骤1 feed.py：market_snapshot.json updated_at=2026-08-24 09:06:04 ✅
- 步骤2 monitor.py：live_events.json updated_at=2026-08-24 09:06:09，扫描14只异动6条（北大荒急跌-5.94%、国瓷/征和/东田微急拉、国瓷/东田微高换手）✅
- 步骤3 signal.py：signals.json updated_at=2026-08-24 09:06:14，信号4条（进攻3：国瓷材料/征和工业/东田微 买入；防守1：北大荒 减仓回避）✅
- 步骤4 westock-mcp data_sector(ranking,sw1,30) ✅ → sector_raw_westock.json updated_at=2026-08-24T09:07:22 → refresh_sector_data.py → sector_leader_data.json updated_at=2026-08-24T09:07:22（top_inflow=7/top_outflow=3）。流入TOP3：通信设备(+2.98%,主净+88.9亿)、元件(+2.80%,+46.8亿)、工业金属(+2.42%,+44.4亿)；流出TOP3：化学制药(-4.33%,-34.1亿)、医疗服务(-3.75%,-28.3亿)、生物制品(-3.63%,-11.4亿)。
- 步骤5 mx-ds-mcp：⚠️ **OAuth 令牌过期需重新授权**（mx_macro_data 与 global news 两次调用均报"requires re-authorization"，重试仍失败，按技能文档 401 不可重试）。A股新闻那次调用成功 → a_news_summary.json 真实刷新(updated_at 2026-08-24 09:08)。macro_commodity/global_news_summary/sector_contrib_mx 三项保留原值未伪造时间戳（asof 分别 8/21/8/21/8/14）。**需用户重连 mx-ds-mcp 授权**。
- 步骤6 build_dashboard.py：index.html 重建成功(4.1MB)；非致命警告 feed.get_indicators(list index out of range) 与 tushare us_daily 无权限，已回退腾讯源成功拉取美股ETF K线。
- 盘面特征：贵金属/能源金属/通信硬件/锂矿/元件领涨；医药链(化学制药/医疗服务/生物制品)集体回调，北大荒急跌-5.94%触发防守信号；国瓷材料急拉+7.85%触发进攻。

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
