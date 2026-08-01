#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_layout_opt.py —— 对已有 index.html 做右栏布局紧凑化注入：
  1. 右栏独立滚动（max-height: calc(100vh - 40px)）
  2. 回测引擎卡片改为 Tab 切换（参数 / 绩效 / 明细）
  3. K 线图高度从 284px 降到 180px，减少右栏纵向长度

用法（在仓库根目录）：
  python scripts/inject_layout_opt.py
"""
import re
import sys

HTML = "index.html"


def main():
    with open(HTML, encoding="utf-8") as f:
        html = f.read()

    if "btTab-params" in html:
        print("OK: 布局优化已存在，跳过")
        return

    # ---- 1. CSS：右栏滚动 + Tab 样式 ----
    # 在 .radar-col 定义后追加右栏滚动
    html = html.replace(
        ".radar-col { display:flex; flex-direction:column; gap:16px; }",
        """.radar-col { display:flex; flex-direction:column; gap:16px; }
        .radar-col:last-child { max-height:calc(100vh - 40px); overflow-y:auto; padding-right:6px; }
        .radar-col:last-child::-webkit-scrollbar { width:5px; }
        .radar-col:last-child::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.15); border-radius:3px; }
        .radar-col:last-child::-webkit-scrollbar-track { background:transparent; }""",
    )

    # 降低 K 线图高度
    html = html.replace(
        "height:284px; margin-bottom:14px;",
        "height:180px; margin-bottom:10px;",
    )

    # 注入 Tab CSS（放在第一个 </style> 之前）
    tab_css = """
        .bt-tabs { display:flex; gap:6px; margin:10px 0 8px; }
        .bt-tab { flex:1; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); color:var(--text-secondary); border-radius:7px; padding:6px 0; font-size:11px; font-weight:600; cursor:pointer; transition:all .18s; }
        .bt-tab:hover { border-color:var(--accent-gold); color:var(--text-primary); }
        .bt-tab.active { background:linear-gradient(135deg,#f59e0b,#ef4444); color:#fff; border-color:transparent; box-shadow:0 2px 8px rgba(239,68,68,0.35); }
        .bt-tab-panel { display:none; animation:btFadeIn .22s ease; }
        .bt-tab-panel.active { display:block; }
        @keyframes btFadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
"""
    # 找到第一个 </style> 并在此之前插入
    first_style_end = html.find("</style>")
    if first_style_end == -1:
        print("ERR: 找不到 </style>")
        sys.exit(1)
    html = html[:first_style_end] + tab_css + html[first_style_end:]

    # ---- 2. HTML：把回测卡片内容改成 Tab 结构 ----
    # 定位：在 symbol select 后插入 Tab 按钮，并把三段内容分别包进 panel
    symbol_row_end = html.find('</select>\n        </div>\n        <div id="btChart"')
    if symbol_row_end == -1:
        print("ERR: 找不到 backtest symbol select")
        sys.exit(1)

    tabs_html = """</select>
        </div>
        <div class="bt-tabs">
            <button type="button" class="bt-tab active" data-tab="params" onclick="switchBTTab('params')"><i class="fas fa-cog"></i> 参数</button>
            <button type="button" class="bt-tab" data-tab="metrics" onclick="switchBTTab('metrics')"><i class="fas fa-trophy"></i> 绩效</button>
            <button type="button" class="bt-tab" data-tab="trades" onclick="switchBTTab('trades')"><i class="fas fa-list"></i> 明细</button>
        </div>
"""
    html = html[:symbol_row_end] + tabs_html + html[symbol_row_end + len('</select>\n        </div>\n'):]

    # 现在包裹三个 panel
    # params panel: 从 <div id="btChart" 到 <button class="backtest-btn" ...>开始回测</button>
    params_start = html.find('<div id="btChart"')
    btn_end = html.find('</button>\n        <div class="backtest-param-title"><i class="fas fa-trophy"></i>')
    if params_start == -1 or btn_end == -1:
        print("ERR: 无法定位 params/metrics 边界")
        sys.exit(1)
    # btn_end 当前是开始回测按钮的 </button> 结束位置，要包含它
    btn_end += len("</button>")
    params_content = html[params_start:btn_end]

    # metrics panel: 从 <div class="backtest-param-title"><i class="fas fa-trophy"></i> 回测绩效</div> 到 metrics </div>
    metrics_start_label = '<div class="backtest-param-title"><i class="fas fa-trophy"></i> 回测绩效</div>'
    metrics_start = html.find(metrics_start_label)
    metrics_end = html.find('</div>\n        <div class="backtest-trades">', metrics_start)
    if metrics_start == -1 or metrics_end == -1:
        print("ERR: 无法定位 metrics 边界")
        sys.exit(1)
    metrics_end += len("</div>")
    metrics_content = html[metrics_start:metrics_end]

    # trades panel: 从 <div class="backtest-trades"> 到 </div>（匹配 radar-card 内的 closing）
    trades_start = html.find('<div class="backtest-trades">')
    if trades_start == -1:
        print("ERR: 无法定位 trades 开始")
        sys.exit(1)
    # 找到 trades div 对应的结束标签：从 trades_start 之后找 "</div>" 且后面紧跟 radar-card 的结束
    trades_end = html.find('</div>\n    </div>', trades_start)
    if trades_end == -1:
        print("ERR: 无法定位 trades 结束")
        sys.exit(1)
    trades_content = html[trades_start:trades_end]

    # 替换原区间为三个 panel
    new_block = f"""<div id="btTab-params" class="bt-tab-panel active">
            {params_content}
        </div>
        <div id="btTab-metrics" class="bt-tab-panel">
            {metrics_content}
        </div>
        <div id="btTab-trades" class="bt-tab-panel">
            {trades_content}
        </div>"""
    html = html[:params_start] + new_block + html[trades_end:]

    # ---- 3. JS：加入 switchBTTab ----
    switch_fn = """function switchBTTab(tab){
    document.querySelectorAll('.bt-tab').forEach(b => b.classList.toggle('active', b.getAttribute('data-tab') === tab));
    document.querySelectorAll('.bt-tab-panel').forEach(p => p.classList.toggle('active', p.id === 'btTab-' + tab));
    if(window.btChart && tab === 'params'){ setTimeout(function(){ window.btChart.resize(); }, 50); }
}

"""
    # 放在第一个 </script> 之前
    first_script_end = html.find("</script>")
    if first_script_end == -1:
        print("ERR: 找不到 </script>")
        sys.exit(1)
    html = html[:first_script_end] + switch_fn + html[first_script_end:]

    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK: 布局优化已注入")


if __name__ == "__main__":
    main()
