"""一次性注入：把浏览器端实时行情轮询逻辑嵌入已生成的 index.html。

用于「保留历史数据 + 增加实时刷新」场景（例如非交易日重新部署时，
扫描数据为空，但线上页面需要保留上一交易日的备选池/指数展示）。

覆盖范围（在原有 指数/备选池/回测 基础上扩展）：
- ④ A股热力全景图（资金流向前50名）：涨跌幅列实时刷新
- ⑤ 持仓复盘：现价/盈亏%/总盈亏/当日盈亏 实时刷新（成本与股数取自页面快照）

实时源：东方财富 push2 (HTTPS + JSONP)，绕过 GitHub Pages 的 CORS/混合内容限制。
名称->代码 解析：腾讯 smartbox (HTTPS)，构建期一次性解析并写回 data-code，
              避免浏览器端批量解析带来的延迟与不确定性。
"""
import re, time, urllib.parse, requests

P = "index.html"
html = open(P, encoding="utf-8").read()
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def resolve_name_to_code(name):
    """腾讯 smartbox 名称->代码。返回 'sh601606' / 'sz300058' 或 None。"""
    try:
        r = requests.get("https://smartbox.gtimg.cn/s3/", params={"v": 2, "t": "all", "q": name},
                         headers=UA, timeout=8)
        m = re.search(r'v_hint="([^"]*)"', r.text)
        if m:
            parts = m.group(1).split("~")
            if len(parts) >= 2 and re.fullmatch(r"[a-z]{2}", parts[0]) and re.fullmatch(r"\d{6}", parts[1]):
                return parts[0] + parts[1]
    except Exception:
        pass
    return None


# ---- 1. 收集热力图 / 持仓表中所有股票名 ----
flow_m = re.search(r'<table class="flow-table"[^>]*>.*?</table>', html, re.DOTALL)
pos_m = re.search(r'<table class="position-table"[^>]*>.*?</table>', html, re.DOTALL)
names = set()
if flow_m:
    names |= set(re.findall(r"<strong>([^<]+)</strong>", flow_m.group(0)))
if pos_m:
    names |= set(re.findall(r"<strong>([^<]+)</strong>", pos_m.group(0)))

name_to_code = {}
for n in sorted(names):
    c = resolve_name_to_code(n)
    if c:
        name_to_code[n] = c
    time.sleep(0.12)  # 轻微限速，避免触发腾讯风控
print("RESOLVED %d/%d names -> codes" % (len(name_to_code), len(names)))


def _add_attr(tr, attr):
    return re.sub(r"^<tr(\s|>)", r"<tr%s\1" % attr, tr, count=1)


def process_flow(table_html):
    def repl(m):
        tr = m.group(0)
        if "data-code" in tr:
            return tr
        sm = re.search(r"<strong>([^<]+)</strong>", tr)
        if not sm:
            return tr
        code = name_to_code.get(sm.group(1).strip())
        if not code:
            return tr
        return _add_attr(tr, ' data-code="%s" data-rt="flow"' % code)
    return re.sub(r"<tr[^>]*>.*?</tr>", repl, table_html, flags=re.DOTALL)


def process_positions(table_html):
    def repl(m):
        tr = m.group(0)
        if "data-code" in tr:
            return tr
        sm = re.search(r"<strong>([^<]+)</strong>", tr)
        if not sm:
            return tr
        code = name_to_code.get(sm.group(1).strip())
        if not code:
            return tr
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        shares = re.sub(r"[^\d.]", "", tds[1]) if len(tds) > 1 else ""
        cost = re.sub(r"[^\d.\-]", "", tds[2]) if len(tds) > 2 else ""
        attr = ' data-code="%s" data-rt="pos" data-shares="%s" data-cost="%s"' % (code, shares, cost)
        return _add_attr(tr, attr)
    return re.sub(r"<tr[^>]*>.*?</tr>", repl, table_html, flags=re.DOTALL)


if flow_m:
    new = process_flow(flow_m.group(0))
    html = html[:flow_m.start()] + new + html[flow_m.end():]
    # 重新定位持仓表（flow 替换后偏移变化）
    pos_m = re.search(r'<table class="position-table"[^>]*>.*?</table>', html, re.DOTALL)
if pos_m:
    new = process_positions(pos_m.group(0))
    html = html[:pos_m.start()] + new + html[pos_m.end():]


# ---- 2. 实时 JS（含 热力图/持仓 刷新 + 手动刷新按钮）----
RT_JS = r'''
(function(){
  var s=document.createElement('style');
  s.textContent=''
    +'.live-badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:3px 9px;border-radius:20px;background:rgba(34,197,94,.15);color:#16a34a;font-weight:500;margin-left:8px;}'
    +'.live-badge .dot{width:7px;height:7px;border-radius:50%;background:#16a34a;animation:rtpulse 1.4s infinite;}'
    +'.live-badge.off{background:rgba(148,163,184,.15);color:#94a3b8;}'
    +'.live-badge.off .dot{background:#94a3b8;animation:none;}'
    +'@keyframes rtpulse{0%,100%{opacity:1}50%{opacity:.3}}'
    +'@keyframes rtflashUp{0%{background:rgba(239,68,68,.40)}100%{background:transparent}}'
    +'@keyframes rtflashDown{0%{background:rgba(34,197,94,.40)}100%{background:transparent}}'
    +'.rt-flash-up{animation:rtflashUp .9s ease-out;}'
    +'.rt-flash-down{animation:rtflashDown .9s ease-out;}'
    +'.rt-refresh-btn{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:3px 10px;border-radius:20px;border:1px solid var(--border-color);background:rgba(79,195,247,.12);color:#4fc3f7;cursor:pointer;font-weight:500;margin-left:8px;transition:.2s;}'
    +'.rt-refresh-btn:hover{background:rgba(79,195,247,.25);}'
    +'.rt-refresh-btn:disabled{opacity:.6;cursor:default;}'
    +'.rt-refresh-btn.spinning i{animation:rtspin .8s linear infinite;}'
    +'@keyframes rtspin{from{transform:rotate(0)}to{transform:rotate(360deg)}}';
  document.head.appendChild(s);
})();

function toEmSecid(code){
  code=(code||'').trim().toLowerCase();
  if(code.indexOf('sh')===0) return '1.'+code.slice(2);
  if(code.indexOf('sz')===0) return '0.'+code.slice(2);
  if(code.indexOf('bj')===0) return '0.'+code.slice(2);
  code=code.replace(/[^0-9]/g,'');
  if(code.length!==6) return '';
  if(code[0]==='6'||code[0]==='9') return '1.'+code;
  return '0.'+code;
}
function rightSecid(){
  var c=document.getElementById('btCode');
  if(!c) return null;
  var t=(c.textContent||'').trim().toUpperCase();
  if(t.indexOf('SH')===0) return '1.'+t.slice(2);
  if(t.indexOf('SZ')===0) return '0.'+t.slice(2);
  if(t.indexOf('BJ')===0) return '0.'+t.slice(2);
  return null;
}
var RT_INDEX=[], RT_PICK_MAP={}, RT_FLOW=[], RT_POS=[];
function collectRT(){
  RT_INDEX=[];
  document.querySelectorAll('.index-mini-item').forEach(function(el){
    var sid=el.getAttribute('data-secid');
    if(!sid){ var dc=el.getAttribute('data-code'); if(dc) sid=toEmSecid(dc); }
    if(sid){ el.setAttribute('data-secid', sid); RT_INDEX.push(sid); }
  });
  RT_PICK_MAP={};
  document.querySelectorAll('#picksTable tbody tr[data-code]').forEach(function(tr){
    var sid=toEmSecid(tr.getAttribute('data-code'));
    if(sid) RT_PICK_MAP[sid]=tr;
  });
  RT_FLOW=[];
  document.querySelectorAll('.flow-table tbody tr[data-code]').forEach(function(tr){
    var sid=toEmSecid(tr.getAttribute('data-code'));
    if(sid){ tr.setAttribute('data-secid', sid); RT_FLOW.push(sid); }
  });
  RT_POS=[];
  document.querySelectorAll('.position-table tbody tr[data-code]').forEach(function(tr){
    var sid=toEmSecid(tr.getAttribute('data-code'));
    if(sid){ tr.setAttribute('data-secid', sid); RT_POS.push(sid); }
  });
}
function flashEl(el, up){
  if(!el) return;
  el.classList.remove('rt-flash-up','rt-flash-down');
  void el.offsetWidth;
  el.classList.add(up?'rt-flash-up':'rt-flash-down');
}
function fmtMoney(v){
  var sign=v>=0?'+':'-'; var a=Math.abs(v);
  if(a>=10000) return sign+(a/10000).toFixed(2)+'万';
  return sign+a.toFixed(2);
}
function applyRealtime(data){
  var diff=(data&&data.data&&data.data.diff)||[];
  var right=rightSecid();
  diff.forEach(function(d){
    var sid=d.f13+'.'+d.f12;
    var price=(d.f2==='-'||d.f2==null)?'—':(d.f2/100).toFixed(2);
    var pct=(d.f3/100);
    var pctStr=(pct>=0?'+':'')+pct.toFixed(2)+'%';
    var up=pct>=0;
    if(RT_INDEX.indexOf(sid)>=0){
      var el=document.querySelector('.index-mini-item[data-secid="'+sid+'"]');
      if(el){
        var p=el.querySelector('.index-mini-price');
        var c=el.querySelector('.index-mini-change');
        if(p)p.textContent=price;
        if(c){c.textContent=pctStr;c.className='index-mini-change '+(up?'up':'down');}
      }
    }
    var tr=RT_PICK_MAP[sid];
    if(tr){
      var tp=tr.children[1]; var pc=tr.children[2];
      if(tp){tp.textContent=price;flashEl(tp,up);}
      if(pc){pc.textContent=pctStr;pc.style.color=up?'#ef4444':'#22c55e';flashEl(pc,up);}
    }
    var ftr=document.querySelector('.flow-table tbody tr[data-secid="'+sid+'"]');
    if(ftr){
      var fc=ftr.children[4];
      if(fc){fc.textContent=pctStr;fc.style.color=up?'#ef4444':'#22c55e';flashEl(fc,up);}
    }
    var ptr=document.querySelector('.position-table tbody tr[data-secid="'+sid+'"]');
    if(ptr){
      var pprice=ptr.children[3], pPct=ptr.children[4], pTotal=ptr.children[5], pDay=ptr.children[6];
      var shares=parseFloat((ptr.getAttribute('data-shares')||'').replace(/[^\d.]/g,''))||0;
      var cost=parseFloat(ptr.getAttribute('data-cost')||'NaN');
      if(pprice){pprice.textContent=price;flashEl(pprice,up);}
      if(!isNaN(cost)&&cost>0&&shares>0){
        var px=parseFloat(price);
        if(pPct){var pp=(px-cost)/cost*100;pPct.textContent=(pp>=0?'+':'')+pp.toFixed(2)+'%';pPct.style.color=pp>=0?'#ef4444':'#22c55e';}
        if(pTotal){var tot=(px-cost)*shares;pTotal.textContent=fmtMoney(tot);pTotal.style.color=tot>=0?'#ef4444':'#22c55e';}
      }
      if(pDay&&d.f18&&d.f18!=='-'&&shares>0){
        var prev=d.f18/100; var dayPnl=(parseFloat(price)-prev)*shares;
        pDay.textContent=fmtMoney(dayPnl); pDay.style.color=dayPnl>=0?'#ef4444':'#22c55e';
      }
    }
    if(right && sid===right){
      var bp=document.getElementById('btPrice');
      var bc=document.getElementById('btPct');
      if(bp)bp.textContent=price;
      if(bc){bc.textContent=pctStr;bc.style.color=up?'#ef4444':'#22c55e';}
    }
  });
  updateRtStatus(true);
}
function emJsonp(secids, cbName){
  return new Promise(function(resolve){
    var s=document.createElement('script');
    window[cbName]=function(d){ resolve(d); try{delete window[cbName];}catch(e){}; if(s.parentNode)s.parentNode.removeChild(s); };
    s.src='https://push2.eastmoney.com/api/qt/ulist.np/get?secids='+secids.join(',')+'&fields=f2,f3,f4,f12,f13,f14,f18&invt=2&cb='+cbName+'&_='+Date.now();
    s.onerror=function(){ resolve(null); if(s.parentNode)s.parentNode.removeChild(s); };
    document.body.appendChild(s);
  });
}
function isTrading(){
  var n=new Date(); var day=n.getDay();
  if(day===0||day===6) return false;
  var hm=n.getHours()*60+n.getMinutes();
  return (hm>=570 && hm<=690) || (hm>=780 && hm<=900);
}
function updateRtStatus(ok){
  var el=document.getElementById('rtStatus');
  if(!el) return;
  if(ok){ el.className='live-badge'; el.innerHTML='<i class="dot"></i> 实时 · '+(isTrading()?'交易中':'已休市'); }
  else { el.className='live-badge off'; el.innerHTML='<i class="dot"></i> 连接中…'; }
}
var RT_TIMER=null;
function rtTick(){
  var secids=RT_INDEX.concat(Object.keys(RT_PICK_MAP), RT_FLOW, RT_POS);
  var right=rightSecid(); if(right) secids.push(right);
  secids=secids.filter(function(v,i){return secids.indexOf(v)===i;});
  if(!secids.length) return;
  var batches=[]; for(var i=0;i<secids.length;i+=40) batches.push(secids.slice(i,i+40));
  var chain=Promise.resolve();
  batches.forEach(function(b){
    chain=chain.then(function(){
      var cb='emrt_'+Math.random().toString(36).slice(2,10);
      return emJsonp(b,cb).then(function(d){ if(d) applyRealtime(d); });
    });
  });
}
function rtManualRefresh(){
  var b=document.getElementById('rtRefreshBtn');
  if(b){ b.disabled=true; b.classList.add('spinning'); }
  updateRtStatus(false);
  rtTick();
  setTimeout(function(){ if(b){ b.disabled=false; b.classList.remove('spinning'); } updateRtStatus(true); }, 1600);
}
function startRealtime(){
  collectRT();
  updateRtStatus(false);
  rtTick();
  if(RT_TIMER) clearInterval(RT_TIMER);
  RT_TIMER=setInterval(rtTick, isTrading()?5000:30000);
  setInterval(function(){
    clearInterval(RT_TIMER);
    RT_TIMER=setInterval(rtTick, isTrading()?5000:30000);
  }, 60000);
}
'''

# 3) header 加 LIVE 指示器 + 手动刷新按钮（在第一个 status-badge 之后）
html = re.sub(
    r'(<span class="status-badge"[^>]*>.*?</span>)',
    lambda m: m.group(1)
    + '\n            <span class="live-badge off" id="rtStatus"><i class="dot"></i> 连接中…</span>'
    + '\n            <button id="rtRefreshBtn" class="rt-refresh-btn" onclick="rtManualRefresh()" title="立即刷新所有行情"><i class="fas fa-sync-alt"></i> 立即刷新</button>',
    html, count=1)

# 4) DOMContentLoaded 启动实时轮询
html = re.sub(r'loadIndexSpark\(\);', 'loadIndexSpark();\n    startRealtime();', html, count=1)

# 5) 注入实时 JS 到最后一个 </script> 之前（内联脚本块）
idx = html.rfind('</script>')
html = html[:idx] + RT_JS + '\n' + html[idx:]

open(P, "w", encoding="utf-8").write(html)
print("INJECT_DONE lines=", html.count("\n"))
