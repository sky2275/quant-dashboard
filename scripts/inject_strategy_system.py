#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_strategy_system.py —— 把「三仓策略执行系统」注入现有 index.html

设计：
  - 读取 config/strategy.yaml 中的 capital / buckets / holdings(bucket,stop) / dividend_pool / risk
  - 用腾讯 smartbox 把持仓名、股息池名解析成代码(sh600900)并写回 data-code
  - 在「⑤ 持仓复盘」卡片前插入一张新卡片：三仓分配 + 持仓分组(含止损价) + 高股息观察池 + 仓位/止损计算器 + 组合回撤监控
  - 在 </body> 前注入独立 JS：自带的 fetchQtQuotes 刷新新行（腾讯 qt.gtimg.cn），并挂 5s/30s 轮询
  - 不改动原有任何模块，保留已部署的真实数据

用法：
  python scripts/inject_strategy_system.py
"""
from __future__ import annotations
import os, re, sys, json
import yaml
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(REPO, "index.html")
CFG = os.path.join(REPO, "config", "strategy.yaml")
UA = {"User-Agent": "Mozilla/5.0"}


def resolve_code(name: str):
    """名称->完整代码(sh600900/sz000001)。腾讯 smartbox 优先，本地硬编码兜底。"""
    fallback = {
        "永安行": "sh603776", "北京君正": "sz300223", "绿的谐波": "sh688017",
        "征和工业": "sz003033", "科大讯飞": "sz002230",
        "长电科技": "sh600584", "通富微电": "sz002156",
        "中装建设": "sz002822", "长高电力": "sz002452",
        "工商银行": "sh601398", "大秦铁路": "sh601006",
        "陕西煤业": "sh601225", "江苏银行": "sh600919",
    }
    try:
        r = requests.get("https://smartbox.gtimg.cn/s3/", params={"v": 2, "t": "all", "q": name},
                         headers=UA, timeout=10)
        m = re.search(r'v_hint="([^"]+)"', r.text)
        if m:
            parts = m.group(1).split("~")
            if len(parts) >= 2 and parts[0] in ("sh", "sz", "bj") and parts[1]:
                return parts[0] + parts[1]
    except Exception:
        pass
    return fallback.get(name)


def main():
    cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
    capital = float(cfg.get("capital", 300000))
    buckets = cfg.get("buckets", {})
    holdings = cfg.get("holdings", [])
    div_pool = cfg.get("dividend_pool", [])
    risk = cfg.get("risk", {})

    # 解析代码
    for h in holdings:
        h["_code"] = resolve_code(h["code"]) or ""
    for d in div_pool:
        d["_code"] = resolve_code(d["name"]) or ""

    bucket_label = {k: v.get("label", k) for k, v in buckets.items()}

    # ---- 分配条 ----
    alloc_html = ""
    order = ["long", "dividend", "short"]
    for k in order:
        b = buckets.get(k, {})
        w = float(b.get("weight", 0))
        amt = capital * w / 100
        alloc_html += (
            f'<div class="alloc-item alloc-{k}">'
            f'<span class="alloc-name">{b.get("label", k)}</span>'
            f'<b class="alloc-amt">{amt/10000:.1f}万</b>'
            f'<i class="alloc-pct">{w:.0f}%</i>'
            f'<span class="alloc-desc">{b.get("desc", "")}</span>'
            f'</div>'
        )

    # ---- 持仓分组表 ----
    rows = ""
    for h in holdings:
        code = h.get("_code", "")
        bucket = h.get("bucket", "long")
        stop = float(h.get("stop", 0.08))
        rows += (
            f'<tr data-code="{code}" data-rt="strat" data-cost="{h["cost"]}" data-stop="{stop}">'
            f'<td><strong>{h["code"]}</strong></td>'
            f'<td class="mono">{code}</td>'
            f'<td>{h["cost"]:.2f}</td>'
            f'<td class="rt-sprice">{h.get("price", "—")}</td>'
            f'<td class="rt-sstop">—</td>'
            f'<td class="rt-spct">—</td>'
            f'<td><span class="tag tag-{bucket}">{bucket_label.get(bucket, bucket)}</span></td>'
            f'</tr>'
        )

    # ---- 高股息观察池 ----
    div_rows = ""
    for d in div_pool:
        code = d.get("_code", "")
        div_rows += (
            f'<tr data-code="{code}" data-rt="div" data-yield="{d.get("yield", 0)}">'
            f'<td><strong>{d["name"]}</strong></td>'
            f'<td class="mono">{code}</td>'
            f'<td class="rt-sprice">—</td>'
            f'<td>{d.get("yield", 0)}%</td>'
            f'<td class="rt-spct">—</td>'
            f'</tr>'
        )

    risk_badge = (
        f'单日≥{risk.get("single_day_drawdown",2)}%减半 · '
        f'月≥{risk.get("month_drawdown",6)}%清仓 · '
        f'单票≤{risk.get("single_position_max",25)}%'
    )

    card = f'''
    <div class="card card-full" id="strategyCard">
        <div class="card-title">
            <span class="icon"><i class="fas fa-sitemap"></i></span> 三仓策略执行
            <span class="badge">STRATEGY EXECUTION</span>
            <span class="badge" style="background:rgba(245,158,11,0.15);color:#f59e0b;" id="stratDrawdown">组合回撤 —</span>
            <span class="click-hint">{risk_badge}</span>
        </div>
        <div class="strat-wrap">
            <div class="strat-alloc">{alloc_html}</div>
            <div class="strat-cols">
                <div class="strat-block">
                    <h4>持仓分组（止损价随实时价计算）</h4>
                    <table class="position-table" style="width:100%;">
                        <thead><tr><th>名称</th><th>代码</th><th>成本</th><th>现价</th><th>止损价</th><th>盈亏%</th><th>仓</th></tr></thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
                <div class="strat-block">
                    <h4>高股息观察池</h4>
                    <table class="position-table" style="width:100%;">
                        <thead><tr><th>名称</th><th>代码</th><th>现价</th><th>股息率</th><th>涨跌%</th></tr></thead>
                        <tbody>{div_rows}</tbody>
                    </table>
                </div>
            </div>
            <div class="strat-calc">
                <h4>仓位 / 止损计算器</h4>
                <div class="calc-row">
                    <label>总本金<input id="calcCapital" type="number" value="{capital:.0f}"></label>
                    <label>长线%<input id="calcLong" type="number" value="{buckets.get('long',{}).get('weight',50)}"></label>
                    <label>高股息%<input id="calcDiv" type="number" value="{buckets.get('dividend',{}).get('weight',30)}"></label>
                    <label>短线%<input id="calcShort" type="number" value="{buckets.get('short',{}).get('weight',20)}"></label>
                    <button onclick="calcAlloc()">算仓位</button>
                </div>
                <div id="calcOut" class="calc-out"></div>
                <div class="calc-row" style="margin-top:8px;">
                    <label>个股价格<input id="calcPrice" type="number" placeholder="如 68.9"></label>
                    <label>止损%<input id="calcStop" type="number" value="8"></label>
                    <label>投入金额<input id="calcAmt" type="number" placeholder="如 60000"></label>
                    <button onclick="calcStop()">算止损价/股数</button>
                </div>
                <div id="calcStopOut" class="calc-out"></div>
            </div>
        </div>
    </div>
'''

    html = open(HTML, encoding="utf-8").read()

    marker = '    <div class="card card-full" onclick="openModal(\'positions\')">'
    if marker not in html:
        print("ERROR: 未找到插入锚点（持仓复盘卡片）")
        sys.exit(1)
    if "id=\"strategyCard\"" in html:
        print("WARN: 已注入过 strategyCard，跳过插入")
    else:
        html = html.replace(marker, card + "\n" + marker, 1)

    # ---- CSS ----
    css = '''
    <style>
    .strat-wrap{padding:4px 2px;}
    .strat-alloc{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px;}
    .alloc-item{background:var(--bg-tertiary,rgba(255,255,255,0.03));border:1px solid var(--border-color,rgba(255,255,255,0.08));border-radius:10px;padding:10px 12px;position:relative;}
    .alloc-item .alloc-name{display:block;font-size:12px;color:var(--text-secondary);}
    .alloc-item .alloc-amt{font-size:18px;font-weight:600;color:var(--text-primary);}
    .alloc-item .alloc-pct{position:absolute;top:10px;right:12px;font-size:12px;color:var(--accent-blue,#378ADD);}
    .alloc-item .alloc-desc{display:block;font-size:10px;color:var(--text-tertiary,#888);margin-top:4px;line-height:1.4;}
    .alloc-long{border-left:3px solid #378ADD;}
    .alloc-dividend{border-left:3px solid #22c55e;}
    .alloc-short{border-left:3px solid #f59e0b;}
    .strat-cols{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;}
    .strat-block h4{font-size:12px;color:var(--text-secondary);margin:6px 0 6px;font-weight:500;}
    .tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;}
    .tag-long{background:rgba(55,138,221,0.15);color:#85b7eb;}
    .tag-dividend{background:rgba(34,197,94,0.15);color:#5dcaa5;}
    .tag-short{background:rgba(245,158,11,0.15);color:#fac775;}
    .strat-calc{margin-top:12px;border-top:1px solid var(--border-color,rgba(255,255,255,0.08));padding-top:10px;}
    .strat-calc h4{font-size:12px;color:var(--text-secondary);margin:0 0 6px;font-weight:500;}
    .calc-row{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;}
    .calc-row label{display:flex;flex-direction:column;font-size:10px;color:var(--text-tertiary,#888);}
    .calc-row input{width:90px;background:var(--bg-tertiary,rgba(255,255,255,0.05));border:1px solid var(--border-color,rgba(255,255,255,0.1));color:var(--text-primary);border-radius:6px;padding:4px 6px;font-size:12px;margin-top:2px;}
    .calc-row button{background:var(--accent-blue,#378ADD);color:#fff;border:none;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;}
    .calc-out{font-size:12px;color:var(--text-primary);margin-top:6px;}
    .mono{font-family:var(--font-mono,monospace);font-size:11px;color:var(--text-secondary);}
    @media(max-width:760px){.strat-alloc{grid-template-columns:1fr;}.strat-cols{grid-template-columns:1fr;}}
    </style>
'''
    if "</head>" in html and ".strat-wrap" not in html:
        html = html.replace("</head>", css + "\n</head>", 1)

    # ---- JS ----
    js = '''
    <script>
    (function(){
      function toEmSecid(c){
        if(!c) return null;
        var m=c.match(/^(sh|sz|bj)(\\d+)$/);
        if(!m) return null;
        var p={sh:'1',sz:'0',bj:'0'}[m[1]];
        return p+'.'+m[2];
      }
      function em2code(sid){
        if(!sid||sid.indexOf('.')<0) return sid;
        var a=sid.split('.');
        var pre={ '1':'sh','0':'sz' }[a[0]]||'sh';
        return pre+a[1];
      }
      function stratRows(){
        return document.querySelectorAll('tr[data-rt="strat"],tr[data-rt="div"]');
      }
      async function fetchQtQuotes(codes){
        if(!codes.length) return {};
        try{
          var r=await fetch('https://qt.gtimg.cn/q='+codes.join(','));
          var text=await r.text();
          var out={};
          var re=/v_([a-z]{2}\\d{6})="([^"]+)"/g;
          var m;
          while((m=re.exec(text))){
            var code=m[1];
            var p=m[2].split('~');
            if(p.length<35) continue;
            out[code]={ name:p[1], code:p[2],
              price:parseFloat(p[3]),
              prev_close:parseFloat(p[4]),
              change_pct:parseFloat(p[32])/100 };
          }
          return out;
        }catch(e){ console.warn('inject fetchQtQuotes:',e); return {}; }
      }
      function applyStrat(qtMap){
        if(!qtMap) return;
        Object.keys(qtMap).forEach(function(code){
          var d=qtMap[code];
          var price=d.price, pct=d.change_pct;
          stratRows().forEach(function(tr){
            if(tr.getAttribute('data-code')!==code) return;
            var sp=tr.querySelector('.rt-sprice');
            var sc=tr.querySelector('.rt-spct');
            var st=tr.querySelector('.rt-sstop');
            var stop=parseFloat(tr.getAttribute('data-stop')||'0.08');
            if(sp && !isNaN(price)) sp.textContent=price.toFixed(2);
            if(sc && !isNaN(pct)){ sc.textContent=(pct>=0?'+':'')+pct.toFixed(2)+'%'; sc.style.color=pct>=0?'#ef4444':'#22c55e'; }
            if(st && !isNaN(price)) st.textContent=(price*(1-stop)).toFixed(2);
          });
        });
        updateStratSummary();
      }
      async function refreshStrategy(){
        var codes=[];
        stratRows().forEach(function(tr){ var c=tr.getAttribute('data-code'); if(c) codes.push(c); });
        if(!codes.length) return;
        var all={};
        for(var i=0;i<codes.length;i+=40){
          var b=codes.slice(i,i+40);
          try{ var d=await fetchQtQuotes(b); Object.assign(all, d); }catch(e){}
        }
        if(Object.keys(all).length) applyStrat(all);
      }
      function updateStratSummary(){
        var sum=0,n=0;
        document.querySelectorAll('tr[data-rt="strat"]').forEach(function(tr){
          var cost=parseFloat(tr.getAttribute('data-cost'));
          var sp=tr.querySelector('.rt-sprice');
          if(cost && sp && sp.textContent!=='—'){
            var p=parseFloat(sp.textContent);
            if(!isNaN(p)){ sum+=(p-cost)/cost*100; n++; }
          }
        });
        var el=document.getElementById('stratDrawdown');
        if(el && n){ var avg=sum/n; el.textContent='组合均值 '+(avg>=0?'+':'')+avg.toFixed(2)+'%'; el.style.color=avg>=0?'#ef4444':'#22c55e'; }
      }
      window.calcAlloc=function(){
        var cap=parseFloat(document.getElementById('calcCapital').value)||0;
        var wl=parseFloat(document.getElementById('calcLong').value)||0;
        var wd=parseFloat(document.getElementById('calcDiv').value)||0;
        var ws=parseFloat(document.getElementById('calcShort').value)||0;
        document.getElementById('calcOut').textContent=
          '长线: '+(cap*wl/100).toFixed(0)+'元 | 高股息: '+(cap*wd/100).toFixed(0)+'元 | 短线: '+(cap*ws/100).toFixed(0)+'元';
      };
      window.calcStop=function(){
        var p=parseFloat(document.getElementById('calcPrice').value)||0;
        var s=parseFloat(document.getElementById('calcStop').value)||0;
        var amt=parseFloat(document.getElementById('calcAmt').value)||0;
        if(!p){ document.getElementById('calcStopOut').textContent='请填写个股价格'; return; }
        var stopP=p*(1-s/100);
        var shares= amt? Math.floor(amt/p):0;
        document.getElementById('calcStopOut').textContent='止损价: '+stopP.toFixed(2)+' | 可买股数: '+shares+'（约 '+(shares*p).toFixed(0)+'元）';
      };
      // 初始刷新 + 跟随交易时段节奏
      function startStrat(){
        refreshStrategy();
        if(typeof isTrading==='function'){
          setInterval(refreshStrategy, isTrading()?5000:30000);
        } else {
          setInterval(refreshStrategy, 30000);
        }
      }
      if(document.readyState!=='loading') startStrat();
      else document.addEventListener('DOMContentLoaded', startStrat);
    })();
    </script>
'''
    if "</body>" in html and "function calcAlloc" not in html:
        html = html.replace("</body>", js + "\n</body>", 1)

    open(HTML, "w", encoding="utf-8").write(html)
    print("OK: 三仓策略系统已注入")
    print("  持仓行(data-rt=strat):", html.count('data-rt="strat"'))
    print("  股息行(data-rt=div):", html.count('data-rt="div"'))
    print("  计算器函数:", html.count("function calcAlloc"))


if __name__ == "__main__":
    main()
