#!/usr/bin/env node
/* ============================================================
   RT V3 实时引擎回归测试
   ------------------------------------------------------------
   用法：node scripts/test_rt_engine.js
   覆盖：
     1. 表头列识别（持仓/三券商/A股池/备选池/板块跳过/历史表跳过）
     2. 名称→代码解析（只有股票名没有代码列的行）
     3. 现价 / 盈亏% / 总盈亏 / 当日盈亏 重算正确性
     4. 红涨绿跌配色
     5. 历史记录表（回测交割单、推断节点）整表跳过保护
   ============================================================ */
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
const ENGINE = path.join(ROOT, 'scripts', 'rt_engine.js');
const PLACEHOLDER = '/*__RT_NAME2CODE__*/{}/**/';

/* 测试用映射（模拟 build 期注入） */
const N2C = {
  '通富微电': '002156', '北京君正': 'sz300223', '国瓷材料': '300285',
  '征和工业': '003033', '风华高科': '000636', '北大荒': '600598'
};

let src = fs.readFileSync(ENGINE, 'utf8');
if (!src.includes(PLACEHOLDER)) {
  console.error('FAIL: rt_engine.js 缺少占位符 ' + PLACEHOLDER);
  process.exit(1);
}
src = src.replace(PLACEHOLDER, JSON.stringify(N2C));

function grab(re, name) {
  const m = src.match(re);
  if (!m) { console.error('FAIL 提取失败: ' + name); process.exit(1); }
  return m[0];
}

const parts = [
  grab(/function norm\(s\) \{[^\n]*\}/, 'norm'),
  grab(/function txt\(el\) \{[^\n]*\}/, 'txt'),
  grab(/function num\(el\) \{[\s\S]*?\n  \}/, 'num'),
  grab(/function extractCode\(t\) \{[\s\S]*?\n  \}/, 'extractCode'),
  grab(/function toSecid\(c\) \{[\s\S]*?\n  \}/, 'toSecid'),
  grab(/function fmtMoney\(v\) \{[\s\S]*?\n  \}/, 'fmtMoney'),
  grab(/var UP = [^\n]*/, 'UP/DOWN'),
  grab(/var RULES = \[[\s\S]*?\];/, 'RULES'),
  grab(/function detectCols\(tb\) \{[\s\S]*?\n  \}/, 'detectCols'),
  grab(/function setCell\(td, val, up\) \{[\s\S]*?\n  \}/, 'setCell'),
  grab(/function scan\(\) \{[\s\S]*?\n  \}/, 'scan'),
  grab(/function apply\(d\) \{[\s\S]*?\n  \}/, 'apply')
];

/* ---------- mock DOM ---------- */
let ALL_TABLES = [];
function cell(text) {
  return {
    textContent: text, style: {}, offsetWidth: 0,
    classList: { add() {}, remove() {} },
    querySelector() { return null; }
  };
}
function row(cells) {
  return {
    children: cells.map(cell), attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; }
  };
}
function table(headers, rows) {
  return {
    getAttribute() { return null; },
    querySelectorAll(sel) {
      if (sel === 'th') return headers.map(h => ({ textContent: h }));
      if (sel === 'tbody tr') return rows;
      return [];
    }
  };
}
global.document = {
  querySelectorAll(sel) { return sel === 'table' ? ALL_TABLES : []; }
};

let ROWS = {};
/* 单次 eval，保证函数声明落在同一作用域 */
eval('var NAME2CODE = ' + JSON.stringify(N2C) + ';\n' + parts.join('\n'));

let pass = 0, fail = 0;
function check(name, cond, extra) {
  console.log('  ' + (cond ? '[PASS] ' : '[FAIL] ') + name + (extra ? '  << ' + extra : ''));
  cond ? pass++ : fail++;
}
function expectCols(name, hdrs, want) {
  const c = detectCols(table(hdrs, []));
  let ok = true, diff = [];
  for (const k in want) {
    const got = c ? c[k] : -1;
    if (got !== want[k]) { ok = false; diff.push(k + ' 期望' + want[k] + ' 实得' + got); }
  }
  check(name, ok, diff.join(', '));
}

/* ============ 1. 表头列识别 ============ */
console.log('\n[1] 表头列识别');
const H = {
  pos: ['账号/股票', '持仓', '成本', '现价', '盈亏%', '总盈亏', '当日盈亏', 'RSI', 'MACD', '量比', '换手', '主力', '操作', '明日策略 / 逻辑'],
  broker: ['券商', '股票', '代码', '持股', '成本', '现价', '当日涨跌', '盈亏额', '收益率', '策略'],
  astock: ['代码', '名称', '现价', '涨幅', '量比', '换手%', '所属行业', '成交额', '市盈(动)', '流通市值'],
  picks: ['名称/代码', '现价', '涨跌幅', '评分', '明日预测', '板块', '策略'],
  sector: ['#', '板块', '今日涨幅', '主力净额', '涨停', '涨/跌家', '领涨龙头', '5日涨幅'],
  backtest: ['日期', '方向', '价格', '数量', '盈亏%'],
  infer: ['阶段', '推断日期', '对应价格', '说明']
};
expectCols('持仓复盘表', H.pos, { name: 0, shares: 1, cost: 2, price: 3, pnlPct: 4, pnlAmt: 5, pnlDay: 6 });
expectCols('三券商持仓表', H.broker, { name: 1, code: 2, shares: 3, cost: 4, price: 5, pct: 6, pnlAmt: 7, pnlPct: 8 });
expectCols('A股池 astock', H.astock, { code: 0, name: 1, price: 2, pct: 3 });
expectCols('备选池 picks', H.picks, { name: 0, price: 1, pct: 2 });
expectCols('板块表应跳过', H.sector, { code: -1, price: -1 });
check('回测交割表整表跳过', detectCols(table(H.backtest, [])) === null);
check('推断节点表整表跳过', detectCols(table(H.infer, [])) === null);

/* ============ 2. 名称→代码解析 ============ */
console.log('\n[2] 名称→代码解析（持仓表无代码列）');
const bjjz = row(['北京君正', '1500', '138.48', '133.66', '-3.48%', '-7230', '0', '51.8']);
const tfwd = row(['通富微电', '700', '59.805', '61.24', '2.40%', '1004', '0', '44.2']);
ALL_TABLES = [table(H.pos, [bjjz, tfwd])];
ROWS = {};
const n = scan();
console.log('  扫描到 ' + n + ' 只：' + Object.keys(ROWS).join(', '));
check('扫描到 2 只证券', n === 2, '实得 ' + n);
check('北京君正 → 0.300223', Object.keys(ROWS).indexOf('0.300223') >= 0);
check('通富微电 → 0.002156', Object.keys(ROWS).indexOf('0.002156') >= 0);

/* ============ 3. 应用行情 + 重算 ============ */
console.log('\n[3] 应用实时行情并重算持仓盈亏');
/* 真实接口格式：f2=价格*100, f3=涨跌幅*100, f18=昨收*100 */
const payload = {
  data: {
    diff: [
      { f2: 13570, f3: -340, f4: -478, f12: '300223', f13: 0, f14: '北京君正', f18: 14048 },
      { f2: 6375, f3: 3, f4: 2, f12: '002156', f13: 0, f14: '通富微电', f18: 6373 }
    ]
  }
};
apply(payload);
const b = bjjz.children, t = tfwd.children;
console.log('  北京君正 → 现价 ' + b[3].textContent + ' | 盈亏% ' + b[4].textContent
  + ' | 总盈亏 ' + b[5].textContent + ' | 当日盈亏 ' + b[6].textContent);
console.log('  通富微电 → 现价 ' + t[3].textContent + ' | 盈亏% ' + t[4].textContent
  + ' | 总盈亏 ' + t[5].textContent + ' | 当日盈亏 ' + t[6].textContent);

check('北京君正 现价 133.66→135.70', b[3].textContent === '135.70', b[3].textContent);
check('通富微电 现价 61.24→63.75', t[3].textContent === '63.75', t[3].textContent);
check('北京君正 盈亏% 重算 -2.01%', b[4].textContent === '-2.01%', b[4].textContent);
check('通富微电 盈亏% 重算 +6.60%', t[4].textContent === '+6.60%', t[4].textContent);
check('北京君正 总盈亏 重算 -4170', b[5].textContent === '-4170', b[5].textContent);
check('通富微电 总盈亏 重算 +2762', t[5].textContent === '+2762', t[5].textContent);
check('北京君正 当日盈亏 重算 -7170', b[6].textContent === '-7170', b[6].textContent);

/* ============ 4. 配色（红涨绿跌） ============ */
console.log('\n[4] A股配色（红涨绿跌）');
check('通富微电(涨) 标红 #FF4D4F', t[3].style.color === '#FF4D4F', t[3].style.color);
check('北京君正(跌) 标绿 #00C896', b[3].style.color === '#00C896', b[3].style.color);

/* ============ 5. 历史表保护 ============ */
console.log('\n[5] 历史记录表保护（不得被实时价覆盖）');
ALL_TABLES = [table(H.backtest, [row(['2026-08-20', '买入', '61.24', '700', '2.4%'])])];
ROWS = {};
check('回测交割表扫描结果为空', scan() === 0);
ALL_TABLES = [table(H.infer, [row(['阶段一', '2026-08-20', '61.24', '建仓'])])];
ROWS = {};
check('推断节点表扫描结果为空', scan() === 0);

console.log('\n' + '='.repeat(46));
console.log('结果: ' + pass + ' 通过 / ' + fail + ' 失败');
console.log('='.repeat(46));
process.exit(fail ? 1 : 0);
