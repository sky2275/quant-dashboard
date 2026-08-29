/* ============================================================
   RT V3 · 通用实时引擎（覆盖旧版 v1，自动接管）
   ------------------------------------------------------------
   设计目的：
     旧版 v1 只认 .index-mini-item / .flow-table / .position-table，
     而页面表格 class 已变更为 astock-table / picks-table / sector-table，
     持仓表更是 JS 动态渲染且无 class → 实时刷新大面积失效。
     V3 改为「通用表格扫描器」：按表头自动识别列，不依赖任何 class。

   能力：
     - 扫描页面所有 <table>，按表头文本识别 代码/现价/涨跌幅/成本/持股/盈亏 列
     - 只有股票名没有代码的行 → 用构建期注入的 NAME2CODE 映射解析
     - 持仓表自动重算 盈亏% / 总盈亏 / 当日盈亏
     - 支持 JS 动态渲染表格（MutationObserver + 30s 定时重扫）
     - 交易时段 5s 轮询，非交易时段 30s；切回页面立即刷新
     - 数据源：东方财富 push2 (JSONP)，绕过 GitHub Pages 的 CORS 限制
   ============================================================ */
(function () {
  'use strict';

  /* 构建期由 build_dashboard.py 注入：股票名称 → 6位代码 */
  var NAME2CODE = /*__RT_NAME2CODE__*/{}/**/;

  var UP = '#FF4D4F', DOWN = '#00C896';   /* A股惯例：红涨绿跌 */

  /* ---------------- 基础工具 ---------------- */
  function norm(s) { return (s || '').replace(/\s+/g, ''); }
  function txt(el) { return el ? norm(el.textContent || '') : ''; }
  function num(el) {
    if (!el) return NaN;
    var s = (el.textContent || '').replace(/[^\d.\-]/g, '');
    return s === '' ? NaN : parseFloat(s);
  }
  function extractCode(t) {
    var m = norm(t).match(/\d{6}/);
    return m ? m[0] : '';
  }
  function toSecid(c) {
    c = (c || '').toLowerCase().replace(/\s/g, '');
    var d = c.replace(/[^0-9]/g, '');
    if (d.length !== 6) return '';
    var p = c.slice(0, 2);
    if (p === 'sh' || d[0] === '6' || d[0] === '9') return '1.' + d;
    if (p === 'bj' || d[0] === '4' || d[0] === '8') return '0.' + d;
    return '0.' + d;
  }
  function fmtMoney(v) {
    var s = v >= 0 ? '+' : '-', a = Math.abs(v);
    if (a >= 10000) return s + (a / 10000).toFixed(2) + '万';
    return s + a.toFixed(0);
  }
  function isTrading() {
    var n = new Date(), d = n.getDay();
    if (d === 0 || d === 6) return false;
    var hm = n.getHours() * 60 + n.getMinutes();
    return (hm >= 570 && hm <= 690) || (hm >= 780 && hm <= 900);
  }

  /* ---------------- 表头列识别 ---------------- */
  /* 顺序敏感：精确列在前，宽泛的 name 规则放最后 */
  var RULES = [
    /* date 放在最前：命中即整表跳过（回测/交割单/推断节点等历史记录表，
       其"价格"是历史成交价而非现价，绝不能被实时行情覆盖）*/
    ['date',   /^(日期|推断日期|交易日期|成交日期|时间|日期时间)$/],
    ['code',   /^(代码|证券代码|股票代码|股票编号)$/],
    ['price',  /^(现价|最新价|价格|最新|收盘价|当前价)$/],
    ['pct',    /^(涨跌幅|涨幅|涨跌|当日涨跌|涨跌%|日涨跌|涨跌幅%)$/],
    ['cost',   /^(成本|成本价|持仓成本|均价|买入价|摊薄成本)$/],
    ['shares', /^(持股|持仓|持仓数量|股数|数量|持仓股数|持股数)$/],
    ['pnlPct', /^(盈亏%|收益率|盈亏比例|盈亏幅度|盈亏率|浮动盈亏%)$/],
    ['pnlAmt', /^(总盈亏|盈亏额|浮动盈亏|累计盈亏)$/],
    ['pnlDay', /^(当日盈亏|日盈亏|今日盈亏|当日盈亏额)$/],
    ['name',   /(名称|股票|标的|证券|个股)/]
  ];
  function detectCols(tb) {
    var ths = tb.querySelectorAll('th');
    if (!ths.length) return null;
    var cols = { date: -1, code: -1, price: -1, pct: -1, cost: -1, shares: -1, pnlPct: -1, pnlAmt: -1, pnlDay: -1, name: -1 };
    for (var i = 0; i < ths.length; i++) {
      var h = txt(ths[i]);
      if (!h) continue;
      for (var r = 0; r < RULES.length; r++) {
        if (cols[RULES[r][0]] < 0 && RULES[r][1].test(h)) { cols[RULES[r][0]] = i; break; }
      }
    }
    /* 历史记录表（含日期列）→ 直接跳过，防止覆盖历史成交价 */
    if (cols.date >= 0) return null;
    /* 既无现价列也无涨跌幅列 → 与行情无关，跳过 */
    if (cols.price < 0 && cols.pct < 0) return null;
    return cols;
  }

  /* ---------------- 扫描所有表格 ---------------- */
  var ROWS = {};          /* secid -> [{tr, cols}] */
  function scan() {
    ROWS = {};
    var tbs = document.querySelectorAll('table');
    for (var t = 0; t < tbs.length; t++) {
      var tb = tbs[t];
      if (tb.getAttribute('data-rt-skip') === '1') continue;
      var cols = detectCols(tb);
      if (!cols) continue;
      var trs = tb.querySelectorAll('tbody tr');
      for (var i = 0; i < trs.length; i++) {
        var tr = trs[i], tds = tr.children, code = '';
        if (cols.code >= 0 && tds[cols.code]) code = extractCode(txt(tds[cols.code]));
        if (!code && cols.name >= 0 && tds[cols.name]) {
          var raw = txt(tds[cols.name]);
          code = extractCode(raw);
          if (!code) {
            /* 纯名称（如持仓表"账号/股票"列）→ 查构建期映射 */
            for (var nm in NAME2CODE) {
              if (raw.indexOf(nm) >= 0) { code = String(NAME2CODE[nm]); break; }
            }
          }
        }
        if (!code) continue;
        var sid = toSecid(code);
        if (!sid) continue;
        tr.setAttribute('data-rt-secid', sid);
        (ROWS[sid] = ROWS[sid] || []).push({ tr: tr, cols: cols });
      }
    }
    return Object.keys(ROWS).length;
  }

  /* ---------------- 写单元格（带闪烁 + 涨跌配色） ---------------- */
  function setCell(td, val, up) {
    if (!td) return;
    var inner = td.querySelector('span,b,div');
    var target = (inner && inner.children.length === 0) ? inner : td;
    if (target.textContent !== val) {
      target.textContent = val;
      target.classList.remove('rt-up', 'rt-dn');
      void target.offsetWidth;
      target.classList.add(up ? 'rt-up' : 'rt-dn');
    }
    if (up === true || up === false) td.style.color = up ? UP : DOWN;
  }

  /* ---------------- 应用行情 ---------------- */
  function apply(d) {
    var diff = (d && d.data && d.data.diff) || [];
    for (var i = 0; i < diff.length; i++) {
      var it = diff[i];
      var sid = it.f13 + '.' + it.f12;
      var list = ROWS[sid];
      if (!list) continue;
      var price = (it.f2 === '-' || it.f2 == null) ? NaN : (it.f2 / 100);
      var pct = (it.f3 == null) ? NaN : (it.f3 / 100);
      var prev = (it.f18 === '-' || it.f18 == null) ? NaN : (it.f18 / 100);
      var isUp = !isNaN(pct) && pct >= 0;
      for (var j = 0; j < list.length; j++) {
        var o = list[j], c = o.cols, tds = o.tr.children;
        if (!isNaN(price) && c.price >= 0) setCell(tds[c.price], price.toFixed(2), isUp);
        if (!isNaN(pct) && c.pct >= 0 && c.pct !== c.price) {
          setCell(tds[c.pct], (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%', pct >= 0);
        }
        /* 持仓行：用实时价重算 盈亏% / 总盈亏 / 当日盈亏 */
        if (c.cost >= 0 && c.shares >= 0 && !isNaN(price)) {
          var cost = num(tds[c.cost]), shares = num(tds[c.shares]);
          if (cost > 0 && shares > 0) {
            var pp = (price - cost) / cost * 100;
            if (c.pnlPct >= 0) setCell(tds[c.pnlPct], (pp >= 0 ? '+' : '') + pp.toFixed(2) + '%', pp >= 0);
            var tot = (price - cost) * shares;
            if (c.pnlAmt >= 0) setCell(tds[c.pnlAmt], fmtMoney(tot), tot >= 0);
            if (c.pnlDay >= 0 && !isNaN(prev)) {
              var day = (price - prev) * shares;
              setCell(tds[c.pnlDay], fmtMoney(day), day >= 0);
            }
          }
        }
      }
    }
  }

  /* ---------------- 拉取行情（JSONP + 超时兜底） ---------------- */
  function emJsonp(secids, cb) {
    return new Promise(function (res) {
      var s = document.createElement('script'), timer = null, done = false;
      function cleanup() {
        try { delete window[cb]; } catch (e) { window[cb] = undefined; }
        if (s.parentNode) s.parentNode.removeChild(s);
      }
      function finish(v) { if (done) return; done = true; clearTimeout(timer); res(v); cleanup(); }
      window[cb] = function (d) { finish(d); };
      s.onerror = function () { finish(null); };
      s.src = 'https://push2.eastmoney.com/api/qt/ulist.np/get?secids=' + secids.join(',')
        + '&fields=f2,f3,f4,f12,f13,f14,f18&invt=2&ut=fa5fd1943c7b386f172d6893dbfba10b&cb=' + cb + '&_=' + Date.now();
      timer = setTimeout(function () { finish(null); }, 6000);
      document.body.appendChild(s);
    });
  }

  /* ---------------- 状态显示 ---------------- */
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function setStatus(ok, n) {
    var el = document.getElementById('rtStatus');
    if (!el) return;
    if (!ok) { el.className = 'live-badge off'; el.innerHTML = '<i class="dot"></i> 连接中…'; return; }
    var t = new Date(), ts = pad(t.getHours()) + ':' + pad(t.getMinutes()) + ':' + pad(t.getSeconds());
    el.className = 'live-badge';
    el.innerHTML = '<i class="dot"></i> 实时 ' + ts + (isTrading() ? ' · 交易中' : ' · 已休市')
      + (n ? ' · ' + n + '只' : '');
  }

  /* ---------------- 主循环 ---------------- */
  var TIMER = null, SCAN_AT = 0, LAST_N = 0;
  function tick(force) {
    var now = Date.now();
    if (force || now - SCAN_AT > 30000) { LAST_N = scan(); SCAN_AT = now; }
    var sids = Object.keys(ROWS);
    if (!sids.length) { setStatus(false, 0); return; }
    var batches = [], i;
    for (i = 0; i < sids.length; i += 50) batches.push(sids.slice(i, i + 50));
    var chain = Promise.resolve(), got = 0;
    batches.forEach(function (b) {
      chain = chain.then(function () {
        var cb = 'rtv3_' + Math.random().toString(36).slice(2, 10);
        return emJsonp(b, cb).then(function (d) { if (d && d.data) { apply(d); got++; } });
      });
    });
    chain.then(function () { setStatus(got > 0, sids.length); });
  }

  /* ---------------- 手动刷新（覆盖旧版同名函数） ---------------- */
  window.rtManualRefresh = function () {
    var b = document.getElementById('rtRefreshBtn');
    if (b) { b.disabled = true; b.classList.add('spinning'); }
    setStatus(false, 0);
    tick(true);
    setTimeout(function () { if (b) { b.disabled = false; b.classList.remove('spinning'); } }, 1500);
  };

  /* ---------------- 启动 ---------------- */
  function start() {
    /* 闪烁动画样式 */
    if (!document.getElementById('rtv3-style')) {
      var st = document.createElement('style');
      st.id = 'rtv3-style';
      st.textContent = '.rt-up{animation:rtFlashUp .9s ease-out;}'
        + '.rt-dn{animation:rtFlashDown .9s ease-out;}'
        + '@keyframes rtFlashUp{0%{background:rgba(255,77,79,.35)}100%{background:transparent}}'
        + '@keyframes rtFlashDown{0%{background:rgba(0,200,150,.35)}100%{background:transparent}}';
      document.head.appendChild(st);
    }
    tick(true);
    if (TIMER) clearInterval(TIMER);
    TIMER = setInterval(function () { tick(false); }, isTrading() ? 5000 : 30000);
    /* 每分钟校准频率，跨越开收盘时自动切换 */
    setInterval(function () {
      clearInterval(TIMER);
      TIMER = setInterval(function () { tick(false); }, isTrading() ? 5000 : 30000);
    }, 60000);
    /* 动态渲染的表格 → 变更后重新扫描 */
    if (window.MutationObserver) {
      var deb = null;
      new MutationObserver(function () {
        clearTimeout(deb);
        deb = setTimeout(function () { if (scan() !== LAST_N) { LAST_N = scan(); tick(false); } }, 900);
      }).observe(document.body, { childList: true, subtree: true });
    }
    /* 切回页面立即刷新 */
    document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(true); });
  }

  /* 覆盖旧版 startRealtime：本脚本位于 body 末尾，
     会在 DOMContentLoaded 之前执行完，因此页面里对 startRealtime() 的调用将命中新版。 */
  window.startRealtime = start;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
