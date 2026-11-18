/* 下载器流量统计 - 前端主逻辑
 *
 * 认证 / 双主题 / 控件状态持久化 / 历史数据清单 / 下载器卡片开关 /
 * 时间范围单选下拉 / 横向拖动平移 / 折线与堆叠柱 / 设置多页面 / 采集参数 /
 * 曲线颜色 HSV+RGB 双模式调色板 / SSE 增量刷新与轮询降级。
 *
 * 所有展示状态（所选下载器、两张图的时间范围 / 方向 / 拖动位置）记在
 * localStorage，下次打开与上次退出时完全一致。
 */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

// 新增「昨日 / 上周 / 上月」，分别紧跟「今日 / 本周 / 本月」之后（与
// sqing33/PTNexus 的速率图范围顺序一致）。内部 key 用 yesterday / lastweek /
// lastmonth；24h 是历史内部 key，界面文案一直为「今日」。
// 末尾新增「全部」，展示项目数据库中所有已采集的数据。
const RANGE_ORDER = ['live', '1h', '6h', '12h', '24h', 'yesterday',
  'week', 'lastweek', 'month', 'lastmonth', 'year', 'all'];
/* 流量统计卡片删除「实时」单选项（实时窗口只属于实时速率卡片）。
 速率卡片仍保留全部 12 档；历史 localStorage 里若存的是 live，加载时按
 rangeOrder 校验失败自动回落到默认的「今日」。 */
const TRAFFIC_RANGE_ORDER = RANGE_ORDER.filter((k) => k !== 'live');
function rangeOrder(which) { return which === 'traffic' ? TRAFFIC_RANGE_ORDER : RANGE_ORDER; }
const RANGE_LABELS = {
  live: '实时', '1h': '1小时', '6h': '6小时', '12h': '12小时',
  '24h': '今日', yesterday: '昨日', week: '本周', lastweek: '上周',
  month: '本月', lastmonth: '上月', year: '本年', all: '全部',
};
// 自然周期里「按完整日 / 月分桶」的范围，流量图弹出菜单标题保持日期标签；
// 补上上周 / 上月。今日 / 昨日按小时桶，与实时 / 1 / 6 / 12 小时一样
// 显示时间段标题，所以不在此列。
const NATURAL_RANGES = ['week', 'lastweek', 'month', 'lastmonth', 'year', 'all'];
const LIVE_SHORT = { 30: '30秒', 60: '1分', 180: '3分', 300: '5分', 600: '10分', 1800: '30分' };
// 顶部 4 张汇总卡片：标题固定为当前周期，右上角下拉展示「历史数据」清单
// （触发文案改「历史数据」、菜单统一加宽不重叠、手机端不越屏；
// 起纯展示清单、不再单选改卡片，可无限下滑加载更早周期）。
const PERIOD_UNITS = [
  { unit: 'day', title: '今日' },
  { unit: 'week', title: '本周' },
  { unit: 'month', title: '本月' },
  { unit: 'year', title: '本年' },
];

const S = {
  token: localStorage.getItem('ttm_token') || '',
  theme: localStorage.getItem('ttm_theme') || 'dark',
  // /api/auth/status 不再回显登录用户名，用户名只在登录 / 改密成功后
  // 由响应里取并存本地，避免未鉴权接口泄露用户名。
  user: localStorage.getItem('ttm_user') || '', mustChange: false,
  logged: false, installReady: false,
  tz: 8, overview: null, downloaders: [], settings: null, statusLine: '',
  settingsPage: 'downloaders',
  // 下载器选择是全局状态：两张图表共用，由上方卡片单击切换
  pick: new Set(['all']),
  periods: null,                                  // /api/periods 返回的卡片当前周期数据
  // 实时速率(pi) / 流量统计(ti) / 实时窗口(ls) 三份独立草稿，默认值与后端一致
  collectDraft: { pi: 5, ti: 60, ls: 300 },
  rate: { range: 'live', dirs: new Set(['up', 'down']), data: null, view: null, _hover: null,
    offset: 0, maxOffset: 0, windowLabel: '', _seq: 0, _panning: false },
  traffic: { range: '24h', dirs: new Set(['up', 'down']), data: null, view: null, _hover: null,
    offset: 0, maxOffset: 0, windowLabel: '', _seq: 0, _panning: false },
};
let timers = [];

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function pad(n) { return String(n).padStart(2, '0'); }
/* 图例按行分组：第一行放「总数除以每行个数的余数」项并居中，之后每行恰好
 perRow 个。起 perRow 由 renderLegend 按容器宽度与固定字号下的各项
 自然宽度自适应算出（不再写死 3），各行独立成 flex 行、整体居中，最后一行
 一定填满，留空部分留在第一行。 */
function legendRows(items, perRow) {
  const n = items.length, rem = n % perRow, rows = [];
  let i = 0;
  if (rem) {
    rows.push('<div class="lg-row lg-first">' + items.slice(0, rem).join('') + '</div>');
    i = rem;
  }
  for (; i < n; i += perRow) {
    rows.push('<div class="lg-row">' + items.slice(i, i + perRow).join('') + '</div>');
  }
  return rows.join('');
}
/* 两张图例统一排版。
 1) 字号固定＝坐标轴刻度字号（charts.js 的 prep：画布 <480px 为 10px，
 否则 11px），由 renderLegend 动态设置，绝不因为文字长就缩小字号；
 2) 先把所有项平铺，在固定字号下量出各项自然宽度，按容器宽度算出「每行
 能放几个」（cols），屏幕宽度不够就直接换行，不再强制一行 3 个；
 3) 再交给 legendRows 分组：第一行放余数项并居中（留空在第一行），
 其余行填满，各行独立居中，整体居中对齐；
 4) 各项按内容自然宽度、无 max-width，任何情况都不裁剪 / 不打省略号。 */
function renderLegend(host, items, chartSel) {
  if (!host || !items.length) return;
  const cv = chartSel ? $(chartSel) : null;
  const compact = !!(cv && cv.getBoundingClientRect().width < 480);
  host.style.fontSize = (compact ? 10 : 11) + 'px';
  // 平铺测量：此时没有 .lg-row 宽度约束，量到的就是固定字号下的自然宽度
  host.innerHTML = items.join('');
  /* 图例中两个下载器之间的间距再加宽「2 个中文字符字号」的宽度。
 图例字号＝坐标轴刻度字号（桌面 11px / 手机 10px），2 个中文字符 ≈ 22px，
 在原 8px 基础上加到 30px。间距统一由 CSS 变量 --lg-gap 定义（.legend），
 这里直接读计算后的值，保证与 CSS 严格一致 —— 否则列数按旧 gap 算、实际
 按新 gap 排，窄屏会换行错乱。桌面 / 手机端由同一变量同步生效。 */
  const gap = parseFloat(getComputedStyle(host).getPropertyValue('--lg-gap')) || 8;
  const W = host.getBoundingClientRect().width ||
            (host.parentElement ? host.parentElement.getBoundingClientRect().width : 0);
  let maxW = 1;
  host.querySelectorAll('.lg-item').forEach((it) => {
    maxW = Math.max(maxW, it.getBoundingClientRect().width);
  });
  const cols = Math.max(1, Math.min(items.length,
    Math.floor((W + gap) / (maxW + gap)) || 1));
  host.innerHTML = legendRows(items, cols);
  fitLegend(host);
}
/* 不再缩字号 —— 字号始终由 renderLegend 固定为坐标轴刻度字号。
 只做「极端单项比整行还宽」的兜底：宁可换行也绝不裁剪 / 打省略号，
 保证图例内容 100% 完整。正常名称不会走到这个分支。 */
function fitLegend(host) {
  if (!host || host.hidden) return;
  const W = host.getBoundingClientRect().width;
  host.querySelectorAll('.lg-item').forEach((it) => {
    const names = () => Array.from(it.querySelectorAll('.lg-nm,.lg-name'));
    it.style.fontSize = '';
    it.style.whiteSpace = '';
    it.style.overflowWrap = '';
    names().forEach((n) => {
      n.style.whiteSpace = ''; n.style.overflowWrap = '';
    });
    if (W && it.getBoundingClientRect().width > W + 1) {
      it.style.whiteSpace = 'normal';
      it.style.overflowWrap = 'anywhere';
      names().forEach((n) => {
        n.style.whiteSpace = 'normal';
        n.style.overflowWrap = 'anywhere';
      });
    }
  });
}
function localDate(ts) { return new Date((Number(ts) + S.tz * 3600) * 1000); }
function fmtClock(ts) {
  const d = localDate(ts);
  return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
}
/* 一个「时间点」其实是一个采样桶 / 小时桶，短窗口范围的弹出菜单标题
 要显示它覆盖的时间段（如 11-07 14:00 ~ 15:00），而不是一个瞬时点。
 桶宽不足 1 分钟时补上秒，跨天时右端也带上日期。 */
function fmtSpanTitle(a, b) {
  const d1 = localDate(a), d2 = localDate(b);
  const day = (d) => pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  const withSec = (b - a) < 60;
  const hm = (d) => pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) +
    (withSec ? ':' + pad(d.getUTCSeconds()) : '');
  const a1 = day(d1), b1 = day(d2);
  return a1 === b1 ? `${a1} ${hm(d1)} ~ ${hm(d2)}`
                   : `${a1} ${hm(d1)} ~ ${b1} ${hm(d2)}`;
}
/* 把「一段时间桶」[a, b) 取中间时刻 (a+b)/2 格式化成横坐标刻度
 文字。流量统计的每组上传/下载柱覆盖一整个时间段，而刻度按柱组中心定位、
 落在柱子正下方居中，因此文字也应是这段时间的「中间时刻」，而不是桶起点。
 中间时刻落在整分钟时输出 HH:MM；桶宽使中点带半分 / 秒（如 5 分钟桶中点
 x:02:30）时补秒输出 HH:MM:SS，保证文字就是真实中点、不被抹成 x:02。
 时区换算与 fmtClock / fmtSpanTitle 完全一致。 */
function fmtSpanMid(sp) {
  const mid = (Number(sp[0]) + Number(sp[1])) / 2;
  const d = localDate(mid);
  const hm = pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
  return (mid % 60 === 0) ? hm : hm + ':' + pad(d.getUTCSeconds());
}
/* 所有「换算后有小数位」的展示数值统一四舍五入保留两位小数。
 旧版按数值大小混用 toFixed(0)/toFixed(1)/toFixed(2)，大数值被抹成整数，
 小数位数不统一；现在一律 2 位。整数 B 本身没有小数位，仍按整数显示；
 计数类（种子数等）不走这里，保持整数。 */
function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return Math.round(n) + ' B';
  const u = ['KB', 'MB', 'GB', 'TB', 'PB'];
  let v = n, i = -1;
  do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1);
  return v.toFixed(2) + ' ' + u[i];
}
function fmtRate(n) { return fmtBytes(n) + '/s'; }
/* 3 列窄卡里两个速率要并排，用紧凑单位（↑3.44M / ↓664.00K）避免被省略；
 完整值放在 title 里，桌面悬停 / 长按可看。紧凑值同样保留两位小数。 */
function fmtRateCompact(n) {
  const s = fmtBytes(n);
  const m = /^([\d.]+)\s*(B|KB|MB|GB|TB|PB)$/.exec(s);
  if (!m) return s;
  return m[1] + (m[2] === 'B' ? 'B' : m[2][0]);
}
/* 手机端「流量统计」图例用紧凑字节值（44.53 GB → 44.53G），去掉单位
 全称与空格以省宽度；完整值仍留在 .v-full（桌面端）与 title（长按 / 悬停）里。
 与全局规则一致，紧凑值也保留两位小数、不再取整（旧版 44.5 GB → 45G）。 */
function fmtBytesShort(n) {
  // 与速率紧凑值完全同一规则，只把单位全称压成首字母
  return fmtRateCompact(n);
}
function adapt(hex) { return TTMCharts.adapt(hex, S.theme); }
function summaryColor(dir) {
  const c = S.settings && S.settings.summary_colors;
  return adapt(dir === 'up' ? ((c && c.up) || '#fb923c') : ((c && c.down) || '#38bdf8'));
}

/* ---------------- 展示状态持久化（需求：下次进入与上次退出一致） ---------------- */
function loadState() {
  try {
    const p = JSON.parse(localStorage.getItem('ttm_pick'));
    if (Array.isArray(p)) {
      S.pick = new Set(p.filter((v) => v === 'all' || /^\d+$/.test(String(v))));
    }
  } catch (e) { /* 损坏的值忽略，用默认 */ }
  // 历史周期清单不再记忆选中项（已无单选改卡片功能），故无 ttm_period 状态
  ['rate', 'traffic'].forEach((w) => {
    const r = localStorage.getItem('ttm_' + w + '_range');
    if (r && rangeOrder(w).indexOf(r) >= 0) S[w].range = r;
    const o = Number(localStorage.getItem('ttm_' + w + '_offset'));
    if (Number.isFinite(o) && o > 0) S[w].offset = Math.floor(o);
    try {
      const d = JSON.parse(localStorage.getItem('ttm_' + w + '_dirs'));
      if (Array.isArray(d) && d.length) {
        S[w].dirs = new Set(d.filter((x) => x === 'up' || x === 'down'));
      }
    } catch (e) { /* 忽略 */ }
  });
}
function saveState() {
  try {
    localStorage.setItem('ttm_pick', JSON.stringify(Array.from(S.pick)));
    ['rate', 'traffic'].forEach((w) => {
      localStorage.setItem('ttm_' + w + '_range', S[w].range);
      localStorage.setItem('ttm_' + w + '_dirs', JSON.stringify(Array.from(S[w].dirs)));
      localStorage.setItem('ttm_' + w + '_offset', String(S[w].offset || 0));
    });
  } catch (e) { /* 隐私模式下 localStorage 可能不可写 */ }
}

/* ---------------- HTTP ---------------- */
function jsonBody(method, data) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) };
}
async function api(path, opts) {
  const o = Object.assign({}, opts || {});
  o.headers = Object.assign({}, (opts && opts.headers) || {});
  if (S.token) o.headers['Authorization'] = 'Bearer ' + S.token;
  let r;
  try { r = await fetch(path, o); }
  catch (e) { throw Object.assign(new Error('网络不可用：' + e.message), { network: true }); }
  let j;
  try { j = await r.json(); }
  catch (e) { throw new Error('HTTP ' + r.status + '，返回不是 JSON'); }
  if (r.status === 401 && j.code === 'auth_required') onAuthLost(j.error);
  if (!r.ok || j.ok === false) {
    throw Object.assign(new Error(j.error || ('HTTP ' + r.status)),
      { code: j.code, status: r.status });
  }
  return j;
}

/* ---------------- SSE 推流 ----------------
 服务端 /api/stream 在采集完成时推一次增量通知（EventBus 已按 1 秒节流，
 0.1 秒高频档位不会把前端压垮）。前端收到事件后只做局部刷新：
 rate 事件 -> 总览（顶部状态 / 下载器卡片）+ live 档速率图
 traffic 事件 -> 流量统计图 + 顶部周期卡片
 SSE 健康时关掉 1 秒 / 30 秒盲轮询，断线或 90 秒无事件自动降级回轮询，
 5 秒兜底定时器始终保留（非 live 档速率图与总览的低频保底）。
 用 fetch + ReadableStream 而非 EventSource：后者不能带 Authorization 头，
 只能把 token 塞进 URL，反而多一个泄露面。 */
let streamAbort = null, streamTimer = null, streamOk = false, lastStreamAt = 0;

function parseSSEFrame(frame) {
  let name = 'message', data = '';
  frame.split('\n').forEach((line) => {
    if (line.indexOf('event:') === 0) name = line.slice(6).trim();
    else if (line.indexOf('data:') === 0) data += line.slice(5).trim();
  });
  if (!data) return null;                       // 注释帧 / keep-alive
  try { return { name, data: JSON.parse(data) }; } catch (e) { return null; }
}
function stopStream() {
  if (streamTimer) { clearTimeout(streamTimer); streamTimer = null; }
  if (streamAbort) { try { streamAbort.abort(); } catch (e) { /* 忽略 */ } streamAbort = null; }
  streamOk = false;
}
async function startStream() {
  stopStream();
  if (!S.logged || !S.token) return;
  const ac = new AbortController();
  streamAbort = ac;
  try {
    const res = await fetch('/api/stream', {
      headers: { 'Authorization': 'Bearer ' + S.token },
      cache: 'no-store', signal: ac.signal,
    });
    if (!res.ok || !res.body) throw new Error('SSE 不可用');
    streamOk = true; lastStreamAt = Date.now();
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buf += dec.decode(chunk.value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = parseSSEFrame(frame);
        if (ev) onStreamEvent(ev);
      }
    }
  } catch (e) {
    if (ac.signal.aborted) return;              // 主动退出，不重连
  } finally {
    streamOk = false;
    if (!ac.signal.aborted) streamTimer = setTimeout(startStream, 3000);
  }
}
function onStreamEvent(ev) {
  if (!S.logged || document.hidden) return;
  lastStreamAt = Date.now();
  if (ev.name === 'rate') {
    loadOverview();                             // 局部更新：顶部状态 / 卡片速率
    if (S.rate.range === 'live') loadChart('rate', true);
  } else if (ev.name === 'traffic') {
    loadChart('traffic'); loadPeriods();
  }
}

function setHealth(ok, text) {
  const el = $('#healthPill');
  // 胶囊文字独立包在 .pill-txt 里（按字形边界垂直居中）；起图标已移除，
  // 仍沿用按字形居中的方案。更新文案时只改这一层；兼容旧版缓存 HTML
  //（无 .pill-txt）时退回整块 textContent。
  // 不再拼接「● 」状态圆点前缀，只显示文字本体（纯文字胶囊）。
  const t = el.querySelector('.pill-txt');
  if (t) t.textContent = text;
  else el.textContent = text;
  el.classList.toggle('bad', !ok);
}
function setOffline(v) { $('#offlineBar').hidden = !v; }
function showTip(e, html) {
  const t = $('#tooltip');
  t.innerHTML = html; t.hidden = false;
  const x = Math.min(e.clientX + 14, window.innerWidth - t.offsetWidth - 10);
  const y = Math.max(8, e.clientY - t.offsetHeight - 12);
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
function hideTip() { $('#tooltip').hidden = true; }

/* ---------------- 主题 ---------------- */
function applyTheme() {
  document.documentElement.dataset.theme = S.theme;
  localStorage.setItem('ttm_theme', S.theme);
  const meta = $('#metaTheme');
  if (meta) meta.content = S.theme === 'light' ? '#f2f5fa' : '#0a1120';
  const label = S.theme === 'light' ? '◐ 深色' : '◐ 浅色';
  if ($('#btnAuthTheme')) $('#btnAuthTheme').textContent = label;
  if ($('#btnThemeDark')) {
    $('#btnThemeDark').classList.toggle('active', S.theme === 'dark');
    $('#btnThemeLight').classList.toggle('active', S.theme === 'light');
  }
}
function refreshChartTheme() {
  if (!S.logged) return;
  renderChart('rate'); renderChart('traffic');
  ['rate', 'traffic'].forEach((w) => { renderRangeDropdown(w); renderDropdown(w); });
}
function setTheme(t) { if (S.theme !== t) { S.theme = t; applyTheme(); refreshChartTheme(); } }
function toggleTheme() { setTheme(S.theme === 'dark' ? 'light' : 'dark'); }

/* ---------------- 认证视图 ---------------- */
function clearTimers() { timers.forEach(clearInterval); timers = []; }
function showLogin(msg) {
  S.logged = false; clearTimers(); stopStream();
  $('#app').hidden = true; $('#authLayer').hidden = false;
  $('#loginForm').hidden = false; $('#setupForm').hidden = true;
  $('#loginMsg').textContent = msg || '';
  $('#loginPass').value = '';
}
function showSetup() {
  S.logged = false; clearTimers(); stopStream();
  $('#app').hidden = true; $('#authLayer').hidden = false;
  $('#loginForm').hidden = true; $('#setupForm').hidden = false;
  $('#setupMsg').textContent = '';
  $('#setupPass').value = ''; $('#setupPass2').value = '';
}
function onAuthLost(msg) {
  S.token = ''; S.logged = false; S.mustChange = false;
  localStorage.removeItem('ttm_token'); localStorage.removeItem('ttm_user');
  clearTimers(); stopStream();
  showLogin(msg || '登录已失效，请重新登录');
}
function enterApp() {
  $('#authLayer').hidden = true; $('#app').hidden = false;
  S.logged = true; S.mustChange = false;
  clearTimers(); stopStream();
  loadAll();
  /* 刷新节奏由「三路固定间隔盲轮询」改为「SSE 事件驱动 + 轮询降级」。
 - 服务端采集完成即推事件（每种 kind 最多 1 次/秒），前端只做局部刷新；
 低频档位不必等下一次轮询，高频档位也不会被 10 次/秒的刷新压垮。
 - SSE 健康时关掉 1 秒 live 档盲轮询与 30 秒流量轮询；
 - 5 秒兜底定时器始终保留：非 live 档速率图 + 总览，兼作 SSE 看门狗
 （90 秒无任何事件则判定推流失效、恢复轮询并重连）。
 - SSE 断线 / 被禁用 / 浏览器不支持流时，三路定时器照常运行，功能零降级。
 的数据签名节流、帧平移动画、页面隐藏暂停轮询全部保留。 */
  timers.push(setInterval(() => {
    if (!S.logged || document.hidden) return;
    if (streamOk && Date.now() - lastStreamAt > 90000) {
      streamOk = false; startStream();            // 看门狗：恢复轮询 + 重连
    }
    loadOverview();
    if (S.rate.range !== 'live') loadChart('rate');
  }, 5000));
  timers.push(setInterval(() => {
    if (!S.logged || document.hidden) return;
    if (streamOk) return;                          // 由 rate 事件驱动
    if (S.rate.range === 'live') loadChart('rate', true);
  }, 1000));
  timers.push(setInterval(() => {
    if (!S.logged || document.hidden) return;
    if (streamOk) return;                          // 由 traffic 事件驱动
    loadPeriods(); loadChart('traffic');
  }, 30000));
  startStream();
}
async function logout() {
  try { await api('/api/auth/logout', jsonBody('POST', {})); } catch (e) { /* 忽略 */ }
  S.token = ''; localStorage.removeItem('ttm_token'); localStorage.removeItem('ttm_user');
  stopStream();
  $('#settingsModal').hidden = true;
  showLogin('已退出登录');
}
async function boot() {
  applyTheme(); loadState(); bindEvents(); initPWA(); installFitWatchers();
  ['rate', 'traffic'].forEach((w) => { renderRangeDropdown(w); renderDropdown(w); });
  renderSummary();
  try {
    const st = await api('/api/auth/status');
    if (st.authenticated) {
      S.mustChange = st.must_change;      // 用户名取本地存储，不再由 status 下发
      if (st.must_change) showSetup(); else enterApp();
    } else {
      if (S.token) { S.token = ''; localStorage.removeItem('ttm_token'); }
      showLogin();
    }
  } catch (e) {
    // 离线且本地有会话：仍展示界面外壳，数据区显示离线提示
    if (S.token) { $('#authLayer').hidden = true; $('#app').hidden = false; S.logged = true; setOffline(true); loadAll(); }
    else showLogin('无法连接服务：' + e.message);
  }
}

/* ---------------- 数据加载 ---------------- */
function handleLoadError(e) {
  if (e.code === 'auth_required' || e.code === 'setup_required') return;
  if (e.network) { setOffline(true); setHealth(false, '连接中断'); }
  else setHealth(false, e.message);
}
async function loadOverview() {
  try {
    S.overview = await api('/api/overview');
    S.tz = S.overview.tz_offset || 8;
    setOffline(false);
    renderStatus(); syncPicks();
    if (!$('#settingsModal').hidden && S.settingsPage === 'about') renderAbout();
  } catch (e) { handleLoadError(e); }
}
async function loadPeriods() {
  try { S.periods = (await api('/api/periods')).periods; renderSummary(); }
  catch (e) { if (e.code !== 'auth_required') console.warn(e); }
}
async function loadDownloaders() {
  try { S.downloaders = (await api('/api/downloaders')).items; renderConfigTable(); }
  catch (e) { console.warn(e); }
}
async function loadSettings() {
  try {
    S.settings = await api('/api/settings');
    // 范围下拉里的「实时」标签要跟着设置里的窗口变化
    ['rate', 'traffic'].forEach(renderRangeDropdown);
  } catch (e) { /* 用默认值 */ }
}
/* 拖动松手后由这里一次性归位画布（与重绘在同一帧提交，避免中间态闪跳）。 */
function clearPanTransform(which) {
  const cv = which === 'rate' ? $('#rateChart') : $('#trafficChart');
  cv.style.transition = '';
  cv.style.transform = '';
}
async function loadChart(which, periodic) {
  const st = S[which];
  if (st._panning) return;               // 拖动中不发请求，避免打断即时平移画面
  const seq = ++st._seq;                 // 只接受最后一次请求的响应
  try {
    const data = await api('/api/chart?range=' + encodeURIComponent(st.range) +
      '&metric=' + (which === 'rate' ? 'rate' : 'traffic') +
      '&offset=' + (st.offset || 0));
    if (seq !== st._seq) return;
    /* （彻底修复长实时范围右端重绘）：live 档周期刷新的签名只认
 「窗口 times[0] 是否推进」。后端 live 桶宽 step 是采样间隔整数倍，窗口
 每 step 秒才推进一桶；前端 1 秒刷新里绝大多数请求窗口没动、只是尾部桶
 AVG 随新采样被重算。签名带「各系列末尾值」，尾桶 AVG 每秒变
 ⇒ 签名每秒变 ⇒ renderChart 每秒调用 ⇒ paintLines 每秒 clearRect 清空整张
 画布再全量重画，右端最新点每秒被擦掉重画一次；长窗口（step 大）窗口推进
 很慢，观感就是「曲线左移后右端停顿、又被重绘一遍，尾端像在被反复修改」。
 只取消了补间动画（改直接画终态），没拦住「每秒全量重画」，故问题依旧。
 参照 PT Nexus v4.0.2「数据/窗口未变化不 setOption」：live 档以 times[0]
 为窗口推进标志，窗口未推进就**完全不重绘**（连 clearRect 都不做），仅在
 窗口真正推进时画一次并走 shift 帧平移。非 live 档沿用原签名（含末尾值），
 数据有变照常刷新；切范围/增删下载器/拖动等非周期刷新 periodic=false，
 不受签名节流影响，一律重画。 */
    const livePeriodic = periodic === true && st.range === 'live';
    /* rate 末点已改对齐 window.end（= 当前时刻，每次请求都变），若继续
 用 times[-1] 当非 live 档签名首项会导致每次 SSE 推送都全量重绘。统一
 改用 times[0] 作「窗口推进标志」（与 live 档一致），数据是否变化仍由
 末尾值判定，语义不变、避免无谓重绘。 */
    const sig = JSON.stringify(livePeriodic
      ? [data.times && data.times[0], data.labels && data.labels.length,
         (data.series || []).map((x) => x.id)]
      : [data.times && data.times[0],
         data.labels && data.labels.length,
         (data.series || []).map((x) => [x.id,
           x.up && x.up[x.up.length - 1], x.down && x.down[x.down.length - 1]])]);
    st.data = data;
    st.maxOffset = Number(data.max_offset) || 0;
    st.offset = Number(data.offset) || 0;   // 后端会把超出上限的值 clamp 回来
    st.windowLabel = (data.window && data.window.label) || '';
    if (periodic && st._sig === sig && st._painted) {
      renderLatestBtn(which);              // 数据没变：不重绘、不动画
      return;
    }
    const changed = st._sig !== sig;
    st._sig = sig; st._painted = true;
    st._hover = null;
    clearPanTransform(which);
    // 仅「实时档周期刷新且数据确有变化」触发 300ms 补间动画
    renderChart(which, periodic === true && which === 'rate' && changed);
    renderLatestBtn(which);
  } catch (e) {
    clearPanTransform(which);
    if (e.code !== 'auth_required') console.warn(e);
  }
}
/* 时间区间文字改为「一直显示」，放在标题行最右侧，随 loadChart 刷新；
 「回到最新」按钮移到文字左侧，仍只在拖到历史窗口（offset>0）时出现，
 当前显示范围是最新时隐藏。 */
function renderLatestBtn(which) {
  const off = (S[which].offset || 0) > 0;
  $('#' + which + 'Latest').hidden = !off;
  const rng = $('#' + which + 'PanRange');
  if (rng) rng.textContent = S[which].windowLabel || '';
}
async function loadAll() {
  await Promise.all([loadSettings(), loadOverview(), loadDownloaders(), loadPeriods(),
    loadChart('rate'), loadChart('traffic')]);
  /* 数据 / 图例 / 下载器卡片全部渲染完成后，按浏览器真实可用高度
 window.innerHeight 分配两个绘图区高度（首屏即无纵向滚动条）。 */
  scheduleFit();
}

/* ---------------- 顶部 4 张汇总卡片 ----------------
 卡片恒显示「当前时间周期」的上传/下载合计；右上角是纯展示的「历史数据」
 清单下拉：每行 = 周期名称 + ↑↓数据(与卡片同格式) + 该周期时间，首屏固定
 10 行、可无限下滑加载更早周期，每次重新展开都回到最近周期。把触发
 文案从「历史周期」改为「历史数据」并统一加宽菜单；单选改卡片的功能及相关
 状态 / 代码自 起已全部移除。
 排版改为「以中轴线分左右两半、各半两端对齐」：
 左半 = 周期名称(最左) … ↑上传数据(最右，单位 B 为左半结尾字符)；
 右半 = ↓下载数据(最左，箭头为右半开头字符) … 周期时间(最右)。
 两半之间只有 CSS column-gap 的一点点留白，展示要素仍是四项、不新增。 */
function histRowHTML(x) {
  return `<div class="hist-row">` +
    `<span class="hr-half">` +
      `<span class="hr-name">${esc(x.label)}</span>` +
      `<span class="v up" title="上传 ${esc(fmtBytes(x.up))}"><i>↑</i><b>${fmtBytes(x.up)}</b></span>` +
    `</span>` +
    `<span class="hr-half">` +
      `<span class="v down" title="下载 ${esc(fmtBytes(x.dl))}"><i>↓</i><b>${fmtBytes(x.dl)}</b></span>` +
      `<span class="hr-date">${esc(x.date)}</span>` +
    `</span>` +
  `</div>`;
}
/* 展开菜单 = 重置到最近周期：清空、start 归零、滚动归零、加载首批 10 条。 */
async function initHistMenu(menu) {
  const list = menu.querySelector('.hist-list');
  if (!list) return;
  menu._start = 0; menu._loading = false; menu._unit = menu.dataset.unit;
  list.innerHTML = '<div class="hist-empty">加载中…</div>';
  list.scrollTop = 0;
  await loadMoreHist(menu);
}
/* 无限下滑：滚到底再拉下一批。后端对更早周期仍返回条目（数据为 0），
 没有最早下限；_loading 标志防止一次滚动触发多个并发请求。 */
async function loadMoreHist(menu) {
  if (menu._loading || menu.hidden) return;
  const list = menu.querySelector('.hist-list');
  if (!list) return;
  menu._loading = true;
  const start = menu._start || 0;
  try {
    const j = await api('/api/periods/page?unit=' + encodeURIComponent(menu._unit) +
                        '&start=' + start + '&count=10');
    if (menu.hidden) { menu._loading = false; return; }   // 期间菜单被关掉了
    if (start === 0) list.innerHTML = '';
    list.insertAdjacentHTML('beforeend', j.items.map(histRowHTML).join(''));
    menu._start = start + j.items.length;
  } catch (e) {
    if (start === 0) list.innerHTML = '<div class="hist-empty">历史数据加载失败</div>';
  }
  menu._loading = false;
}
function renderSummary() {
  const P = S.periods;
  // 定时刷新会重建卡片，记住当前展开的清单并在重建后恢复（重新加载首批）
  const openMenu = $('#summaryCards .card-dd-menu:not([hidden])');
  const keepOpen = openMenu ? openMenu.dataset.unit : null;
  if (!P) {
    $('#summaryCards').innerHTML = PERIOD_UNITS.map((u) =>
      `<div class="card"><div class="card-head"><div class="card-ttl"><b>${u.title}</b></div></div>` +
      `<div class="card-vals"><span class="v up"><i>↑</i><b>—</b></span>` +
      `<span class="v down"><i>↓</i><b>—</b></span></div></div>`).join('');
    return;
  }
  $('#summaryCards').innerHTML = PERIOD_UNITS.map((u) => {
    // 卡片恒取 list[0]（当前周期），不再随下拉选择变化
    const it = (P[u.unit] || [])[0] || { label: u.title, date: '', up: 0, dl: 0 };
    return `<div class="card" data-unit="${u.unit}">` +
      `<div class="card-head">` +
        `<div class="card-ttl"><b title="${esc(u.title)}">${esc(u.title)}</b>` +
        `<span class="card-date" title="${esc(it.date)}">${esc(it.date)}</span></div>` +
        `<div class="card-dd dropdown">` +
          `<button class="dd-trigger card-dd-trigger" type="button" data-unit="${u.unit}" ` +
            `aria-haspopup="true" aria-expanded="false" title="查看历史数据">` +
            `<span class="dd-count">历史数据</span><span class="caret">▾</span></button>` +
          `<div class="dd-menu card-dd-menu hist-menu" data-unit="${u.unit}" hidden>` +
            `<div class="dd-title hist-title">历史周期数据</div>` +
            `<div class="hist-list" data-unit="${u.unit}"></div>` +
          `</div>` +
        `</div>` +
      `</div>` +
      `<div class="card-vals">` +
        `<span class="v up" title="上传 ${esc(fmtBytes(it.up))}"><i>↑</i><b>${fmtBytes(it.up)}</b></span>` +
        `<span class="v down" title="下载 ${esc(fmtBytes(it.dl))}"><i>↓</i><b>${fmtBytes(it.dl)}</b></span>` +
      `</div></div>`;
  }).join('');
  if (keepOpen) {
    const trig = $('#summaryCards .card-dd-trigger[data-unit="' + keepOpen + '"]');
    const menu = $('#summaryCards .card-dd-menu[data-unit="' + keepOpen + '"]');
    if (trig && menu) {
      menu.hidden = false;
      trig.classList.add('open');
      trig.setAttribute('aria-expanded', 'true');
      keepMenuInViewport(menu);
      initHistMenu(menu);          // 重建后重新拉首批，回到最近周期
    }
  }
}
/* 卡片清单下拉：展开即重置到最近周期；菜单内点击不关闭、不选择（纯展示）。
 scroll 事件不冒泡，用捕获阶段委托到 .hist-list 实现无限下滑。 */
function bindSummaryCards() {
  const host = $('#summaryCards');
  host.addEventListener('click', (e) => {
    const trig = e.target.closest('.card-dd-trigger');
    if (trig) {
      e.stopPropagation();
      const menu = trig.parentElement.querySelector('.card-dd-menu');
      const willOpen = menu.hidden;
      closeAllDropdowns();
      if (willOpen) {
        menu.hidden = false;
        trig.classList.add('open');
        trig.setAttribute('aria-expanded', 'true');
        keepMenuInViewport(menu);
        initHistMenu(menu);        // 每次重新弹出都回到最近历史周期
      }
      return;
    }
    const menu = e.target.closest('.card-dd-menu');
    if (menu) e.stopPropagation();   // 清单内任意点击都不触发全局关闭
  });
  host.addEventListener('scroll', (e) => {
    const t = e.target;
    const list = t.closest && t.closest('.hist-list');
    if (!list) return;
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 24) {
      const menu = list.closest('.card-dd-menu');
      if (menu && !menu.hidden) loadMoreHist(menu);
    }
  }, true);
}
function renderStatus() {
  const o = S.overview;
  if (!o) return;
  const t = o.total;
  S.statusLine = `${t.online}/${t.count} 个下载器在线 · 每 ${o.collector.interval}s 采样 · UTC+${S.tz}`;
  $('#lastUpdate').textContent = '更新于 ' + fmtClock(o.server_time);
  const healthy = o.collector.ticks > 0 && !o.collector.last_error;
  setHealth(healthy, healthy ? '采集中' : (o.collector.last_error || '等待首轮采集'));
}

/* ---------------- 下载器卡片 ----------------
 第一行：汇总（占满一行）；其余下载器用 3 列网格，放不下自动换行，不再横向滚动。
 布局：每张卡片两行 ——
 第一行：状态点 + 名称（左，完整显示绝不省略） + 右上角更短的胶囊开关；
 第二行：实时上传 / 下载速率（左，靠左排列） + 类型 / 在线标签（右下角）。
 选中状态只由胶囊开关呈现，单击卡片其余区域打开详情弹窗（汇总卡开汇总详情）。 */
function switchHTML(on, label) {
  return `<button type="button" class="dl-switch ${on ? 'on' : ''}" role="switch" ` +
    `aria-checked="${on}" aria-label="${esc(label)}" title="${esc(label)}">` +
    `<span class="knob"></span></button>`;
}
/* 下载器名称必须 100% 完整可见，绝不用省略号。渲染后逐卡测量：
 单行放不下就等比缩小该名称字号（下限 9px），缩到下限仍放不下则允许换行，
 两种情况都不裁剪、不省略。CSS 侧也去掉了 ellipsis，双保险。 */
function fitChipNames(host) {
  if (!host) return;
  host.querySelectorAll('.dl-nm').forEach((n) => {
    n.style.fontSize = '';
    n.style.whiteSpace = 'nowrap';
    n.style.overflowWrap = '';
    const avail = n.clientWidth || (n.parentElement && n.parentElement.clientWidth) || 0;
    if (!avail) return;
    const base = parseFloat(getComputedStyle(n).fontSize) || 12;
    for (let k = 0; k < 6; k++) {
      if (n.scrollWidth <= n.clientWidth + 0.5) break;
      const cur = parseFloat(getComputedStyle(n).fontSize) || base;
      const next = Math.max(9, cur * (n.clientWidth / n.scrollWidth) * 0.985);
      if (next >= cur - 0.05) break;
      n.style.fontSize = next.toFixed(2) + 'px';
    }
    if (n.scrollWidth > n.clientWidth + 1) {
      n.style.whiteSpace = 'normal';
      n.style.overflowWrap = 'anywhere';
    }
  });
}
function renderDownloaders() {
  const ds = (S.overview && S.overview.downloaders) || [];
  const t = (S.overview && S.overview.total) || { up_rate: 0, dl_rate: 0, online: 0, count: 0 };
  const sumSel = S.pick.has('all');
  const rates = (up, dl) =>
    `<div class="dl-rates">` +
    `<span class="u" title="上传 ${esc(fmtRate(up))}"><b class="rf">↑ ${fmtRate(up)}</b><b class="rc">↑${fmtRateCompact(up)}</b></span>` +
    `<span class="d" title="下载 ${esc(fmtRate(dl))}"><b class="rf">↓ ${fmtRate(dl)}</b><b class="rc">↓${fmtRateCompact(dl)}</b></span></div>`;
  const sum =
    `<div class="dl-row dl-row-sum">` +
    `<div class="dl-chip summary" data-v="all" title="单击查看全部下载器汇总详情">` +
      `<div class="dl-top"><div class="nm"><i class="dot"></i><span class="dl-nm">汇总 · 全部下载器</span></div>` +
      switchHTML(sumSel, '汇总线：' + (sumSel ? '已开启，点击关闭' : '已关闭，点击开启')) +
      `</div>` +
      `<div class="dl-bottom">` + rates(t.up_rate, t.dl_rate) +
      `<span class="tag dl-tag">${t.online}/${t.count} 在线</span></div>` +
    `</div></div>`;
  let items;
  if (!ds.length) {
    items = `<div class="dl-row"><p class="hint">还没有下载器，请在「设置 → 下载器」中添加。</p></div>`;
  } else {
    items = `<div class="dl-row dl-row-items">` + ds.map((d) => {
      const off = d.status !== 'online';
      const sel = S.pick.has(String(d.id));
      return `<div class="dl-chip ${off ? 'off' : ''}" data-v="${d.id}" title="${esc(d.name)}：单击查看详情">` +
        `<div class="dl-top"><div class="nm"><i class="dot ${off ? 'off' : ''}"></i><span class="dl-nm">${esc(d.name)}</span></div>` +
        switchHTML(sel, esc(d.name) + '：' + (sel ? '已加入图表，点击移出' : '未加入图表，点击加入')) +
        `</div>` +
        `<div class="dl-bottom">` + rates(d.up_rate, d.dl_rate) +
        `<span class="tag dl-tag">${d.type === 'qb' ? 'qB' : 'TR'}</span></div>` +
      `</div>`;
    }).join('') + `</div>`;
  }
  const host = $('#dlStrip');
  host.innerHTML = sum + items;
  fitChipNames(host);
  if (!window._chipNameResize) {
    window._chipNameResize = true;
    window.addEventListener('resize', () => {
      if (S.logged) fitChipNames($('#dlStrip'));
    });
  }
}

/* ---------------- 下载器详情弹窗 ----------------
 单击卡片打开，按需向 /api/downloaders/<id>/detail 取一次实时快照；
 弹窗可见时每 5 秒静默刷新，保证「实时上下行速度」不陈旧。 */
const DL_BADGE = {
  qb: `<svg viewBox="0 0 64 64" role="img" aria-label="qBittorrent">` +
    `<circle cx="32" cy="32" r="30" fill="#2f7ad1"/>` +
    `<circle cx="32" cy="32" r="23" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="2"/>` +
    `<text x="32" y="41" text-anchor="middle" font-size="25" font-weight="700" ` +
    `fill="#fff" font-family="Arial,Helvetica,sans-serif">qB</text></svg>`,
  tr: `<svg viewBox="0 0 64 64" role="img" aria-label="Transmission">` +
    `<circle cx="32" cy="32" r="30" fill="#d1503f"/>` +
    `<circle cx="32" cy="32" r="23" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="2"/>` +
    `<text x="32" y="41" text-anchor="middle" font-size="25" font-weight="700" ` +
    `fill="#fff" font-family="Arial,Helvetica,sans-serif">TR</text></svg>`,
};
let detailTimer = null, detailId = null, detailMode = null;  // 'single' | 'summary'
const IO_LEVEL_TEXT = { good: '健康', warn: '繁忙', bad: '过载' };

function detailMeta() {
  return ((S.overview && S.overview.downloaders) || [])
    .find((x) => Number(x.id) === Number(detailId)) || {};
}
function dtLimit(v, arrow) {
  if (Number(v) > 0) {
    return `<span class="dt-lim">${arrow} ${fmtRate(v)}</span>`;
  }
  return `<span class="dt-lim" title="${arrow} 不限速">${arrow} ` +
    `<b class="dt-inf" role="img" aria-label="不限速">∞</b></span>`;
}
function dtStat(label, value, cls) {
  return `<div class="dt-stat ${cls || ''}"><span>${label}</span><b>${value}</b></div>`;
}
/* qB 的 I/O 胶囊显示「排队 I/O 作业数」这个整数，并按三级阈值着色：
 绿=健康(<warn) / 黄=繁忙(warn~bad) / 红=过载(>=bad)。TR 不显示 I/O。 */
function ioPillHTML(j) {
  if (j.type !== 'qb' || !j.io) return '';
  const lv = j.io_level || 'good';
  const warn = j.io_warn, bad = j.io_bad;
  const tip = `${j.io_label || '排队 I/O 作业'}：${j.io_value}（${IO_LEVEL_TEXT[lv] || ''}）` +
    (warn != null && bad != null
      ? `　绿 <${warn} / 黄 ${warn}~${bad - 1} / 红 ≥${bad}` : '') +
    (j.io_full ? `　|　${j.io_full}` : '');
  return `<span class="dt-pill io io-${lv}" title="${esc(tip)}">${esc(j.io)}</span>`;
}
function dtPillsHTML(j) {
  return `<span class="dt-pill" title="下载器版本">${esc(j.version || '未知')}</span>` + ioPillHTML(j);
}
/* 头部：左图标（撑满三行高）+ 三行「每行左右独立」的内容。
 旧版是「中间三行」与「右侧三行」各占一个 grid 列，右侧列宽度会被第一行较长
 的「实时 ↑↓ 速度」撑大，反过来把中间列压窄，导致第二行的「下载地址」被迫
 换行 —— 明明第二行右侧的「限速」很短却跟着受牵连。改成每行一个独立 flex 行
 后，各行左侧可用宽度只受「同一行」右侧内容影响：第二行右侧限速短，地址就
 占满整行、不再换行。单台弹窗与汇总弹窗逐台明细共用这套头部。 */
function dtHeadHTML(name, url, j) {
  const isQb = j.type === 'qb';
  const free = (j.free_space == null) ? '—' : fmtBytes(j.free_space);
  return `<div class="dt-head">` +
    `<div class="dt-badge ${isQb ? 'qb' : 'tr'}">${DL_BADGE[isQb ? 'qb' : 'tr']}</div>` +
    `<div class="dt-main">` +
      `<div class="dt-row">` +
        `<div class="dt-l dt-line dt-name" title="${esc(name)}">${esc(name)}</div>` +
        `<div class="dt-r dt-line"><span class="dt-k">实时</span>` +
          `<b class="u">↑ ${fmtRate(j.up_rate)}</b><b class="d">↓ ${fmtRate(j.dl_rate)}</b></div>` +
      `</div>` +
      `<div class="dt-row">` +
        `<div class="dt-l dt-line dt-url" title="${esc(url)}">${esc(url)}</div>` +
        `<div class="dt-r dt-line"><span class="dt-k">限速</span>` +
          dtLimit(j.up_limit, '↑') + dtLimit(j.dl_limit, '↓') + `</div>` +
      `</div>` +
      `<div class="dt-row">` +
        `<div class="dt-l dt-line dt-pills">${dtPillsHTML(j)}</div>` +
        `<div class="dt-r dt-line"><span class="dt-k">剩余</span><b>${free}</b></div>` +
      `</div>` +
    `</div>` +
  `</div>`;
}
/* 下半部分三行统计：种子总数/总大小 + 4 类活跃 + 4 类其它。单台与汇总共用。 */
function dtStatsHTML(t) {
  t = t || {};
  return `<div class="dt-stats">` +
    `<div class="dt-stats-row two">` +
      dtStat('种子总数', Number(t.total || 0)) +
      dtStat('种子总大小', fmtBytes(t.total_size || 0), 'wide') +
    `</div>` +
    `<div class="dt-stats-row four">` +
      dtStat('正在做种', Number(t.seeding || 0)) +
      dtStat('正在上传', Number(t.uploading || 0)) +
      dtStat('正在下载', Number(t.downloading || 0)) +
      dtStat('等待状态', Number(t.waiting || 0)) +
    `</div>` +
    `<div class="dt-stats-row four">` +
      dtStat('校验状态', Number(t.checking || 0)) +
      dtStat('暂停上传', Number(t.paused_up || 0)) +
      dtStat('暂停下载', Number(t.paused_down || 0)) +
      dtStat('错误状态', Number(t.error || 0), 'bad') +
    `</div>` +
  `</div>`;
}
function renderDetail(j) {
  const d = detailMeta();
  $('#detailBody').innerHTML = dtHeadHTML(d.name || ('#' + detailId), d.url || '—', j) +
    dtStatsHTML(j.torrents);
}
/* 汇总详情：标题＝汇总速率 + 下载器数量/连接情况；第一块＝全部下载器求和；
 第二块＝按 sort_order 逐台列出，每台与单台详情完全同款。
 注意：顶部 4 张周期卡片的渲染函数叫 renderSummary（无参），此处必须另起名字，
 否则会覆盖它导致 boot 阶段报错。 */
function renderSummaryDetail(j) {
  const t = j.total || {}, agg = (j.aggregate && j.aggregate.torrents) || {};
  const items = j.items || [];
  const hero =
    `<div class="dt-sum-hero">` +
      `<div class="dt-sum-rates"><span class="dt-k">汇总实时</span>` +
        `<b class="u">↑ ${fmtRate(t.up_rate || 0)}</b>` +
        `<b class="d">↓ ${fmtRate(t.dl_rate || 0)}</b></div>` +
      `<div class="dt-sum-conn"><b>${Number(t.count || 0)}</b> 个下载器 · ` +
        `<span class="ok">${Number(t.online || 0)} 在线</span> / ` +
        `<span class="bad">${Number(t.offline || 0)} 离线</span></div>` +
    `</div>`;
  const perItems = items.map((it, i) => {
    const body = it.detail
      ? dtHeadHTML(it.name, it.url, it.detail) + dtStatsHTML(it.detail.torrents)
      : `<div class="dt-error">${esc(it.error || '读取失败')}` +
        `<br><span class="hint">该下载器当前不可读，其余下载器不受影响</span></div>`;
    return `<div class="dt-item">` +
      `<div class="dt-item-hd"><span class="dt-item-no">${i + 1}</span>` +
      `<b class="dt-item-nm">${esc(it.name)}</b>` +
      `<span class="dt-item-st ${it.online ? 'ok' : 'bad'}">${it.online ? '在线' : '离线'}</span></div>` +
      body + `</div>`;
  }).join('');
  $('#summaryBody').innerHTML = hero +
    `<h3 class="dt-sec">全部下载器汇总</h3>` + dtStatsHTML(agg) +
    `<h3 class="dt-sec">各下载器明细（按设置顺序，共 ${items.length} 台）</h3>` +
    `<div class="dt-items">` +
      (perItems || '<div class="dt-loading">还没有下载器</div>') + `</div>`;
}
async function refreshDetail(first) {
  if (detailMode === 'summary') {
    try {
      const j = await api('/api/downloaders/summary/detail');
      if ($('#summaryModal').hidden) return;
      renderSummaryDetail(j);
    } catch (err) {
      if (first === true) {
        $('#summaryBody').innerHTML =
          `<div class="dt-error">读取失败：${esc(err.message)}` +
          `<br><span class="hint">请确认采集器在线后重试</span></div>`;
      }
    }
    return;
  }
  if (detailId == null) return;
  try {
    const j = await api('/api/downloaders/' + detailId + '/detail');
    if ($('#detailModal').hidden) return;      // 已经关掉，别再改 DOM
    renderDetail(j);
  } catch (err) {
    if (first === true) {
      $('#detailBody').innerHTML =
        `<div class="dt-error">读取失败：${esc(err.message)}` +
        `<br><span class="hint">请确认下载器在线、账号密码正确后重试</span></div>`;
    }
  }
}
function startDetailTimer() {
  if (detailTimer) clearInterval(detailTimer);
  refreshDetail(true);
  detailTimer = setInterval(refreshDetail, 5000);
}
function openDetail(id) {
  closeDetail();                    // 只保留一个详情弹窗
  detailMode = 'single'; detailId = id;
  $('#dlDetailTitle').textContent = '下载器详情 · ' + (detailMeta().name || ('#' + id));
  $('#detailBody').innerHTML = '<div class="dt-loading">正在读取下载器信息…</div>';
  $('#detailModal').hidden = false;
  closeAllDropdowns();
  startDetailTimer();
}
/* 配置表某台下载器「测试」按钮的结果，独立小窗口就地展示 —— 明确
 归属该下载器，含连接状态、实时上下行速率、版本、地址或失败原因。 */
function openTestResult(d, ok, j, err) {
  const ex = (ok && j && j.extra) || {};
  const ver = ex.version || ex.qb_version || ex.tr_version || '';
  let body;
  if (ok) {
    body = `<div class="test-verdict ok"><span class="ic">✓</span>连接成功</div>` +
      `<div class="test-meta">` +
        `<div class="cell"><span>实时上传</span><b class="u">↑ ${fmtRate(j.up_rate)}</b></div>` +
        `<div class="cell"><span>实时下载</span><b class="d">↓ ${fmtRate(j.dl_rate)}</b></div>` +
        (ver ? `<div class="cell"><span>版本</span><b>${esc(String(ver))}</b></div>` : '') +
        `<div class="cell"><span>类型</span><b>${d.type === 'qb' ? 'qBittorrent' : 'Transmission'}</b></div>` +
      `</div>` +
      `<div class="test-url">${esc(d.url)}</div>`;
  } else {
    body = `<div class="test-verdict bad"><span class="ic">✗</span>连接失败</div>` +
      `<div class="test-err">${esc(err || '未知错误')}</div>` +
      `<div class="test-url">${esc(d.url)}</div>`;
  }
  $('#testTitle').textContent = '连接测试 · ' + d.name;
  $('#testBody').innerHTML = body;
  $('#testModal').hidden = false;
  closeAllDropdowns();
}
function closeTest() { $('#testModal').hidden = true; }
function openSummary() {
  closeDetail();
  detailMode = 'summary';
  $('#summaryBody').innerHTML = '<div class="dt-loading">正在汇总全部下载器信息…</div>';
  $('#summaryModal').hidden = false;
  closeAllDropdowns();
  startDetailTimer();
}
function closeDetail() {
  $('#detailModal').hidden = true;
  $('#summaryModal').hidden = true;
  if (detailTimer) { clearInterval(detailTimer); detailTimer = null; }
  detailId = null; detailMode = null;
}

/* ---------------- 时间范围单选下拉 + 方向多选下拉 ---------------- */
function liveLabel() {
  const span = (S.settings && S.settings.live_span) || 300;
  return '实时·' + (LIVE_SHORT[span] || '5分');
}
function rangeLabel(k) { return k === 'live' ? liveLabel() : (RANGE_LABELS[k] || k); }
function dirOptions() { return [{ v: 'up', name: '上传' }, { v: 'down', name: '下载' }]; }
function dirLabel(which) {
  const st = S[which];
  if (!st.dirs.size) return '未选择';
  if (st.dirs.has('up') && st.dirs.has('down')) return '双向';
  return st.dirs.has('up') ? '仅上传' : '仅下载';
}
function renderRangeDropdown(which) {
  const st = S[which], p = '#' + which;
  $(p + 'RangeTrigger').innerHTML =
    `<span>范围</span><span class="dd-count">${esc(rangeLabel(st.range))}</span><span class="caret">▾</span>`;
  $(p + 'RangeMenu').innerHTML =
    `<div class="dd-title">时间范围（单选）</div>` +
    rangeOrder(which).map((k) =>
      `<label class="dd-item ${st.range === k ? 'active' : ''}">` +
      `<input type="radio" name="${which}Range" value="${k}" ${st.range === k ? 'checked' : ''}>` +
      `<span class="nm">${esc(rangeLabel(k))}</span></label>`).join('');
}
function renderDropdown(which) {
  const st = S[which], p = '#' + which;
  $(p + 'DirTrigger').innerHTML =
    `<span>方向</span><span class="dd-count">${esc(dirLabel(which))}</span><span class="caret">▾</span>`;
  $(p + 'DirMenu').innerHTML =
    `<div class="dd-title">显示方向（可多选）</div>` +
    dirOptions().map((o) =>
      `<label class="dd-item"><input type="checkbox" data-v="${o.v}" ${st.dirs.has(o.v) ? 'checked' : ''}>` +
      `<i class="sw" style="background:${summaryColor(o.v)}"></i><span class="nm">${o.name}</span></label>`).join('') +
    `<div class="dd-foot"><button type="button" data-act="all">双向</button>` +
    `<button type="button" data-act="none">仅上传</button></div>`;
}
/* 下拉展开后夹回视口内：绝对定位菜单在窄屏左列卡片上会向左溢出屏幕，
 按实测边界平移回来；任意屏宽 / 列数 / 任意下拉都适用，也不影响菜单布局。 */
function keepMenuInViewport(menu) {
  if (!menu || menu.hidden) return;
  menu.style.transform = '';
  const r = menu.getBoundingClientRect();
  if (!r.width) return;
  const gap = 8, vw = document.documentElement.clientWidth;
  let dx = 0;
  if (r.left < gap) dx = gap - r.left;
  else if (r.right > vw - gap) dx = (vw - gap) - r.right;
  if (dx) menu.style.transform = 'translateX(' + Math.round(dx) + 'px)';
}
function toggleMenu(trig, menu) {
  const willOpen = menu.hidden;
  closeAllDropdowns();
  menu.hidden = !willOpen;
  trig.classList.toggle('open', willOpen);
  trig.setAttribute('aria-expanded', String(willOpen));
  if (willOpen) keepMenuInViewport(menu);
}
function closeAllDropdowns() {
  $$('.dd-menu').forEach((m) => { m.hidden = true; m.style.transform = ''; });
  $$('.dd-trigger').forEach((t) => { t.classList.remove('open'); t.setAttribute('aria-expanded', 'false'); });
}
/* 下载器被删除导致选项失效时清理，顺带重绘卡片、范围与方向下拉 */
function syncPicks() {
  const valid = new Set(['all'].concat(((S.overview && S.overview.downloaders) || [])
    .map((d) => String(d.id))));
  let removed = false;
  Array.from(S.pick).forEach((v) => { if (!valid.has(v)) { S.pick.delete(v); removed = true; } });
  if (removed && !S.pick.size) S.pick.add('all');
  if (removed) saveState();
  renderDownloaders();
  ['rate', 'traffic'].forEach((w) => { renderRangeDropdown(w); renderDropdown(w); });
}
function bindRangeDropdown(which) {
  const st = S[which], p = '#' + which;
  const trig = $(p + 'RangeTrigger'), menu = $(p + 'RangeMenu');
  trig.addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(trig, menu); });
  menu.addEventListener('click', (e) => {
    e.stopPropagation();
    const item = e.target.closest('.dd-item');
    if (!item) return;
    const radio = item.querySelector('input[type=radio]');
    const v = radio ? radio.value : '';
    if (rangeOrder(which).indexOf(v) < 0) return;
    // label 与内部 radio 会各冒泡一次 click；已选中或刚处理过就直接收起菜单
    if (v === st.range) { closeAllDropdowns(); return; }
    st.range = v; st._hover = null; st.offset = 0;   // 换范围一律回到最新窗口
    saveState(); renderRangeDropdown(which); renderLatestBtn(which); closeAllDropdowns();
    loadChart(which);
  });
}
function bindDropdowns(which) {
  const st = S[which], p = '#' + which;
  const trig = $(p + 'DirTrigger'), menu = $(p + 'DirMenu');
  trig.addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(trig, menu); });
  menu.addEventListener('click', (e) => {
    e.stopPropagation();
    const act = e.target.closest('[data-act]');
    if (!act) return;
    if (act.dataset.act === 'all') dirOptions().forEach((o) => st.dirs.add(o.v));
    else { st.dirs.clear(); st.dirs.add('up'); }
    saveState(); renderDropdown(which);
    menu.hidden = false; trig.classList.add('open'); trig.setAttribute('aria-expanded', 'true');
    keepMenuInViewport(menu);
    renderChart(which);
  });
  menu.addEventListener('change', (e) => {
    const cb = e.target.closest('input[type=checkbox]');
    if (!cb) return;
    if (cb.checked) st.dirs.add(cb.dataset.v);
    else st.dirs.delete(cb.dataset.v);
    saveState(); renderDropdown(which);
    menu.hidden = false; trig.classList.add('open'); trig.setAttribute('aria-expanded', 'true');
    keepMenuInViewport(menu);
    renderChart(which);
  });
}

/* ---------------- 按画布宽度限制「可见点数」 ----------------
 参考 sqing33/PTNexus —— 速率折线的数据点由后端按固定时间粒度做 AVG
 聚合（点数与采集频率解耦），前端再按画布宽度限制一次能看到多少个点
 （ptnexus 手机端用 dataZoom 只显示 12 个可见点，本项目按每点 ≥4px 自适应）。
 这样既不会像 那样把 1080 个采样点全糊在一张图上，也不会退回旧版 12 点
 的稀疏折线。流量堆叠柱状图仍按柱宽抽稀，窄屏不至于被压成细线。 */
function targetPoints(which) {
  const cv = which === 'rate' ? $('#rateChart') : $('#trafficChart');
  const w = cv.getBoundingClientRect().width || (window.innerWidth - 40);
  // 与 charts.js makePad 的左右留白对齐（桌面 l≈78+r30、
  // 紧凑 l≈42+r26），略保守，确保「1 像素 1 点」不因留白估算偏大而超标。
  const plotW = Math.max(120, w - (w < 480 ? 68 : 108));
  // 速率：上限 = 绘图区像素宽度 ⇒ 1 像素最多 1 个绘制点。后端按目标密度
  // （1h 1800 / 6h 1440 / 24h 1440 点）把点给足，downsample 仅在点数 > plotW
  // 时按比例聚合收敛到 ≤ plotW；点数 ≤ plotW 时原样保留，细节不丢失。
  // live 档仍由 renderChart 强制不降采样（见下方 pts 计算），零形变。
  // 流量：维持原「按柱宽抽稀」口径（下限 12 保证采样类窗口不被压成细线）。
  // 本月 / 上月 / 全部三个范围在 renderChart 里豁免本上限，直接保留
  // 后端全部数据点（详见 renderChart 的 KEEP_ALL），其余范围口径不变。
  return which === 'rate'
    ? Math.max(60, Math.floor(plotW))
    : Math.max(12, Math.min(60, Math.floor(plotW / 26)));
}
function downsample(data, maxPoints, mode) {
  const n = data.labels.length;
  const M = Math.max(1, Math.floor(maxPoints));
  // 点数没超过「1 像素 1 点」上限就原样保留（live 档恒走这里，
  // 零降采样、零形变）。超过时把 n 个原始点按目标点数 M **均匀分成恰好 M 组**
  // （每组 1~2 个点按比例分摊），输出正好 M 个点 —— 旧实现用整数步长
  // k=ceil(n/M) 会把点数再砍掉近一半（如 1440→1180 上限却只给 720 点），
  // 用户会觉得「绘制点还是不够」。均匀分组让绘制点尽量贴近绘图区像素宽度，
  // 同时严格满足「1 像素最多 1 个绘制点」。
  if (n <= M) return data;
  const b0 = [], b1 = [];
  for (let j = 0; j < M; j++) {
    b0[j] = Math.floor(j * n / M);
    b1[j] = Math.min(n, Math.floor((j + 1) * n / M));
    if (b1[j] <= b0[j]) b1[j] = Math.min(n, b0[j] + 1);
  }
  const agg = (arr) => {
    const out = [];
    for (let j = 0; j < M; j++) {
      let sum = 0, cnt = 0;
      for (let i = b0[j]; i < b1[j]; i++) {
        const v = arr[i];
        if (v == null) continue;
        sum += Number(v) || 0; cnt++;
      }
      // avg 模式（速率）保留两位小数，不再用 Math.round 抹掉小数位；
      // sum 模式（流量字节累加）本来就是整数，保持原样
      if (!cnt) out.push(mode === 'avg' ? null : 0);
      else out.push(mode === 'avg' ? Number((sum / cnt).toFixed(2)) : sum);
    }
    return out;
  };
  const labels = [], times = [], spans = [];
  for (let j = 0; j < M; j++) {
    const lo = b0[j], hi = b1[j] - 1;
    labels.push(data.labels[lo]); times.push(data.times[lo]);
    // 相邻桶被合并成一个时，标题时间段也要跟着合并成「首桶起点 ~ 末桶终点」
    spans.push(data.spans && data.spans[lo] && data.spans[hi]
      ? [data.spans[lo][0], data.spans[hi][1]]
      : [data.times[lo], data.times[hi] + 1]);
  }
  /* b：后端已把 rate 折线最后一点对齐 window.end。降采样后最后一
 组取的是 b0[M-1]（< n-1），若沿用该组「起点时刻」，右端又退回「少一桶」
 的桶起点，手机端几乎所有非 live 档都会降采样、问题会复现。这里把 rate
 降采样后的末点时间 / 标签强制对齐 data 的末端（= 窗口右端）。traffic
 柱状按柱组区间语义、tooltip 用 spans 时间段，保持原样不受影响。 */
  if (data.metric === "rate" && M > 1 && n > 1) {
    times[M - 1] = data.times[n - 1];
    labels[M - 1] = data.labels[n - 1];
  }
  const outSeries = data.series.map((s) =>
    Object.assign({}, s, { up: agg(s.up), down: agg(s.down) }));
  /* avg 模式（速率）下每条线独立窗口平均会破坏「汇总 = 各下载器
 速度之和」—— 各下载器采样落在不同桶、或 4 台写 0 的桶把汇总 avg 稀释，
 就会出现「汇总 80 < 单下载器 100」。降采样后按各下载器线逐点重新求和，
 让汇总线恒等于用户看到的「各下载器速度之和」，与后端 _fill_rate_gaps
 的口径一致。traffic 的 sum 模式本就是线性（sum of sums = sum of sums），
 不受影响、无需处理。 */
  if (data.metric === "rate" && outSeries.length > 1) {
    const s0 = outSeries[0], others = outSeries.slice(1);
    ["up", "down"].forEach((key) => {
      s0[key] = s0[key].map((_, i) => {
        const vs = others.map((s) => s[key][i]).filter((v) => v != null);
        return vs.length ? Number(vs.reduce((a, b) => a + b, 0).toFixed(2)) : null;
      });
    });
  }
  return Object.assign({}, data, { labels, times, spans, series: outSeries });
}

/* ---------------- 图表渲染 ---------------- */
function renderChart(which, animate) {
  const st = S[which], cv = which === 'rate' ? $('#rateChart') : $('#trafficChart');
  const axis = $('#' + which + 'Axis');          // 固定坐标轴层，不随拖动平移
  if (!st.data) {
    if (which === 'rate') TTMCharts.drawLines(cv, { labels: [], lines: [], fmt: fmtRate,
      axis, empty: '正在加载数据…' });
    else TTMCharts.drawBars(cv, { labels: [], groups: [], dirs: { up: true, down: true },
      fmt: fmtBytes, axis, empty: '正在加载数据…' });
    return;
  }
  const maxPts = targetPoints(which);
  /* 实时档给足绘图区采样点密度。后端 live 已按 RATE_MAX_POINTS 把
 采样点给足；前端若仍按「每点 ≥4px」把 100~180 点降采样成 30~70 点，
 聚合窗口会随实时窗口推进而整体滑动，每个下采样点的 AVG 取数都变，
 曲线左移后就会「形状变化」。实时档直接用后端全部点（k=1）可彻底规避；
 采样间隔设得长导致点数本就偏少时，由 charts.js 自适应放慢左移速度。 */
  /* / 流量统计卡片的「本月 / 上月 / 全部」必须逐组保留
 后端给的全部数据点，不允许前端按画布宽度抽稀合并。
 · 本月 / 上月：后端 _traffic_period 早就是「本月＝当前日号个点、
 上月＝该月天数个点」的按天分桶，但 及以前手机端
 targetPoints('traffic') 下限 12 + downsample(sum) 会把这 28~31
 天合并成 12 组，中间的日期数据被吞 —— 这正是用户反馈的 bug。
 · 全部：后端按自然日 / 月 / 季度 / 年给 ≤30 / 24 / 20 个柱组，
 同样不能被 12 组下限截断，否则「单个柱组＝一个自然单位」的语义失效。
 这三个范围桌面 / 手机统一走「零降采样」；点密时由 charts.js drawBars
 把柱子缩窄到最窄 3px，组间留白公式与 X 轴刻度密度（axisXMarkup 的
 2.5 个数字字符净空白）标准均保持不变。其余范围口径一律不动。 */
  const KEEP_ALL = which === 'traffic' &&
    (st.range === 'month' || st.range === 'lastmonth' || st.range === 'all');
  const pts = ((which === 'rate' && st.range === 'live') || KEEP_ALL)
    ? Math.max(maxPts, st.data.labels.length) : maxPts;
  st.view = downsample(st.data, pts, which === 'rate' ? 'avg' : 'sum');
  which === 'rate' ? drawRate(st, animate) : drawTraffic(st);
}

/* ---------------- 桌面端绘图区按浏览器真实可用高度动态分配 ----------------
 1920×1080 是「屏幕物理分辨率」：浏览器标签栏 / 地址栏 / 书签栏 + 操作系统
 任务栏会占掉一大截，页面真正可用的 window.innerHeight 远小于 1080。把
 .chart-lg 写死 240px，只在 innerHeight≈1080 的理想视口下刚好放下，真实窗口
 （innerHeight≈820~960）就会超出、出现纵向滚动条 —— 这正是用户反馈的问题。
 做法：运行时先读 window.innerHeight（实际可用高度），量出「除两个绘图区外的
 固定内容高度」，把剩余空间（扣安全余量）平分给两张卡片的绘图区，用 inline
 height 覆盖 CSS 回退值并触发重绘；窗口 / 可用高度一变就实时重算，始终无
 纵向滚动条。仅桌面端（≥901px，与 CSS 断点一致）启用；≤900px 清除 inline
 交还 CSS 的 480 / 380px，手机端逐像素 */
const FIT_MQ = '(min-width:901px)';
const FIT_MIN_H = 120, FIT_MAX_H = 560, FIT_SAFE = 16;
let _fitRaf = 0, _fitInstalled = false;

function fitHosts() {
  return Array.prototype.slice.call(
    document.querySelectorAll('.chart-viewport .chart-lg'));
}
function fitCharts() {
  return Array.prototype.slice.call(
    document.querySelectorAll('.chart-viewport .chart.chart-lg'));
}
/* 文档「真实内容底边」。不能用 documentElement.scrollHeight：body 有
 min-height:100vh，内容不足视口时 scrollHeight 会被撑成 innerHeight，拿它做
 减法反推固定高度会逐帧缩小、无法收敛。main 底边 + 滚动偏移才是真实内容高。 */
function fitContentBottom() {
  const main = document.querySelector('main');
  if (!main) return document.documentElement.scrollHeight;
  return main.getBoundingClientRect().bottom + (window.pageYOffset || 0);
}
function fitRedrawCharts() {
  if (!S.logged || !S.rate || !S.traffic) return;
  renderChart('rate'); renderChart('traffic');
}
/* 计算并设置高度，返回是否发生了改动（调用方据此决定是否重绘）。 */
function fitDesktopCharts() {
  const hosts = fitHosts();
  if (!hosts.length) return false;
  if (!window.matchMedia(FIT_MQ).matches) {
    let cleared = false;
    hosts.forEach((h) => { if (h.style.height) { h.style.height = ''; cleared = true; } });
    return cleared;                         // 切回窄屏：交还 CSS，需重绘
  }
  const charts = fitCharts();
  if (charts.length !== 2) return false;
  const curH = charts[0].getBoundingClientRect().height;
  if (!(curH > 0)) return false;
  const fixedH = fitContentBottom() - 2 * curH;   // 两个 viewport 之外的固定内容高度
  let per = Math.floor((window.innerHeight - FIT_SAFE - fixedH) / 2);
  per = Math.max(FIT_MIN_H, Math.min(FIT_MAX_H, per));
  if (Math.abs(per - curH) <= 1) return false;     // 已稳定：打断 ResizeObserver 回环
  hosts.forEach((h) => { h.style.height = per + 'px'; });
  return true;
}
/* 桌面端纵坐标刻度数取消「固定 5 个」，改为按**实际绘图区高度**
 自适应，且两张卡片必须用同一个数。做法：每次重绘前读两个 .chart-lg 的
 实测高度算一次等分数，通过 TTMCharts.setTickCount 下发为共享值，
 drawLines / drawBars 都读它 ⇒ 哪怕只有一张卡单独重绘也保持一致。
 手机 / 平板（<901px）下发 0，charts.js 内 yTickCount 自动回落到
 6 等分，窗口高度 / 断点变化导致共享值变化时
 强制重绘两图，保证刻度数实时一致。 */
function syncTickCount() {
  const C = window.TTMCharts;
  if (!C || typeof C.setTickCount !== 'function') return false;
  let want = 0;
  if (window.matchMedia(FIT_MQ).matches) {
    const hosts = fitHosts();
    const h = hosts.length ? hosts[0].getBoundingClientRect().height : 0;
    want = C.tickCountFor(h);
  }
  return C.setTickCount(want);
}
function fitAndRedraw(force) {
  const changed = fitDesktopCharts();
  /* 放在高度调整之后：用调整后的实测绘图区高度算本次等分数。 */
  const tickChanged = syncTickCount();
  if (changed || force || tickChanged) fitRedrawCharts();
}
function scheduleFit() {
  if (_fitRaf) return;
  _fitRaf = requestAnimationFrame(() => { _fitRaf = 0; fitAndRedraw(false); });
}
function installFitWatchers() {
  if (_fitInstalled) return;
  _fitInstalled = true;
  window.addEventListener('resize', scheduleFit, { passive: true });
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', scheduleFit, { passive: true });
  }
  const mq = window.matchMedia(FIT_MQ);
  /* 跨越 901px 断点时除重算绘图区高度，还要重排「运行状态」卡片
 （桌面端合并成单一 auto-fit 网格，手机端恢复两容器分组）。 */
  const onBreakpointChange = () => {
    scheduleFit();
    if (typeof renderAbout === 'function') renderAbout();
  };
  if (mq.addEventListener) mq.addEventListener('change', onBreakpointChange);
  else if (mq.addListener) mq.addListener(onBreakpointChange);
  /* 观察会改变「固定内容高度」的区块：图例行数 / 汇总卡 / 下载器卡片变化也要
 实时重算；ResizeObserver 回环由 fitDesktopCharts 的「差异 ≤1px 不改动」
 打断，稳定后不再重绘。 */
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(scheduleFit);
    ['main', '#summaryCards', '.dl-panel', '.rate-panel',
     '#rateLegend', '#trafficLegend', '#trafficSummary'].forEach((s) => {
      const e = document.querySelector(s); if (e) ro.observe(e);
    });
  }
}
/* 手动触发一次（首屏数据加载完成、以及自动化验证 / 调试用）。 */
window.TTMFit = function () { fitAndRedraw(true); };

function noPickHint() {
  return '请在上方下载器卡片中打开至少一个胶囊开关';
}
function drawRate(st, animate) {
  const view = st.view, cv = $('#rateChart');
  const fmt = view.metric === 'traffic' ? fmtBytes : fmtRate;
  /* 把左上角「时间范围」文字（data.window.label，形如
 "11-13 10:08 ~ 11-13 10:13"）拆成两端，交给 charts.js 作为折线 X 轴
 首 / 末刻度文本，使横坐标首尾与所选范围逐字对齐。
 a：所选范围 ≤24h（live / 1h / 6h / 12h / 今日 / 昨日）时，
 横坐标只显示时间、不显示日期 —— 直接拿带 "MM-DD" 的 window.label
 当首尾刻度，日期占宽把手机端挤到只剩「头尾 + 中间 1 个」。这里用
 window 的真实跨度判定（兼顾 live_span 可调），≤24h 时去掉每段开头的
 "MM-DD " 日期前缀，只留时间；>24h 保留日期以区分跨天。
 中间刻度同步给一份去日期的 axisLabels（仅影响 X 轴刻度文字），tooltip
 仍用原始 labels（保留秒 / 日期精度），两不干扰。 */
  const win = (st.data && st.data.window) || {};
  const shortRange = (Number(win.end) - Number(win.start)) <= 86400 + 120;
  const stripDay = (s) => shortRange ? String(s).replace(/^\d{2}-\d{2}\s+/, '') : String(s);
  const wl = st.windowLabel || '';
  const sep = wl.indexOf(' ~ ');
  const edges = sep > 0
    ? { start: stripDay(wl.slice(0, sep)), end: stripDay(wl.slice(sep + 3)) }
    : null;
  const axisLabels = shortRange ? view.labels.map(stripDay) : view.labels;
  const lines = [], legend = [];
  const upOn = st.dirs.has('up'), downOn = st.dirs.has('down');
  view.series.forEach((s) => {
    const v = s.id === 0 ? 'all' : String(s.id);
    if (!S.pick.has(v)) return;
    // 汇总线降到原单台粗细(1.7)，单台再调细到 0.9，两级明显区分
    const isSum = s.id === 0, width = isSum ? 1.7 : 0.9;
    const name = isSum ? '汇总' : s.name;
    const cu = adapt(s.color_up), cd = adapt(s.color_down);
    // 上传优先：每个下载器先画上传，再画下载
    if (upOn) lines.push({ label: name + ' ↑ 上传', name, dir: 'up', color: cu, width, values: s.up });
    if (downOn) lines.push({ label: name + ' ↓ 下载', name, dir: 'down', color: cd, width, values: s.down });
    legend.push({ name, cu, cd });
  });
  TTMCharts.drawLines(cv, {
    /* 参照 PT Nexus v4.0.2 —— 实时档 1s 刷新、smooth=true 保形平滑
 （单调三次 Hermite 精确过采样点、段内不过冲）；周期刷新传 animate。
 charts.js 按 times 判定窗口真实推进桶数：推进了才做「帧平移」（动画帧
 全程用目标帧真实值、整体左移 + Y 轴上下伸缩，形状恒定），没推进就只做
 纵向伸缩，绝不空移再弹回；点数少时自适应放慢左移。 */
    labels: view.labels, times: view.times, lines, fmt, smooth: true,
    animate: animate === true, axisLabels,
    hover: st._hover, theme: S.theme, axis: $('#rateAxis'), edges,
    empty: lines.length ? '该时间范围暂无采样数据，等待采集器写入…'
      : (S.pick.size ? '请在「方向」下拉中至少选择一项' : noPickHint()),
  });
  /* 两张卡片图例统一为同一套 DOM ——
 桌面端：下载器名称 + 颜色方块 + 箭头 + 「上传 / 下载」；
 手机端：下载器名称 + 箭头（颜色方块与「上传 / 下载」字样由 CSS 收起）。
 流量统计卡片在同一结构的末尾再追加流量数据（见 drawTraffic）。
 方向未选的一侧不显示。两张图例统一走 renderLegend：字号固定＝坐标轴
 刻度字号、按宽度自适应列数、宽度不够换行、留空在第一行、内容完整不省略。 */
  const rateItems = legend.map((p) => {
      const u = upOn ? `<span class="pair up" style="--c:${p.cu}">` +
        `<i class="sq" style="background:${p.cu}"></i>` +
        `<b class="arw" style="color:${p.cu}">↑</b>` +
        `<span class="lg-lb">上传</span></span>` : '';
      const d = downOn ? `<span class="pair down" style="--c:${p.cd}">` +
        `<i class="sq" style="background:${p.cd}"></i>` +
        `<b class="arw" style="color:${p.cd}">↓</b>` +
        `<span class="lg-lb">下载</span></span>` : '';
      return `<span class="lg-item" title="${esc(p.name)}（上传 ↑ / 下载 ↓）">` +
        `<span class="lg-nm">${esc(p.name)}</span>${u}${d}</span>`;
    });
  if (rateItems.length && (upOn || downOn)) {
    renderLegend($('#rateLegend'), rateItems, '#rateChart');
  } else {
    $('#rateLegend').innerHTML = `<span>${S.pick.size ? '请选择方向' : noPickHint()}</span>`;
  }
}

function drawTraffic(st) {
  const view = st.view, cv = $('#trafficChart');
  const allSel = S.pick.has('all');
  // 「汇总」视为全选下载器；具体勾选与汇总取并集，堆叠分段始终有效
  const parts = view.series.filter((s) => s.id !== 0 && (allSel || S.pick.has(String(s.id))))
    .map((s) => ({ id: s.id, name: s.name, color_up: adapt(s.color_up),
      color_down: adapt(s.color_down), up: s.up, down: s.down }));
  const groups = view.labels.map((label, i) => {
    const upParts = parts.map((p) => ({ name: p.name, color: p.color_up, value: Number(p.up[i]) || 0 }));
    const downParts = parts.map((p) => ({ name: p.name, color: p.color_down, value: Number(p.down[i]) || 0 }));
    return { label, upParts, downParts,
      up: upParts.reduce((a, p) => a + p.value, 0),
      down: downParts.reduce((a, p) => a + p.value, 0) };
  });
  const dirs = { up: st.dirs.has('up'), down: st.dirs.has('down') };
  const noData = !parts.length || (!dirs.up && !dirs.down);
  /* 非自然周期范围（实时 / 1 / 6 / 12 小时 / 今日 / 昨日）的每个
 柱组是一个采样 / 小时桶 —— 一段「时间段」而非「某一个日期」，弹出菜单
 标题改成该桶覆盖的时间段；周 / 月 / 年 / 全部按天 / 月聚合成日期标签，
 保持原样。两类范围的分界沿用 的 NATURAL_RANGES。 */
  const spanRange = NATURAL_RANGES.indexOf(st.range) < 0;
  const tipTitles = spanRange
    ? (view.spans || []).map((sp, i) =>
        sp ? fmtSpanTitle(sp[0], sp[1]) : view.labels[i])
    : null;
  /* 流量统计卡片横坐标刻度 = 柱组所覆盖时间段的「中间时刻」。
 charts.js 把柱状图刻度按柱组中心定位（X(i)=pad.l+plotW*((i+.5)/n)），
 落在上传/下载两柱正下方居中；若文字仍用「桶起点」就与这个居中位置
 语义不符，改为取 spans[i] 两端的中点（fmtSpanMid）。
 · 仅对「时间段」类范围生效；周/月/年/全部是「某一个日期」标签，
 整天/整月取中间没有意义，保持原日期刻度不变。
 · 首 / 尾两个刻度是明确例外：用户要求「优先对齐当前选择时间范围的
 首尾时间」，故直接用区间文字 windowLabel 的两端覆盖中间时刻，与
 实时速率卡片 edges、左上角范围文字逐字一致。
 · n===1 只有一个柱组，首尾是同一个刻度，保留中间时刻更贴合居中语义。
 ≤24h 的区间文字去掉 MM-DD 日期前缀，与中间时刻同为纯时间格式；
 刻度密度 / 抽稀仍由 charts.js axisXMarkup 统一处理（的
 2.5 个数字字符净空白，原先是 4 个）。 */
  const tWin = (st.data && st.data.window) || {};
  const tShort = (Number(tWin.end) - Number(tWin.start)) <= 86400 + 120;
  const stripDayT = (s) => tShort
    ? String(s).replace(/^\d{2}-\d{2}\s+/, '') : String(s);
  let tAxisLabels;
  if (spanRange && !noData) {
    tAxisLabels = (view.spans || []).map((sp, i) =>
      sp ? fmtSpanMid(sp) : stripDayT(view.labels[i]));
    const wl = st.windowLabel || '', sep = wl.indexOf(' ~ ');
    if (sep > 0 && tAxisLabels.length > 1) {
      tAxisLabels[0] = stripDayT(wl.slice(0, sep));
      tAxisLabels[tAxisLabels.length - 1] = stripDayT(wl.slice(sep + 3));
    }
  } else {
    /* 日期类范围 / 空数据 —— ≤24h 去日期，跨天周期保留日期区分。 */
    tAxisLabels = tShort
      ? view.labels.map((s) => String(s).replace(/^\d{2}-\d{2}\s+/, ''))
      : view.labels;
  }
  TTMCharts.drawBars(cv, {
    labels: noData ? [] : view.labels, groups: noData ? [] : groups,
    dirs, fmt: fmtBytes, hover: st._hover, theme: S.theme, axis: $('#trafficAxis'),
    axisLabels: noData ? [] : tAxisLabels,
    tipTitles,
    empty: noData ? (S.pick.size ? '请在「方向」下拉中至少选择一项' : noPickHint())
      : '该时间范围暂无数据',
  });
  const su = groups.reduce((a, g) => a + g.up, 0), sd = groups.reduce((a, g) => a + g.down, 0);
  /* 区间数据卡片：只保留 区间上传 / 区间下载 / 合计 三项，左对齐、彼此留白 */
  $('#trafficSummary').innerHTML =
    `<div>区间上传<b class="u">${fmtBytes(dirs.up ? su : 0)}</b></div>` +
    `<div>区间下载<b class="d">${fmtBytes(dirs.down ? sd : 0)}</b></div>` +
    `<div>合计<b>${fmtBytes((dirs.up ? su : 0) + (dirs.down ? sd : 0))}</b></div>`;
  /* 与实时速率卡片共用同一套图例结构 ——
 桌面端：下载器名称 + 颜色方块 + 箭头 + 「上传 / 下载」 + 流量数据；
 手机端：下载器名称 + 箭头 + 流量数据（方块与「上传 / 下载」由 CSS 收起）。
 数据量＝该下载器在当前区间所有时间点的累加；方向未选的一侧不显示。
 数值备两份：.v-full 完整（桌面）/ .v-short 紧凑（手机）。
 统一走 renderLegend：字号固定＝坐标轴刻度字号、按宽度自适应列数、
 宽度不够换行、留空在第一行、整体居中、内容完整不省略，绝不缩字号。 */
  const trafficItems = parts.map((p) => {
        const upT = p.up.reduce((a, v) => a + (Number(v) || 0), 0);
        const downT = p.down.reduce((a, v) => a + (Number(v) || 0), 0);
        const val = (n) => `<span class="v-full">${fmtBytes(n)}</span>` +
          `<span class="v-short">${fmtBytesShort(n)}</span>`;
        const u = dirs.up ? `<span class="pair up" style="--c:${p.color_up}">` +
          `<i class="sq" style="background:${p.color_up}"></i>` +
          `<b class="arw" style="color:${p.color_up}">↑</b>` +
          `<span class="lg-lb">上传</span><b class="lg-v">${val(upT)}</b></span>` : '';
        const d = dirs.down ? `<span class="pair down" style="--c:${p.color_down}">` +
          `<i class="sq" style="background:${p.color_down}"></i>` +
          `<b class="arw" style="color:${p.color_down}">↓</b>` +
          `<span class="lg-lb">下载</span><b class="lg-v">${val(downT)}</b></span>` : '';
        return `<span class="lg-item" title="${esc(p.name)}：↑ 上传 ${fmtBytes(upT)}　↓ 下载 ${fmtBytes(downT)}">` +
          `<b class="lg-name" title="${esc(p.name)}">${esc(p.name)}</b>${u}${d}</span>`;
      });
  if (parts.length && (dirs.up || dirs.down)) {
    renderLegend($('#trafficLegend'), trafficItems, '#trafficChart');
  } else {
    $('#trafficLegend').innerHTML = `<span>${S.pick.size ? '请选择方向' : noPickHint()}</span>`;
  }
}

/* ---------------- 横向拖动平移（顺滑版）----------------
 拖动过程中：零网络请求、零 canvas 重绘，只用 rAF + CSS transform 平移位图，
 GPU 合成跟手 60fps；两端带橡皮筋阻尼。
 松手后：按总位移一次性换算 offset 发「一次」请求，数据回来时清 transform
 并重绘（归位与新数据在同一帧提交，不闪跳）。
 可回看 30 个「当前时间范围」长度（后端 maxOffset = 30 × 桶数）。 */
function bindPan(which) {
  const cv = which === 'rate' ? $('#rateChart') : $('#trafficChart');
  const st = S[which];
  let drag = null, raf = 0, pendingX = 0;

  const xOf = (e) => (e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX);
  function pxPerBucket() {
    const g = cv._geom;
    const w = cv.getBoundingClientRect().width || 360;
    const plotW = g ? (g.w - g.pad.l - g.pad.r) : Math.max(120, w - 60);
    const n = g ? (g.type === 'lines' ? Math.max(1, g.n - 1) : (g.groups.length || 1)) : 10;
    return Math.max(6, plotW / n);
  }
  function applyX(px) {
    cv.style.transform = px ? 'translate3d(' + px.toFixed(1) + 'px,0,0)' : '';
  }
  /* 到边界后位移按 0.3 衰减，产生「拉不动」的阻尼手感 */
  function clampDx(dx, base) {
    const unit = pxPerBucket();
    const maxRight = (st.maxOffset - base) * unit;   // 还能回看多少像素
    const maxLeft = base * unit;                      // 还能往「新」走多少像素
    if (dx > maxRight) return maxRight + (dx - maxRight) * 0.3;
    if (dx < -maxLeft) return -maxLeft + (dx + maxLeft) * 0.3;
    return dx;
  }
  function start(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (!st.data || !st.maxOffset) return;           // 无数据 / 无可回看范围就不进入拖动
    hideTip();
    // 拖动画面保持干净：清掉之前悬停留下的竖线 / 圆点，仅在此刻重绘一次
    if (st._hover != null) { st._hover = null; renderChart(which); }
    cv.style.transition = '';
    drag = { x0: xOf(e), base: st.offset, dx: 0, moved: false };
    st._panning = true;
    cv.classList.add('panning');
    if (cv.setPointerCapture && e.pointerId != null) {
      try { cv.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
    }
  }
  function move(e) {
    if (!drag) return;
    const raw = xOf(e) - drag.x0;
    if (!drag.moved && Math.abs(raw) < 4) return;
    drag.moved = true;
    if (e.cancelable) e.preventDefault();
    drag.dx = raw;
    pendingX = clampDx(raw, drag.base);
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; applyX(pendingX); });
  }
  function end() {
    if (!drag) return;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    const d = drag; drag = null;
    st._panning = false;
    cv.classList.remove('panning');
    if (!d.moved) return;
    st._panEndAt = Date.now();          // 刚拖动过：忽略随后浏览器合成的 click
    const delta = Math.round(d.dx / pxPerBucket());   // 向右拖 = 看更早 = offset 增大
    const next = Math.max(0, Math.min(st.maxOffset || 0, d.base + delta));
    if (next === d.base) {
      // 没跨过一个桶：带过渡平滑弹回原位
      cv.style.transition = 'transform .18s ease-out';
      applyX(0);
      return;
    }
    st.offset = next;
    renderLatestBtn(which);        // 立即显示「回到最新」，不等请求
    saveState();
    loadChart(which);              // 一次请求；成功 / 失败都会清 transform 归位
  }
  cv.addEventListener('pointerdown', start);
  cv.addEventListener('pointermove', move);
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', end);
  $('#' + which + 'Latest').addEventListener('click', () => {
    st.offset = 0; saveState(); loadChart(which);
  });
}

function bindHover(which) {
  const cv = which === 'rate' ? $('#rateChart') : $('#trafficChart');
  let raf = 0, lastE = null;
  /* 悬停重绘合并到每帧一次：鼠标快速划过时不再逐事件全量重绘画布 */
  function flush() {
    raf = 0;
    const e = lastE;
    if (!e || S[which]._panning) return;
    const g = cv._geom; if (!g) return;
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left;
    let idx, n;
    if (g.type === 'lines') {
      n = g.n;
      idx = Math.round((x - g.pad.l) / (g.w - g.pad.l - g.pad.r) * (n - 1));
    } else { n = g.groups.length; idx = Math.floor((x - g.pad.l) / g.groupW); }
    if (x < g.pad.l || idx < 0 || idx >= n) { hideTip(); S[which]._hover = null; renderChart(which); return; }
    S[which]._hover = idx;
    renderChart(which);
    /* 菜单模板：一个下载器一行
 名称:(黑) ↑ 上传速度(上传线色) ↓ 下载速度(下载线色)
 白底上把线条色轻微压暗一点，保证黄色等亮色也读得清，仍是同一色系。 */
    const ink = (c) => `color-mix(in srgb, ${c} 78%, #0b1220)`;
    /* 流量统计在短窗口范围下用「时间段」标题，其余沿用 X 轴日期标签 */
    const titleOf = (g, i) => (g.tipTitles && g.tipTitles[i]) || g.labels[i];
    const row = (name, up, down) =>
      `<div class="tip-row"><span class="tip-name">${esc(name)}:</span>` +
      (up ? `<span class="tip-v" style="color:${ink(up.color)}">↑ ${up.text}</span>` : '') +
      (down ? `<span class="tip-v" style="color:${ink(down.color)}">↓ ${down.text}</span>` : '') +
      `</div>`;
    let html;
    if (g.type === 'lines') {
      const byName = new Map();
      g.lines.forEach((L) => {
        const k = L.name || L.label;
        if (!byName.has(k)) byName.set(k, {});
        byName.get(k)[L.dir] = L;
      });
      const val = (L) => L.values[idx] == null ? '—' : g.fmt(L.values[idx]);
      html = `<div class="t">${esc(g.labels[idx])}</div>` +
        [...byName.entries()].map(([name, d]) => row(name,
          d.up && { color: d.up.color, text: val(d.up) },
          d.down && { color: d.down.color, text: val(d.down) })).join('');
    } else {
      // 按选中下载器顺序完整列出，0 流量也显示（不再过滤 value>0）
      const gr = g.groups[idx];
      /* 流量统计点击 / 悬停弹出框改为「先合计、后单下载器明细」。
 合计行移最前，并加 .lead 由 CSS 把分隔线改到底部（与下方明细分隔）。 */
      /* 合计行的「上传 / 下载」内容改用 .u / .d 着色 —— 这两个
 类在 style.css 里就是 var(--up) / var(--down)，与页面最顶部四张
 周期卡片（.card-vals .v.up / .v.down）的上传下载文字颜色逐字一致；
 未选中的方向仍显示占位符，颜色一并套用，视觉更统一。 */
      html = `<div class="t">${esc(titleOf(g, idx))}</div>` +
        `<div class="tip-sum lead">合计 ` +
        `<b class="u">↑ ${g.dirs.up ? g.fmt(gr.up) : '—'}</b>　` +
        `<b class="d">↓ ${g.dirs.down ? g.fmt(gr.down) : '—'}</b></div>` +
        gr.upParts.map((u, i) => {
          const d = gr.downParts[i];
          return row(u.name,
            g.dirs.up && { color: u.color, text: g.fmt(u.value) },
            g.dirs.down && d && { color: d.color, text: g.fmt(d.value) });
        }).join('');
    }
    showTip(e, html);
  }
  cv.addEventListener('mousemove', (e) => {
    if (S[which]._panning) return;                 // 拖动时不触发悬停提示
    lastE = e;
    if (!raf) raf = requestAnimationFrame(flush);
  });
  cv.addEventListener('mouseleave', () => {
    if (S[which]._panning) return;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    lastE = null;
    hideTip(); S[which]._hover = null; renderChart(which);
  });
  /* 点击 / 手机点按也唤出同一个菜单；拖动结束后合成的 click 会被忽略 */
  cv.addEventListener('click', (e) => {
    if (S[which]._panning || (Date.now() - (S[which]._panEndAt || 0)) < 400) return;
    lastE = e;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    flush();
  });
}

/* ---------------- 下载器配置 ---------------- */
function autoColors() {
  const pal = (S.settings && S.settings.palette) || [['#F56C6C', '#409EFF']];
  // 与后端 next_palette_index / PT Nexus 一致 —— 按当前下载器数量
  // 顺序取下一组（index % len）。新增第 n 台正好拿到色板第 n 组，5 台以内
  // 自动分配区分度最高；不再「找第一组没被占用的色」，避免删除 / 重排 /
  // 手动改色后新下载器跳到不相邻的色组。
  const i = S.downloaders.length % pal.length;
  return { up: pal[i][0], down: pal[i][1] };
}
function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());
  if (!m) return [0, 0, 0];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map((v) =>
    Math.max(0, Math.min(255, Math.round(Number(v) || 0))).toString(16).padStart(2, '0')
  ).join('');
}
/* ---------------- 曲线颜色设置 ----------------
 唯一真值 = 隐藏的 <input type="color">（#fColorUp / #fColorDown），
 formData 直接读它。上传 / 下载两行里的「大写 HSV 代码框 + R/G/B
 数值框」与弹出调色板里的「HSV 三滑块 / RGB 三滑块 + 数值框」全部
 双向同步到它。界面展示的 HSV 代码（#RRGGBB）字母一律大写，数据库
 仍存小写 hex，不影响图表配色与统计口径。 */
let cpTarget = 'fColorUp';    // 调色板当前正在编辑的目标取色器 id
let cpMode = 'hsv';           // 'hsv' | 'rgb'

function normHex(v) {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(String(v || '').trim());
  return m ? '#' + m[1].toLowerCase() : null;
}
function clamp(v, lo, hi) {
  v = Math.round(Number(v));
  if (!isFinite(v)) v = lo;
  return Math.max(lo, Math.min(hi, v));
}
/* RGB(0~255) -> HSV(色调 0~360 / 饱和度 0~100 / 明度 0~100) */
function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d > 1e-9) {
    if (mx === r) h = ((g - b) / d) % 6;
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60; if (h < 0) h += 360;
  }
  return [Math.round(h), Math.round(mx === 0 ? 0 : d / mx * 100), Math.round(mx * 100)];
}
/* HSV -> RGB(0~255) */
function hsvToRgb(h, s, v) {
  h = ((Number(h) % 360) + 360) % 360;
  s = clamp(s, 0, 100) / 100; v = clamp(v, 0, 100) / 100;
  const c = v * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = v - c;
  let r = 0, g = 0, b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}
/* 把隐藏取色器的颜色回填到某一行的全部可见控件：色块背景、大写 HSV
 代码框、R/G/B 数值框。skip = 用户正在键盘输入的那个框，避免光标跳动。 */
function syncColorLine(id, skip) {
  const picker = $('#' + id);
  if (!picker) return;
  const hex = normHex(picker.value) || '#000000';
  const line = $('.cc-block[data-target="' + id + '"]');
  if (!line) return;
  const sw = line.querySelector('.cc-swatch');
  if (sw) { sw.style.background = hex; sw.title = hex.toUpperCase() + ' · 点击打开调色板'; }
  const hx = $('#' + id + 'Hex');
  if (hx && hx !== skip) hx.value = hex.toUpperCase();
  const rgb = hexToRgb(hex);
  ['r', 'g', 'b'].forEach((ch, i) => {
    const inp = line.querySelector('.cc-rgb[data-ch="' + ch + '"]');
    if (inp && inp !== skip) inp.value = rgb[i];
  });
}
/* 自动分配 / 编辑回填 / 清空表单统一入口。 */
function setColorInputs(up, down) {
  [['#fColorUp', up], ['#fColorDown', down]].forEach(([sel, c]) => {
    $(sel).value = normHex(c) || '#000000';
    syncColorLine(sel.slice(1));
  });
  if (!$('#colorPickerModal').hidden) syncColorPanel();
}
/* 调色板左侧：结果色块 + 当前模式的结果代码（HSV 大写 hex / RGB(...)）。 */
function setCpResult(hex, rgb) {
  const prev = $('#cpPreview');
  if (prev) prev.style.background = hex;
  const code = $('#cpCode');
  if (code) {
    // RGB(...) 代码比 #RRGGBB 长，RGB 模式适当调小字号（CSS .is-rgb）
    code.classList.toggle('is-rgb', cpMode === 'rgb');
    code.textContent = cpMode === 'hsv'
      ? hex.toUpperCase() : 'RGB(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ')';
  }
}
/* 按当前模式把真值颜色回填到三条滑块 + 数值框 + 结果区。 */
function syncColorPanel() {
  const picker = $('#' + cpTarget);
  if (!picker) return;
  const hex = normHex(picker.value) || '#000000';
  const rgb = hexToRgb(hex), hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]);
  const vals = cpMode === 'hsv'
    ? { h: hsv[0], s: hsv[1], v: hsv[2] }
    : { r: rgb[0], g: rgb[1], b: rgb[2] };
  const box = $('.cp-sliders[data-cm="' + cpMode + '"]');
  if (box) Object.keys(vals).forEach((ch) => {
    const sl = box.querySelector('.cp-range[data-ch="' + ch + '"]');
    const nm = box.querySelector('.cp-num[data-ch="' + ch + '"]');
    if (sl) sl.value = vals[ch];
    if (nm) nm.value = vals[ch];
  });
  setCpResult(hex, rgb);
}
/* 从当前模式三条滑块算出颜色，写回隐藏取色器并同步全行可见控件。 */
function applyPanel() {
  const box = $('.cp-sliders[data-cm="' + cpMode + '"]');
  if (!box) return;
  const read = (ch) => box.querySelector('.cp-range[data-ch="' + ch + '"]').value;
  const rgb = cpMode === 'hsv'
    ? hsvToRgb(read('h'), read('s'), read('v'))
    : [read('r'), read('g'), read('b')].map((v) => clamp(v, 0, 255));
  const hex = rgbToHex(rgb[0], rgb[1], rgb[2]);
  const picker = $('#' + cpTarget);
  if (picker) picker.value = hex;
  syncColorLine(cpTarget);
  setCpResult(hex, rgb);
}
function openColorPicker(id) {
  cpTarget = id;
  const modal = $('#colorPickerModal');
  modal.hidden = false;
  $('#cpTitle').textContent = (id === 'fColorUp' ? '上传' : '下载') + '曲线颜色 · 自定义';
  syncColorPanel();
}
function closeColorPicker() { $('#colorPickerModal').hidden = true; }
function switchCpMode(mode) {
  cpMode = mode;
  $$('#colorPickerModal .cm-tab').forEach((t) => {
    const on = t.dataset.cm === mode;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', String(on));
  });
  $$('#colorPickerModal .cp-sliders').forEach((p) => { p.hidden = p.dataset.cm !== mode; });
  syncColorPanel();
}
function formData() {
  return {
    name: $('#fName').value.trim(), type: $('#fType').value, url: $('#fUrl').value.trim(),
    username: $('#fUser').value.trim(), password: $('#fPass').value,
    enabled: $('#fEnabled').checked,
    color_up: $('#fColorUp').value, color_down: $('#fColorDown').value,
  };
}
function resetForm() {
  $('#fId').value = ''; $('#dlForm').reset();
  $('#fEnabled').checked = true; $('#formTitle').textContent = '添加下载器';
  $('#formMsg').textContent = '';
  const c = autoColors(); setColorInputs(c.up, c.down);
}
function fillForm(d) {
  $('#fId').value = d.id; $('#fName').value = d.name; $('#fType').value = d.type;
  $('#fUrl').value = d.url; $('#fUser').value = d.username || ''; $('#fPass').value = '';
  $('#fEnabled').checked = !!d.enabled;
  setColorInputs(d.color_up || '#e05252', d.color_down || '#43dbbd');
  $('#formTitle').textContent = '编辑：' + d.name;
  $('#formMsg').textContent = '密码留空表示保持原值';
}
function renderConfigTable() {
  const list = S.downloaders;
  $('#configTable tbody').innerHTML = list.map((d, idx) =>
    `<tr><td data-label="名称">${esc(d.name)}</td>` +
    `<td data-label="类型">${d.type === 'qb' ? 'qBittorrent' : 'Transmission'}</td>` +
    `<td data-label="地址" title="${esc(d.url)}">${esc(d.url)}</td>` +
    /* 曲线颜色列改成「上传 色块，下载 色块」，与下方「新增下载器」表单
 「文字在前、调色板在后」的顺序一致；仍不显示十六进制代码，完整色值放
 title 里悬停可查，列宽收窄留给顺序 / 操作按钮。 */
    `<td data-label="曲线颜色" title="上传 ${esc(String(d.color_up).toUpperCase())}　下载 ${esc(String(d.color_down).toUpperCase())}">` +
    `<span class="swatch"><span>上传</span><i style="background:${esc(d.color_up)}"></i></span>` +
    `<span class="swatch"><span>下载</span><i style="background:${esc(d.color_down)}"></i></span></td>` +
    `<td data-label="启用">${d.enabled ? '是' : '否'}</td>` +
    `<td data-label="顺序"><div class="order-btns">` +
    `<button class="btn xs" data-act="up" data-id="${d.id}" ${idx === 0 ? 'disabled' : ''} title="上移">↑</button>` +
    `<button class="btn xs" data-act="down" data-id="${d.id}" ${idx === list.length - 1 ? 'disabled' : ''} title="下移">↓</button>` +
    `</div></td>` +
    `<td data-label="操作"><div class="row-btns">` +
    `<button class="btn sm" data-act="edit" data-id="${d.id}">编辑</button> ` +
    `<button class="btn sm" data-act="toggle" data-id="${d.id}">${d.enabled ? '停用' : '启用'}</button> ` +
    `<button class="btn sm" data-act="test" data-id="${d.id}">测试</button> ` +
    `<button class="btn sm danger" data-act="del" data-id="${d.id}">删除</button></div></td></tr>`).join('')
    || '<tr><td colspan="7" class="hint">暂无下载器</td></tr>';
}
async function moveDownloader(id, delta) {
  const list = S.downloaders.slice();
  const i = list.findIndex((d) => d.id === id), j = i + delta;
  if (i < 0 || j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  try {
    await api('/api/downloaders/reorder', jsonBody('POST', { ids: list.map((d) => d.id) }));
    await loadAll();
  } catch (err) { alert('排序失败：' + err.message); }
}

/* ---------------- 设置多页面 ---------------- */
function switchSettingsPage(page) {
  S.settingsPage = page;
  $$('#settingsNav .st-nav').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  $$('.st-page').forEach((s) => { s.hidden = s.dataset.page !== page; });
  // 弹窗高度固定、标题行与分页行冻结，切换分页只把右栏滚回顶部即可，
  // 页面顶端位置不会因内容长短而上下跳动。
  const pages = $('.settings-pages');
  if (pages) pages.scrollTop = 0;
}
function renderAbout() {
  const o = S.overview;
  if (!o) {
    const lead0 = $('#aboutLead');
    if (lead0) { lead0.innerHTML = ''; lead0.hidden = false; }
    $('#aboutInfo').innerHTML = '<p class="hint">暂无数据，请稍后刷新。</p>';
    return;
  }
  const s = S.settings || {};
  const labelOf = (opts, v, fb) => ((opts || [])
    .filter((x) => Number(x.value) === Number(v)).map((x) => x.label)[0]) || fb;
  const live = labelOf(s.live_span_options, s.live_span, '5 分钟');
  const rate = labelOf(s.poll_interval_options, s.poll_interval, '5 秒');
  const traffic = labelOf(s.traffic_interval_options, s.traffic_interval, '1 分钟');
  /* 手机端把前两项放固定 2 列网格，让第二行「两种采样间隔」
 与第三行「两种采样轮次」上下对应。这个分组原本只该给手机端用，
 却被同步到了桌面端；桌面端（≥901px）不再强制固定前两行，把 9 张卡片
 按正常顺序放进同一个 auto-fit 网格、按宽度自动换行、卡片等宽。 */
  const lead = [
    ['在线下载器', `${o.total.online} / ${o.total.count}`],
    ['「实时」窗口', live],
    ['实时速率采样间隔', rate],
    ['流量统计采样间隔', traffic],
  ];
  const rows = [
    ['实时速率采样轮次', `${o.collector.ticks} 轮`],
    ['流量统计采样轮次', `${o.collector.traffic_ticks || 0} 轮`],
    ['时区', `UTC+${S.tz}`],
    ['最后更新', fmtClock(o.server_time)],
    ['采集状态', o.collector.last_error ? esc(String(o.collector.last_error).slice(0, 24)) : '正常'],
  ];
  const card = ([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`;
  const leadEl = $('#aboutLead');
  if (leadEl) {
    /* 桌面端按「正常顺序 + 宽度」排版 —— 9 张卡片全部落进 #aboutInfo
 的同一个 auto-fit 网格（minmax(150px,1fr)），前两块不再被固定成 2 列
 半屏宽；#aboutLead 隐藏且清空，避免空容器留下 margin / gap。
 手机 / 平板（<901px）保持 的两容器分组， */
    const desktop = !!(window.matchMedia && window.matchMedia(FIT_MQ).matches);
    if (desktop) {
      leadEl.hidden = true;
      leadEl.innerHTML = '';
      $('#aboutInfo').innerHTML = lead.concat(rows).map(card).join('');
    } else {
      leadEl.hidden = false;
      leadEl.innerHTML = lead.map(card).join('');
      $('#aboutInfo').innerHTML = rows.map(card).join('');
    }
  } else {
    // 兼容旧版缓存 HTML（无 #aboutLead）：九项退回单容器，信息不丢
    $('#aboutInfo').innerHTML = lead.concat(rows).map(card).join('');
  }
}
/* 采样间隔分三组 chip —— 实时速率 / 流量统计 / 实时窗口，
 前两组分别对应后端两条独立采集线程，各自独立保存、独立生效。 */
function renderCollect() {
  const st = S.settings || {}, d = S.collectDraft;
  const piOpts = st.poll_interval_options || [{ value: 5, label: '5 秒' }];
  const tiOpts = st.traffic_interval_options || [{ value: 60, label: '1 分钟' }];
  const lsOpts = st.live_span_options || [{ value: 300, label: '5 分钟' }];
  const chip = (o, k, cur) =>
    `<button type="button" class="chip ${Number(o.value) === Number(cur) ? 'active' : ''}" ` +
    `data-k="${k}" data-v="${o.value}">${esc(o.label)}</button>`;
  $('#pollOptions').innerHTML = piOpts.map((o) => chip(o, 'pi', d.pi)).join('');
  $('#trafficPollOptions').innerHTML = tiOpts.map((o) => chip(o, 'ti', d.ti)).join('');
  $('#liveOptions').innerHTML = lsOpts.map((o) => chip(o, 'ls', d.ls)).join('');
  const labelOf = (opts, v, fb) =>
    opts.filter((o) => Number(o.value) === Number(v)).map((o) => o.label)[0] || fb;
  const curLive = labelOf(lsOpts, st.live_span, '5 分钟');
  const curRate = labelOf(piOpts, st.poll_interval, '5 秒');
  const curTraffic = labelOf(tiOpts, st.traffic_interval, '1 分钟');
  $('#collectCurrent').textContent =
    `当前生效：实时速率每 ${curRate}采样一次，流量统计每 ${curTraffic}采样一次，「实时」窗口 ${curLive}。`;
}
function updateInstallHint() {
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  const el = $('#installHint');
  if (!el) return;
  el.textContent = standalone ? '当前已在独立窗口中运行（应用已安装）。'
    : (S.installReady ? '检测到可安装，点击上方按钮添加到桌面。'
      : '未检测到安装条件：需通过 HTTPS 域名访问，并使用支持 PWA 的浏览器（如安卓 Chrome）。');
}
function openSettings(page) {
  const p = page || 'downloaders';
  switchSettingsPage(p);
  $('#settingsModal').hidden = false;
  if (p === 'downloaders') { loadDownloaders(); resetForm(); }
  if (p === 'collect') {
    S.collectDraft = { pi: (S.settings && S.settings.poll_interval) || 5,
      ti: (S.settings && S.settings.traffic_interval) || 60,
      ls: (S.settings && S.settings.live_span) || 300 };
    renderCollect(); $('#collectMsg').textContent = '';
  }
  if (p === 'account') {
    ['#acOld', '#acUser', '#acPass', '#acPass2'].forEach((s) => { $(s).value = ''; });
    $('#accountMsg').textContent = '';
  }
  if (p === 'appearance') { applyTheme(); updateInstallHint(); }
  if (p === 'about') renderAbout();
}

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  $('#btnAuthTheme').addEventListener('click', toggleTheme);
  $('#btnSettings').addEventListener('click', () => openSettings());
  $('#btnCloseSettings').addEventListener('click', () => { $('#settingsModal').hidden = true; closeAllDropdowns(); });
  /* 详情类弹窗（单台 / 汇总）正中间显示，遮罩的上下空白区域点击一律忽略，
 不会被误关回主界面；关闭只能用右上角胶囊按钮或 Esc。 */
  $('#btnCloseDetail').addEventListener('click', closeDetail);
  $('#btnCloseSummary').addEventListener('click', closeDetail);
  /* 测试结果小窗口 —— 点遮罩上下空白一律忽略，关闭只能用胶囊按钮或 Esc */
  $('#btnCloseTest').addEventListener('click', closeTest);
  $('#testModal').addEventListener('click', (e) => {
    if (e.target === $('#testModal')) e.stopPropagation();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#testModal').hidden) closeTest();
  });
  ['#detailModal', '#summaryModal'].forEach((sel) => {
    $(sel).addEventListener('click', (e) => {
      if (e.target === $(sel)) e.stopPropagation();   // 点在遮罩空白：忽略
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' &&
        (!$('#detailModal').hidden || !$('#summaryModal').hidden)) closeDetail();
  });
  /* 点击设置弹窗范围外（遮罩）一律忽略，不再误关回主界面；
 关闭只能用右上角胶囊按钮。 */
  $('#settingsModal').addEventListener('click', (e) => {
    if (e.target.id === 'settingsModal') e.stopPropagation();
  });
  $('#settingsNav').addEventListener('click', (e) => {
    const b = e.target.closest('.st-nav');
    if (b) openSettings(b.dataset.page);
  });
  document.addEventListener('click', () => closeAllDropdowns());

  /* 调色板弹窗：遮罩空白点击忽略，关闭只能用胶囊按钮 / 完成 / Esc。 */
  $('#btnCloseColorPicker').addEventListener('click', closeColorPicker);
  $('#btnColorPickerDone').addEventListener('click', closeColorPicker);
  $('#colorPickerModal').addEventListener('click', (e) => {
    if (e.target.id === 'colorPickerModal') e.stopPropagation();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#colorPickerModal').hidden) closeColorPicker();
  });

  // 顶部 4 张卡：右上角「历史数据」清单（纯展示、可无限下滑）
  bindSummaryCards();

  // 登录
  $('#loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('#loginMsg').textContent = '';
    try {
      const j = await api('/api/auth/login', jsonBody('POST', {
        username: $('#loginUser').value.trim(), password: $('#loginPass').value,
      }));
      S.token = j.token; localStorage.setItem('ttm_token', j.token);
      S.user = j.username; localStorage.setItem('ttm_user', j.username);
      S.mustChange = j.must_change;
      $('#loginPass').value = '';
      if (j.must_change) showSetup(); else enterApp();
    } catch (err) { $('#loginMsg').textContent = err.message; }
  });
  // 首次强制改账号密码
  $('#setupForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = $('#setupUser').value.trim(), p = $('#setupPass').value, p2 = $('#setupPass2').value;
    if (!u || !p) { $('#setupMsg').textContent = '请填写完整'; return; }
    if (p !== p2) { $('#setupMsg').textContent = '两次输入的密码不一致'; return; }
    if (u.toLowerCase() === 'admin') { $('#setupMsg').textContent = '新账号不能仍为 admin'; return; }
    if (p === 'admin' || p.length < 6) { $('#setupMsg').textContent = '新密码至少 6 位且不能是 admin'; return; }
    try {
      const j = await api('/api/auth/setup', jsonBody('POST', { username: u, password: p }));
      S.user = j.username; localStorage.setItem('ttm_user', j.username); enterApp();
    } catch (err) { $('#setupMsg').textContent = err.message; }
  });
  $('#btnSetupLogout').addEventListener('click', logout);

  // 设置 → 账户
  $('#btnLogout').addEventListener('click', logout);
  $('#accountForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const p = $('#acPass').value, p2 = $('#acPass2').value;
    if (p !== p2) { $('#accountMsg').textContent = '两次输入的密码不一致'; return; }
    if (p && p.length < 6) { $('#accountMsg').textContent = '新密码至少 6 位'; return; }
    try {
      const j = await api('/api/auth/change', jsonBody('POST', {
        old_password: $('#acOld').value, username: $('#acUser').value.trim(), password: p,
      }));
      S.user = j.username; localStorage.setItem('ttm_user', j.username);
      ['#acOld', '#acPass', '#acPass2'].forEach((s) => { $(s).value = ''; });
      $('#accountMsg').textContent = '已保存';
    } catch (err) { $('#accountMsg').textContent = err.message; }
  });

  // 设置 → 外观
  $('#btnThemeDark').addEventListener('click', () => setTheme('dark'));
  $('#btnThemeLight').addEventListener('click', () => setTheme('light'));

  // 设置 → 采集
  ['#pollOptions', '#trafficPollOptions', '#liveOptions'].forEach((sel) => {
    $(sel).addEventListener('click', (e) => {
      const b = e.target.closest('button.chip');
      if (!b) return;
      S.collectDraft[b.dataset.k] = Number(b.dataset.v);
      renderCollect();
    });
  });
  $('#btnSaveCollect').addEventListener('click', async (e) => {
    const b = e.currentTarget, d = S.collectDraft;
    b.disabled = true; b.textContent = '保存中…';
    try {
      const j = await api('/api/settings', jsonBody('POST', {
        poll_interval: d.pi, traffic_interval: d.ti, live_span: d.ls,
      }));
      if (S.settings) {
        S.settings.poll_interval = j.poll_interval;
        S.settings.traffic_interval = j.traffic_interval;
        S.settings.live_span = j.live_span;
      }
      $('#collectMsg').textContent = '已保存，立即生效';
      renderCollect();
      ['rate', 'traffic'].forEach(renderRangeDropdown);
      await Promise.all([loadOverview(), loadChart('rate'), loadChart('traffic')]);
    } catch (err) { $('#collectMsg').textContent = '保存失败：' + err.message; }
    b.disabled = false; b.textContent = '保存设置';
  });

  // 设置 → 关于
  $('#btnRefresh').addEventListener('click', async (e) => {
    const b = e.currentTarget;
    b.disabled = true; b.textContent = '刷新中…';
    await loadAll(); renderAbout();
    b.disabled = false; b.textContent = '立即刷新数据';
  });

  // 设置 → 下载器：一键重新分配颜色
  $('#btnRecolor').addEventListener('click', async (e) => {
    const b = e.currentTarget, msg = $('#recolorMsg');
    b.disabled = true; b.textContent = '分配中…';
    try {
      const j = await api('/api/downloaders/recolor', jsonBody('POST', {}));
      msg.textContent = `已为 ${j.count} 个下载器重新分配颜色（第 ${Number(j.shift) + 1} 套配色），图表与卡片已同步`;
      await loadAll();
    } catch (err) { msg.textContent = '分配失败：' + err.message; }
    b.disabled = false; b.textContent = '🎨 一键重新分配颜色';
  });

  // 设置 → 下载器：表单
  $('#btnReset').addEventListener('click', resetForm);
  /* 曲线颜色设置：两行色块弹调色板；HSV 代码框与 R/G/B 数值框既能
 返显自动分配 / 调色结果，也支持键盘直接输入，全部双向同步到隐藏取色器。 */
  $('#btnAutoColor').addEventListener('click', () => { const c = autoColors(); setColorInputs(c.up, c.down); });
  $$('.cc-swatch').forEach((sw) =>
    sw.addEventListener('click', () => openColorPicker(sw.dataset.target)));
  $$('.cc-block').forEach((line) => {
    const id = line.dataset.target, picker = $('#' + id), hx = $('#' + id + 'Hex');
    if (hx) hx.addEventListener('change', () => {
      const v = normHex(hx.value);
      if (v) {
        picker.value = v; syncColorLine(id, hx); hx.value = v.toUpperCase();
        if (!$('#colorPickerModal').hidden && cpTarget === id) syncColorPanel();
      } else hx.value = (normHex(picker.value) || '#000000').toUpperCase();
    });
    line.querySelectorAll('.cc-rgb').forEach((inp) => {
      inp.addEventListener('input', () => {
        const read = (ch) => line.querySelector('.cc-rgb[data-ch="' + ch + '"]').value;
        const rgb = ['r', 'g', 'b'].map((ch) => clamp(read(ch), 0, 255));
        picker.value = rgbToHex(rgb[0], rgb[1], rgb[2]);
        syncColorLine(id, inp);      // 不覆盖正在输入的这个框
        if (!$('#colorPickerModal').hidden && cpTarget === id) syncColorPanel();
      });
      inp.addEventListener('change', () => {
        inp.value = clamp(inp.value, 0, 255);
        syncColorLine(id);           // 失焦后统一夹取回填
      });
    });
  });
  /* 这些数值框都在 <form> 里：回车默认会提交表单保存下载器，改成失焦生效。 */
  $$('#dlForm .cc-hex, #dlForm .cc-rgb').forEach((inp) =>
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
    }));
  /* 调色板弹窗：顶部胶囊切模式；三条滑块与右侧数值框实时互相同步。 */
  $$('#colorPickerModal .cm-tab').forEach((tab) =>
    tab.addEventListener('click', () => switchCpMode(tab.dataset.cm)));
  $$('#colorPickerModal .cp-sliders').forEach((box) => {
    box.addEventListener('input', (e) => {
      const t = e.target;
      if (t.classList.contains('cp-range')) {
        const nm = box.querySelector('.cp-num[data-ch="' + t.dataset.ch + '"]');
        if (nm) nm.value = t.value;
      } else if (t.classList.contains('cp-num')) {
        const sl = box.querySelector('.cp-range[data-ch="' + t.dataset.ch + '"]');
        if (sl) sl.value = clamp(t.value, 0, Number(t.max) || 255);
      }
      applyPanel();
    });
    box.addEventListener('change', (e) => {
      const t = e.target;
      if (t.classList.contains('cp-num')) {
        t.value = clamp(t.value, 0, Number(t.max) || 255);
        const sl = box.querySelector('.cp-range[data-ch="' + t.dataset.ch + '"]');
        if (sl) sl.value = t.value;
        applyPanel();
      }
    });
  });
  /* 新增 / 编辑下载器表单里的「测试连接」，以及配置表已保存下载器
 的「测试」，结果一律只在独立结果窗口（openTestResult / testModal）展示，
 不再往页面右下角（#formMsg）写任何文本。按钮保留 loading 态与 12 秒兜底
 提示（只更新按钮文字），成功 / 失败都有明确可见反馈。 */
  $('#btnTest').addEventListener('click', async () => {
    const id = $('#fId').value;
    const url = id ? `/api/downloaders/${id}/test` : '/api/downloaders/test';
    const d = { name: $('#fName').value.trim() || '（未命名下载器）',
      type: $('#fType').value, url: $('#fUrl').value.trim() };
    const btn = $('#btnTest');
    btn.disabled = true; btn.textContent = '测试中…';
    // 真机地址不可达时避免「看起来卡住」：12 秒兜底只更新按钮状态（不打断请求）
    const slowTip = setTimeout(() => {
      if (btn.disabled) btn.textContent = '仍连接中…';
    }, 12000);
    try {
      const j = await api(url, jsonBody('POST', formData()));
      openTestResult(d, true, j, '');
    } catch (err) {
      openTestResult(d, false, null, err.message);
    } finally {
      clearTimeout(slowTip);
      btn.disabled = false; btn.textContent = '测试连接';
    }
  });
  $('#dlForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = $('#fId').value, data = formData();
    if (!data.url) { $('#formMsg').textContent = '请填写地址'; return; }
    try {
      await api(id ? `/api/downloaders/${id}` : '/api/downloaders', jsonBody(id ? 'PUT' : 'POST', data));
      await loadAll(); resetForm();
      $('#formMsg').textContent = '已保存，采集器下一轮自动生效';
    } catch (err) { $('#formMsg').textContent = '保存失败：' + err.message; }
  });
  $('#configTable').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-act]');
    if (!b || b.disabled) return;
    const id = Number(b.dataset.id), d = S.downloaders.find((x) => x.id === id);
    if (!d) return;
    const act = b.dataset.act;
    if (act === 'up' || act === 'down') { moveDownloader(id, act === 'up' ? -1 : 1); return; }
    if (act === 'edit') { fillForm(d); return; }
    if (act === 'del') {
      if (!confirm(`删除「${d.name}」？该下载器的所有历史流量记录也会一并删除。`)) return;
      try { await api(`/api/downloaders/${id}`, { method: 'DELETE' }); await loadAll(); resetForm(); }
      catch (err) { alert('删除失败：' + err.message); }
      return;
    }
    if (act === 'toggle') {
      try {
        await api(`/api/downloaders/${id}`, jsonBody('PUT', { ...d, enabled: !d.enabled }));
        await loadAll();
      } catch (err) { alert('操作失败：' + err.message); }
      return;
    }
    if (act === 'test') {
      // 结果只在弹出的测试窗口展示，删除页面右下角文本
      b.disabled = true; b.textContent = '测试中';
      try {
        const j = await api(`/api/downloaders/${id}/test`, jsonBody('POST', {}));
        openTestResult(d, true, j, '');
      } catch (err) {
        openTestResult(d, false, null, err.message);
      }
      b.disabled = false; b.textContent = '测试';
    }
  });

  /* 下载器卡片：右上角胶囊开关切换「是否加入图表」，单击卡片其余区域
 打开详情弹窗（汇总卡打开「全部下载器汇总详情」）。两张图共用同一选择状态。 */
  $('#dlStrip').addEventListener('click', (e) => {
    const sw = e.target.closest('.dl-switch');
    if (sw) {
      e.stopPropagation();
      const chip = sw.closest('.dl-chip');
      if (!chip) return;
      const v = chip.dataset.v;
      if (S.pick.has(v)) S.pick.delete(v); else S.pick.add(v);
      saveState();
      renderDownloaders();
      renderChart('rate'); renderChart('traffic');
      return;
    }
    const chip = e.target.closest('.dl-chip');
    if (!chip) return;
    if (chip.dataset.v === 'all') { openSummary(); return; }
    openDetail(Number(chip.dataset.v));
  });

  ['rate', 'traffic'].forEach((w) => {
    bindRangeDropdown(w); bindDropdowns(w); bindHover(w); bindPan(w);
  });
  let rtimer;
  window.addEventListener('resize', () => {
    clearTimeout(rtimer);
    rtimer = setTimeout(() => {
      $$('.dd-menu:not([hidden])').forEach(keepMenuInViewport);
      if (S.logged) { renderChart('rate'); renderChart('traffic'); }
    }, 150);
  });
}

/* ---------------- PWA ---------------- */
function initPWA() {
  const installBtn = $('#btnInstall'), bar = $('#offlineBar');
  let deferredPrompt = null;
  if ('serviceWorker' in navigator) {
    const hadController = !!navigator.serviceWorker.controller;
    let refreshing = false;
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .catch((e) => console.warn('Service Worker 注册失败：', e));
    });
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (hadController && !refreshing) { refreshing = true; window.location.reload(); }
    });
  }
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); deferredPrompt = e;
    S.installReady = true; installBtn.hidden = false; updateInstallHint();
  });
  installBtn.addEventListener('click', async () => {
    if (!deferredPrompt) return;
    installBtn.hidden = true;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null; S.installReady = false; updateInstallHint();
  });
  window.addEventListener('appinstalled', () => {
    installBtn.hidden = true; S.installReady = false; updateInstallHint();
  });
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (standalone) {
    installBtn.hidden = true;
  }
  /* 手机端默认竖屏。manifest 的 orientation:"portrait" 已经让 PWA 以
 竖屏启动 / 不随系统自动横屏；在已安装的 standalone 模式里再静默尝试锁一次，
 兜住部分浏览器旋转设备后仍会横过来的情况。普通浏览器标签页不支持锁方向，
 抛错或 Promise reject 一律忽略，不影响任何功能。 */
  if (standalone && screen.orientation && typeof screen.orientation.lock === 'function') {
    try {
      const p = screen.orientation.lock('portrait');
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch (_) { /* 忽略：浏览器不支持或当前不在全屏 */ }
  }
  const sync = () => { bar.hidden = navigator.onLine; };
  window.addEventListener('online', () => { sync(); if (S.logged) loadAll(); });
  window.addEventListener('offline', sync);
  sync();
}

boot();
