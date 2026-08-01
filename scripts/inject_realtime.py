"""一次性注入：把浏览器端实时行情轮询逻辑嵌入已生成的 index.html。

用于「保留历史数据 + 增加实时刷新」场景（例如非交易日重新部署时，
扫描数据为空，但线上页面需要保留上一交易日的备选池/指数展示）。
实时源：东方财富 push2 (HTTPS + JSONP)，绕过 GitHub Pages 的 CORS/混合内容限制。
"""
import re

P = "index.html"
html = open(P, encoding="utf-8").read()

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
    +'.rt-flash-down{animation:rtflashDown .9s ease-out;}';
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
var RT_INDEX=[], RT_PICK_MAP={};
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
}
function flashEl(el, up){
  if(!el) return;
  el.classList.remove('rt-flash-up','rt-flash-down');
  void el.offsetWidth;
  el.classList.add(up?'rt-flash-up':'rt-flash-down');
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
    s.src='https://push2.eastmoney.com/api/qt/ulist.np/get?secids='+secids.join(',')+'&fields=f2,f3,f4,f12,f13,f14&invt=2&cb='+cbName+'&_='+Date.now();
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
  var secids=RT_INDEX.concat(Object.keys(RT_PICK_MAP));
  var right=rightSecid(); if(right) secids.push(right);
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

# 1) header 加 LIVE 指示器（在第一个 status-badge 之后）
html = re.sub(
    r'(<span class="status-badge"[^>]*>.*?</span>)',
    lambda m: m.group(1) + '\n            <span class="live-badge off" id="rtStatus"><i class="dot"></i> 连接中…</span>',
    html, count=1)

# 2) DOMContentLoaded 启动实时轮询
html = re.sub(r'loadIndexSpark\(\);', 'loadIndexSpark();\n    startRealtime();', html, count=1)

# 3) 注入实时 JS 到最后一个 </script> 之前（内联脚本块）
idx = html.rfind('</script>')
html = html[:idx] + RT_JS + '\n' + html[idx:]

open(P, "w", encoding="utf-8").write(html)
print("INJECT_DONE lines=", html.count("\n"))
