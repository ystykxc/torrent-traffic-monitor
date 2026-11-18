/* 下载器流量统计 - 前端主逻辑（v1.0.32）
 *
 * 控件状态持久化 / 历史数据清单 / 下载器卡片开关 / 时间范围单选下拉 /
 * 横向拖动平移 / 流量堆叠柱状图。实时速率卡片、双主题、设置弹窗、
 * 调色板、SSE 全部删除；页面固定浅色、手机端紧凑一页展示。
 * v1.0.4：修复单台下载器卡片开关失效（改用「隐藏集合」按每台开关显隐
 * 图表分段）；桌面 / 手机统一按可用高度分配绘图区，底部留白按下载器
 * 小卡片高度计算（桌面 2 张、手机 1 张）。
 * v1.0.5 / v1.0.6：仅后端变更（首次安装默认开启通知、通知正文改为带边框的
 * 纯文本表格、上传下载改用 🔴 / 🟢 区分），前端页面无功能改动。
 * v1.0.28：仅后端通知排版调整（24格段间横线、标题下等长横线+无表头、🟢↑/🔴↓），
 * 前端页面无功能改动。
 * v1.0.29：仅后端通知排版调整（删除标题下的横线），前端页面无功能改动。
 * v1.0.30：仅后端通知排版调整（合计行首列居中），前端页面无功能改动。
 * v1.0.31：仅后端通知排版调整（合计居中填充空格改 NBSP），前端页面无功能改动。
 * v1.0.32：仅后端通知排版调整（合计行再右偏 2 格对齐微信表头），前端无功能改动。
 */
'use strict';

/* MoviePilot 插件运行时由 page() 注入：数据端点 base 与宿主 API_TOKEN。
 独立部署版是同源 /api 直连；插件版全部收敛到单一 /data 端点。 */
const TTM = window.TTM_CFG || { base: '/api/v1/plugin/TorrentTrafficMonitor/data', apikey: '' };

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

// 流量统计卡片的时间范围（实时速率卡片已删除，不再有「实时」档）。
const RANGE_ORDER = ['1h', '6h', '12h', '24h', 'yesterday',
  'week', 'lastweek', 'month', 'lastmonth', 'year', 'all'];
const RANGE_LABELS = {
  '1h': '1小时', '6h': '6小时', '12h': '12小时',
  '24h': '今日', yesterday: '昨日', week: '本周', lastweek: '上周',
  month: '本月', lastmonth: '上月', year: '本年', all: '全部',
};
// 自然周期里「按完整日 / 月分桶」的范围，流量图弹出菜单标题保持日期标签。
const NATURAL_RANGES = ['week', 'lastweek', 'month', 'lastmonth', 'year', 'all'];
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
  theme: 'light',   // 固定浅色主题
  logged: false,
  tz: 8, overview: null, statusLine: '',
  // v1.0.4：图表显隐由「隐藏集合」（黑名单）决定。默认空 = 全部下载器
  // 都参与图表；单台卡片开关关闭时把该下载器 id 加入集合。这样新接入的
  // 下载器默认展示、用户主动关闭的状态也能持久化，彻底修复 v1.0.3 把
  // 'all' 恒置选中导致单台开关失效的问题。
  hidden: new Set(),
  periods: null,                                  // /api/periods 返回的卡片当前周期数据
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
  return adapt(dir === 'up' ? '#fb923c' : '#38bdf8');
}

/* ---------------- 展示状态持久化（需求：下次进入与上次退出一致） ---------------- */
function loadState() {
  try {
    const h = JSON.parse(localStorage.getItem('ttm_hidden'));
    if (Array.isArray(h)) {
      S.hidden = new Set(h.filter((v) => /^\d+$/.test(String(v))).map(String));
    }
  } catch (e) { /* 损坏的值忽略，用默认（全部展示） */ }
  // 历史周期清单不再记忆选中项（已无单选改卡片功能），故无 ttm_period 状态
  const r = localStorage.getItem('ttm_traffic_range');
  if (r && RANGE_ORDER.indexOf(r) >= 0) S.traffic.range = r;
  const o = Number(localStorage.getItem('ttm_traffic_offset'));
  if (Number.isFinite(o) && o > 0) S.traffic.offset = Math.floor(o);
  try {
    const d = JSON.parse(localStorage.getItem('ttm_traffic_dirs'));
    if (Array.isArray(d) && d.length) {
      S.traffic.dirs = new Set(d.filter((x) => x === 'up' || x === 'down'));
    }
  } catch (e) { /* 忽略 */ }
}
function saveState() {
  try {
    localStorage.setItem('ttm_hidden', JSON.stringify(Array.from(S.hidden)));
    localStorage.setItem('ttm_traffic_range', S.traffic.range);
    localStorage.setItem('ttm_traffic_dirs', JSON.stringify(Array.from(S.traffic.dirs)));
    localStorage.setItem('ttm_traffic_offset', String(S.traffic.offset || 0));
  } catch (e) { /* 隐私模式下 localStorage 可能不可写 */ }
}

/* ---------------- HTTP ----------------
 MoviePilot 插件把原 /api/xxx 全部收敛到单一 /data 端点：
   GET <base>?action=<原路径映射>&args=<JSON>&apikey=<token>
 原路径里的 query 与 opts.body 合并进 args；非 GET 方法用 args._method 传递。
 这样图表、总览、统计、卡片等既有调用代码一处不改，天然适配插件宿主。 */
function jsonBody(method, data) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) };
}
function mapPath(path) {
  let raw = String(path || '');
  const qi = raw.indexOf('?');
  let qs = '';
  if (qi >= 0) { qs = raw.slice(qi + 1); raw = raw.slice(0, qi); }
  const seg = raw.replace(/^\/api\//, '').replace(/^\/+/, '').replace(/\/+$/, '');
  const args = {};
  if (qs) new URLSearchParams(qs).forEach((v, k) => { args[k] = v; });
  let action = seg, m;
  if ((m = seg.match(/^downloaders\/(\d+)\/detail$/))) {
    action = 'downloaders/detail'; args.did = Number(m[1]);
  } else if (seg === 'downloaders/summary/detail') {
    action = 'downloaders/summary';
  } else if ((m = seg.match(/^downloaders\/(\d+)\/test$/))) {
    action = 'downloaders/test'; args.did = Number(m[1]);
  } else if ((m = seg.match(/^downloaders\/(\d+)$/))) {
    action = 'downloaders/config'; args.id = Number(m[1]);
  }
  return { action, args };
}
async function api(path, opts) {
  const { action, args } = mapPath(path);
  const method = (opts && opts.method) || 'GET';
  if (opts && opts.body) {
    try { Object.assign(args, JSON.parse(opts.body)); } catch (e) { /* 忽略 */ }
  }
  if (String(method).toUpperCase() !== 'GET') args._method = String(method).toUpperCase();
  const url = TTM.base + '?action=' + encodeURIComponent(action) +
    '&args=' + encodeURIComponent(JSON.stringify(args)) +
    '&apikey=' + encodeURIComponent(TTM.apikey || '');
  let r;
  try { r = await fetch(url, { cache: 'no-store' }); }
  catch (e) { throw Object.assign(new Error('网络不可用：' + e.message), { network: true }); }
  let j;
  try { j = await r.json(); }
  catch (e) { throw new Error('HTTP ' + r.status + '，返回不是 JSON'); }
  if (!r.ok || j.ok === false) {
    throw Object.assign(new Error(j.error || ('HTTP ' + r.status)),
      { code: j.code, status: r.status });
  }
  return j;
}

/* ---------------- 刷新节奏 ----------------
 独立部署版的 SSE 推流已精简，统一使用 enterApp() 里的固定间隔轮询刷新。 */

/* 顶部状态胶囊 / 离线提示条已移除：采集状态由下载器卡片呈现。 */
function setHealth(ok, text) { /* no-op */ }
function setOffline(v) { /* no-op：离线提示条已移除 */ }
function showTip(e, html) {
  const t = $('#tooltip');
  t.innerHTML = html; t.hidden = false;
  const x = Math.min(e.clientX + 14, window.innerWidth - t.offsetWidth - 10);
  const y = Math.max(8, e.clientY - t.offsetHeight - 12);
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
function hideTip() { $('#tooltip').hidden = true; }

/* ---------------- 主题 ----------------
 v1.0.1：删除主题选择功能，固定浅色主题；页面背景透明以采用 MoviePilot 原生底色。 */
function applyTheme() {
  document.documentElement.dataset.theme = 'light';
  const meta = $('#metaTheme');
  if (meta) meta.content = '#ffffff';
}

/* ---------------- 视图切换 ----------------
 账户 / 登录 / 首次改密 / 退出登录视图已整体删除，认证由 MoviePilot 宿主负责。 */
function clearTimers() { timers.forEach(clearInterval); timers = []; }
function enterApp() {
  /* #app 常驻显示；认证由 MoviePilot 宿主负责。 */
  S.logged = true;
  clearTimers();
  loadAll();
  /* 固定间隔轮询：5 秒刷新总览（下载器卡片 / 顶部状态），30 秒刷新
 周期卡片与流量统计图表。实时速率 1 秒定时器已随实时速率卡片删除。 */
  timers.push(setInterval(() => {
    if (!S.logged || document.hidden) return;
    loadOverview();
  }, 5000));
  timers.push(setInterval(() => {
    if (!S.logged || document.hidden) return;
    loadPeriods(); loadChart();
  }, 30000));
}
function boot() {
  applyTheme(); loadState(); bindEvents(); initPWA(); installFitWatchers();
  renderRangeDropdown(); renderDropdown();
  renderSummary();
  enterApp();
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
  } catch (e) { handleLoadError(e); }
}
async function loadPeriods() {
  try { S.periods = (await api('/api/periods')).periods; renderSummary(); }
  catch (e) { if (e.code !== 'auth_required') console.warn(e); }
}
/* 拖动松手后由这里一次性归位画布（与重绘在同一帧提交，避免中间态闪跳）。 */
function clearPanTransform() {
  const cv = $('#trafficChart');
  cv.style.transition = '';
  cv.style.transform = '';
}
async function loadChart(periodic) {
  const st = S.traffic;
  if (st._panning) return;               // 拖动中不发请求，避免打断即时平移画面
  const seq = ++st._seq;                 // 只接受最后一次请求的响应
  try {
    const data = await api('/api/chart?range=' + encodeURIComponent(st.range) +
      '&metric=traffic&offset=' + (st.offset || 0));
    if (seq !== st._seq) return;
    const sig = JSON.stringify([
      data.times && data.times[0],
      data.labels && data.labels.length,
      (data.series || []).map((x) => [x.id,
        x.up && x.up[x.up.length - 1], x.down && x.down[x.down.length - 1]])]);
    st.data = data;
    st.maxOffset = Number(data.max_offset) || 0;
    st.offset = Number(data.offset) || 0;   // 后端会把超出上限的值 clamp 回来
    st.windowLabel = (data.window && data.window.label) || '';
    if (periodic && st._sig === sig && st._painted) {
      renderLatestBtn();                   // 数据没变：不重绘
      return;
    }
    st._sig = sig; st._painted = true;
    st._hover = null;
    clearPanTransform();
    renderChart();
    renderLatestBtn();
  } catch (e) {
    clearPanTransform();
    if (e.code !== 'auth_required') console.warn(e);
  }
}
function renderLatestBtn() {
  $('#trafficLatest').hidden = !(S.traffic.offset > 0);
  const rng = $('#trafficPanRange');
  if (rng) rng.textContent = S.traffic.windowLabel || '';
}
async function loadAll() {
  await Promise.all([loadOverview(), loadPeriods(), loadChart()]);
  /* 数据 / 图例 / 下载器卡片全部渲染完成后，按浏览器真实可用高度
 分配绘图区高度（首屏即无纵向滚动条）。 */
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
 第一行：汇总（占满一行）；其余下载器用自适应网格，放不下自动换行，不再横向滚动。
 布局：每张卡片两行 ——
 第一行：状态点 + 名称（左，完整显示绝不省略） + 右上角信息
        （汇总卡＝在线情况「在线/总数」，单台＝加入图表的胶囊开关）；
 第二行：实时上传 / 下载速率（左） + 类型标签（单台，右下角）。
 v1.0.4：汇总卡片右上角为下载器在线情况（无开关）；图表由每台卡片右上角
 的开关各自控制显隐（S.hidden 黑名单），单击卡片其余区域打开详情弹窗。 */
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
  const rates = (up, dl) =>
    `<div class="dl-rates">` +
    `<span class="u" title="上传 ${esc(fmtRate(up))}"><b class="rf">↑ ${fmtRate(up)}</b><b class="rc">↑${fmtRateCompact(up)}</b></span>` +
    `<span class="d" title="下载 ${esc(fmtRate(dl))}"><b class="rf">↓ ${fmtRate(dl)}</b><b class="rc">↓${fmtRateCompact(dl)}</b></span></div>`;
  /* v1.0.4：汇总卡片右上角为「在线情况」，不再放胶囊开关；单台开关各管各台。 */
  const allOnline = t.count === 0 || t.online === t.count;
  const onlineTag =
    `<span class="tag sum-online ${allOnline ? 'ok' : 'warn'}" ` +
    `title="在线 ${t.online} / 共 ${t.count}">${t.online}/${t.count} 在线</span>`;
  const sum =
    `<div class="dl-row dl-row-sum">` +
    `<div class="dl-chip summary" data-v="all" title="单击查看全部下载器汇总详情">` +
      `<div class="dl-top"><div class="nm"><i class="dot"></i><span class="dl-nm">汇总 · 全部下载器</span></div>` +
      onlineTag +
      `</div>` +
      `<div class="dl-bottom">` + rates(t.up_rate, t.dl_rate) +
      `</div>` +
    `</div></div>`;
  let items;
  if (!ds.length) {
    items = `<div class="dl-row"><p class="hint">MoviePilot 尚未接入下载器，请先在宿主「设定 → 下载器」中添加。</p></div>`;
  } else {
    items = `<div class="dl-row dl-row-items">` + ds.map((d) => {
      const off = d.status !== 'online';
      const sel = !S.hidden.has(String(d.id));   // 开关开 = 未隐藏 = 参与图表
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
/* 「测试连接」结果窗口已随下载器增删改一起精简（连接由 MoviePilot 宿主校验）。 */
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
function rangeLabel(k) { return RANGE_LABELS[k] || k; }
function dirOptions() { return [{ v: 'up', name: '上传' }, { v: 'down', name: '下载' }]; }
function dirLabel() {
  const st = S.traffic;
  if (!st.dirs.size) return '未选择';
  if (st.dirs.has('up') && st.dirs.has('down')) return '双向';
  return st.dirs.has('up') ? '仅上传' : '仅下载';
}
function renderRangeDropdown() {
  const st = S.traffic, p = '#traffic';
  $(p + 'RangeTrigger').innerHTML =
    `<span>范围</span><span class="dd-count">${esc(rangeLabel(st.range))}</span><span class="caret">▾</span>`;
  $(p + 'RangeMenu').innerHTML =
    `<div class="dd-title">时间范围（单选）</div>` +
    RANGE_ORDER.map((k) =>
      `<label class="dd-item ${st.range === k ? 'active' : ''}">` +
      `<input type="radio" name="trafficRange" value="${k}" ${st.range === k ? 'checked' : ''}>` +
      `<span class="nm">${esc(rangeLabel(k))}</span></label>`).join('');
}
function renderDropdown() {
  const st = S.traffic, p = '#traffic';
  $(p + 'DirTrigger').innerHTML =
    `<span>方向</span><span class="dd-count">${esc(dirLabel())}</span><span class="caret">▾</span>`;
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
/* 下载器被删除导致选项失效时清理「隐藏集合」里的失效 id，顺带重绘卡片、
 范围与方向下拉。v1.0.4：不再强制 'all'，每台下载器的显隐完全由自身开关
 （S.hidden 黑名单）决定，默认全部展示。 */
function syncPicks() {
  const valid = new Set(((S.overview && S.overview.downloaders) || [])
    .map((d) => String(d.id)));
  let removed = false;
  Array.from(S.hidden).forEach((v) => { if (!valid.has(v)) { S.hidden.delete(v); removed = true; } });
  if (removed) saveState();
  renderDownloaders();
  renderRangeDropdown(); renderDropdown();
}
function bindRangeDropdown() {
  const st = S.traffic, p = '#traffic';
  const trig = $(p + 'RangeTrigger'), menu = $(p + 'RangeMenu');
  trig.addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(trig, menu); });
  menu.addEventListener('click', (e) => {
    e.stopPropagation();
    const item = e.target.closest('.dd-item');
    if (!item) return;
    const radio = item.querySelector('input[type=radio]');
    const v = radio ? radio.value : '';
    if (RANGE_ORDER.indexOf(v) < 0) return;
    // label 与内部 radio 会各冒泡一次 click；已选中或刚处理过就直接收起菜单
    if (v === st.range) { closeAllDropdowns(); return; }
    st.range = v; st._hover = null; st.offset = 0;   // 换范围一律回到最新窗口
    saveState(); renderRangeDropdown(); renderLatestBtn(); closeAllDropdowns();
    loadChart();
  });
}
function bindDropdowns() {
  const st = S.traffic, p = '#traffic';
  const trig = $(p + 'DirTrigger'), menu = $(p + 'DirMenu');
  trig.addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(trig, menu); });
  menu.addEventListener('click', (e) => {
    e.stopPropagation();
    const act = e.target.closest('[data-act]');
    if (!act) return;
    if (act.dataset.act === 'all') dirOptions().forEach((o) => st.dirs.add(o.v));
    else { st.dirs.clear(); st.dirs.add('up'); }
    saveState(); renderDropdown();
    menu.hidden = false; trig.classList.add('open'); trig.setAttribute('aria-expanded', 'true');
    keepMenuInViewport(menu);
    renderChart();
  });
  menu.addEventListener('change', (e) => {
    const cb = e.target.closest('input[type=checkbox]');
    if (!cb) return;
    if (cb.checked) st.dirs.add(cb.dataset.v);
    else st.dirs.delete(cb.dataset.v);
    saveState(); renderDropdown();
    menu.hidden = false; trig.classList.add('open'); trig.setAttribute('aria-expanded', 'true');
    keepMenuInViewport(menu);
    renderChart();
  });
}

/* ---------------- 按画布宽度限制「可见点数」 ----------------
 参考 sqing33/PTNexus —— 速率折线的数据点由后端按固定时间粒度做 AVG
 聚合（点数与采集频率解耦），前端再按画布宽度限制一次能看到多少个点
 （ptnexus 手机端用 dataZoom 只显示 12 个可见点，本项目按每点 ≥4px 自适应）。
 这样既不会像 那样把 1080 个采样点全糊在一张图上，也不会退回旧版 12 点
 的稀疏折线。流量堆叠柱状图仍按柱宽抽稀，窄屏不至于被压成细线。 */
function targetPoints() {
  const cv = $('#trafficChart');
  const w = cv.getBoundingClientRect().width || (window.innerWidth - 40);
  // 与 charts.js makePad 的左右留白对齐（桌面 l≈78+r30、紧凑 l≈42+r26）
  const plotW = Math.max(120, w - (w < 480 ? 68 : 108));
  // 流量堆叠柱状图按柱宽抽稀；本月 / 上月 / 全部由 renderChart 豁免上限
  return Math.max(12, Math.min(60, Math.floor(plotW / 26)));
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
  const outSeries = data.series.map((s) =>
    Object.assign({}, s, { up: agg(s.up), down: agg(s.down) }));
  return Object.assign({}, data, { labels, times, spans, series: outSeries });
}

/* ---------------- 图表渲染 ---------------- */
function renderChart() {
  const st = S.traffic, cv = $('#trafficChart');
  const axis = $('#trafficAxis');          // 固定坐标轴层，不随拖动平移
  if (!st.data) {
    TTMCharts.drawBars(cv, { labels: [], groups: [], dirs: { up: true, down: true },
      fmt: fmtBytes, axis, empty: '正在加载数据…' });
    return;
  }
  const maxPts = targetPoints();
  /* 本月 / 上月 / 全部必须逐组保留后端给的全部数据点，不允许前端按
 画布宽度抽稀合并（详见 KEEP_ALL）：本月＝当前日号个点、上月＝该月天数
 个点、全部按自然日 / 月 / 季度 / 年给 ≤30 / 24 / 20 个柱组。 */
  const KEEP_ALL = (st.range === 'month' || st.range === 'lastmonth' || st.range === 'all');
  const pts = KEEP_ALL ? Math.max(maxPts, st.data.labels.length) : maxPts;
  st.view = downsample(st.data, pts, 'sum');
  drawTraffic(st);
}

/* ---------------- 绘图区按浏览器真实可用高度动态分配（桌面 + 手机） ----------------
 1920×1080 是「屏幕物理分辨率」：浏览器标签栏 / 地址栏 / 书签栏 + 操作系统
 任务栏会占掉一大截，页面真正可用的 window.innerHeight 远小于 1080。把
 .chart-lg 写死高度只在理想视口刚好放下，真实窗口会超出、出现纵向滚动条。
 做法：运行时读 window.innerHeight（实际可用高度），量出「除绘图区外的固定
 内容高度」，把剩余空间（扣安全余量 + 底部留白）分给绘图区，用 inline height
 覆盖 CSS 回退值并触发重绘；窗口 / 可用高度一变就实时重算。
 v1.0.4：桌面与手机统一启用（CSS 各断点高度仅作无 JS 回退），底部留白以
 「单个下载器小卡片高度」为单位 —— 桌面留白 2 张、手机留白 1 张，手机端
 因此保证一页放下整个页面内容，桌面绘图区也相应调低两张小卡高度。 */
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
  if (!S.logged) return;
  renderChart();
}
/* 单个下载器小卡片的实测高度（用于把「底部留白」换算成卡片高度）。
 优先取 .dl-row-items 里的单台卡片；没有下载器时退回汇总卡片；再退回估值。 */
function dlChipHeight() {
  const el = document.querySelector('.dl-row-items .dl-chip') ||
             document.querySelector('.dl-chip.summary');
  const h = el ? el.getBoundingClientRect().height : 0;
  return h > 0 ? h : 40;
}
/* 计算并设置高度，返回是否发生了改动（调用方据此决定是否重绘）。
 v1.0.4：桌面 / 手机统一按「视口真实可用高度」分配绘图区，只是底部留白
 的卡片张数不同 —— 桌面 nChip=2（需求2：绘图区调低两个小卡高度），手机
 nChip=1（需求4：一页放下 + 底部留白一个小卡高度）。fixedH 是绘图区之外
 全部内容高度，与绘图区当前高度无关，计算稳定、不会形成 ResizeObserver 回环。 */
function fitDesktopCharts() {
  const hosts = fitHosts();
  if (!hosts.length) return false;
  const charts = fitCharts();
  if (charts.length !== 1) return false;
  const curH = charts[0].getBoundingClientRect().height;
  if (!(curH > 0)) return false;
  const fixedH = fitContentBottom() - curH;   // 绘图区之外的固定内容高度
  const desktop = window.matchMedia(FIT_MQ).matches;
  const nChip = desktop ? 2 : 1;
  const safe = desktop ? FIT_SAFE : 6;          // 手机端安全余量取小，留白 ≈ 恰好一张小卡
  // 先算「填满视口」的原版高度（含 MIN/MAX 钳制），再在它基础上减掉
  // nChip 张小卡高度。这样即便高屏（1920×1080）被 FIT_MAX_H 截断，
  // 「调低 N 张小卡」也一定生效；手机端留白也精确等于一张小卡。
  const base = Math.max(FIT_MIN_H, Math.min(FIT_MAX_H,
                 Math.floor(window.innerHeight - safe - fixedH)));
  let per = Math.max(FIT_MIN_H, Math.min(FIT_MAX_H,
                 Math.floor(base - nChip * dlChipHeight())));
  if (Math.abs(per - curH) <= 1) return false;     // 已稳定：打断 ResizeObserver 回环
  hosts.forEach((h) => { h.style.height = per + 'px'; });
  return true;
}
/* 桌面端纵坐标刻度数取消「固定 5 个」，改为按**实际绘图区高度**
 自适应，且两张卡片必须用同一个数。做法：每次重绘前读两个 .chart-lg 的
 实测高度算一次等分数，通过 TTMCharts.setTickCount 下发为共享值，
 drawLines / drawBars 都读它 ⇒ 哪怕只有一张卡单独重绘也保持一致。
 手机 / 平板（<901px）下发 0，charts.js 内 yTickCount 自动回落到
 固定 5 等分（v1.0.3：不含 0 坐标共 5 个刻度），窗口高度 / 断点变化
 导致共享值变化时强制重绘两图，保证刻度数实时一致。 */
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
  const onBreakpointChange = () => { scheduleFit(); };
  if (mq.addEventListener) mq.addEventListener('change', onBreakpointChange);
  else if (mq.addListener) mq.addListener(onBreakpointChange);
  /* 观察会改变「固定内容高度」的区块：图例行数 / 汇总卡 / 下载器卡片变化也要
 实时重算；ResizeObserver 回环由 fitDesktopCharts 的「差异 ≤1px 不改动」
 打断，稳定后不再重绘。 */
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(scheduleFit);
    ['main', '#summaryCards', '.dl-panel',
     '#trafficLegend', '#trafficSummary'].forEach((s) => {
      const e = document.querySelector(s); if (e) ro.observe(e);
    });
  }
}
/* 手动触发一次（首屏数据加载完成、以及自动化验证 / 调试用）。 */
window.TTMFit = function () { fitAndRedraw(true); };

function noPickHint() {
  return '请在上方下载器卡片中打开至少一个开关';
}
function drawTraffic(st) {
  const view = st.view, cv = $('#trafficChart');
  // v1.0.4：图表分段只由「每台下载器卡片右上角开关」决定 —— 隐藏集合
  // （S.hidden）里的下载器不参与堆叠；汇总卡（id=0）仅作实时汇总展示、
  // 不参与分段。默认隐藏集合为空，即所有下载器都展示。
  const parts = view.series.filter((s) => s.id !== 0 && !S.hidden.has(String(s.id)))
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
    empty: noData ? (parts.length ? '请在「方向」下拉中至少选择一项' : noPickHint())
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
    $('#trafficLegend').innerHTML = `<span>${parts.length ? '请选择方向' : noPickHint()}</span>`;
  }
}

/* ---------------- 横向拖动平移（顺滑版）----------------
 拖动过程中：零网络请求、零 canvas 重绘，只用 rAF + CSS transform 平移位图，
 GPU 合成跟手 60fps；两端带橡皮筋阻尼。
 松手后：按总位移一次性换算 offset 发「一次」请求，数据回来时清 transform
 并重绘（归位与新数据在同一帧提交，不闪跳）。
 可回看 30 个「当前时间范围」长度（后端 maxOffset = 30 × 桶数）。 */
function bindPan() {
  const cv = $('#trafficChart');
  const st = S.traffic;
  let drag = null, raf = 0, pendingX = 0;

  const xOf = (e) => (e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX);
  function pxPerBucket() {
    const g = cv._geom;
    const w = cv.getBoundingClientRect().width || 360;
    const plotW = g ? (g.w - g.pad.l - g.pad.r) : Math.max(120, w - 60);
    const n = g ? (g.groups.length || 1) : 10;
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
    if (st._hover != null) { st._hover = null; renderChart(); }
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
      cv.style.transition = 'transform .18s ease-out';
      applyX(0);
      return;
    }
    st.offset = next;
    renderLatestBtn();        // 立即显示「回到最新」，不等请求
    saveState();
    loadChart();              // 一次请求；成功 / 失败都会清 transform 归位
  }
  cv.addEventListener('pointerdown', start);
  cv.addEventListener('pointermove', move);
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', end);
  $('#trafficLatest').addEventListener('click', () => {
    st.offset = 0; saveState(); loadChart();
  });
}

function bindHover() {
  const cv = $('#trafficChart');
  let raf = 0, lastE = null;
  /* 悬停重绘合并到每帧一次：鼠标快速划过时不再逐事件全量重绘画布 */
  function flush() {
    raf = 0;
    const e = lastE;
    if (!e || S.traffic._panning) return;
    const g = cv._geom; if (!g) return;
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left;
    const n = g.groups.length;
    const idx = Math.floor((x - g.pad.l) / g.groupW);
    if (x < g.pad.l || idx < 0 || idx >= n) { hideTip(); S.traffic._hover = null; renderChart(); return; }
    S.traffic._hover = idx;
    renderChart();
    /* 菜单模板：一个下载器一行
 名称:(黑) ↑ 上传速度(上传线色) ↓ 下载速度(下载线色)
 白底上把线条色轻微压暗一点，保证黄色等亮色也读得清，仍是同一色系。 */
    const ink = (c) => `color-mix(in srgb, ${c} 78%, #0b1220)`;
    const titleOf = (g, i) => (g.tipTitles && g.tipTitles[i]) || g.labels[i];
    const row = (name, up, down) =>
      `<div class="tip-row"><span class="tip-name">${esc(name)}:</span>` +
      (up ? `<span class="tip-v" style="color:${ink(up.color)}">↑ ${up.text}</span>` : '') +
      (down ? `<span class="tip-v" style="color:${ink(down.color)}">↓ ${down.text}</span>` : '') +
      `</div>`;
    const gr = g.groups[idx];
    /* 流量统计点击 / 悬停弹出框改为「先合计、后单下载器明细」。 */
    const html = `<div class="t">${esc(titleOf(g, idx))}</div>` +
      `<div class="tip-sum lead">合计 ` +
      `<b class="u">↑ ${g.dirs.up ? g.fmt(gr.up) : '—'}</b>　` +
      `<b class="d">↓ ${g.dirs.down ? g.fmt(gr.down) : '—'}</b></div>` +
      gr.upParts.map((u, i) => {
        const d = gr.downParts[i];
        return row(u.name,
          g.dirs.up && { color: u.color, text: g.fmt(u.value) },
          g.dirs.down && d && { color: d.color, text: g.fmt(d.value) });
      }).join('');
    showTip(e, html);
  }
  cv.addEventListener('mousemove', (e) => {
    if (S.traffic._panning) return;                 // 拖动时不触发悬停提示
    lastE = e;
    if (!raf) raf = requestAnimationFrame(flush);
  });
  cv.addEventListener('mouseleave', () => {
    if (S.traffic._panning) return;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    lastE = null;
    hideTip(); S.traffic._hover = null; renderChart();
  });
  /* 点击 / 手机点按也唤出同一个菜单；拖动结束后合成的 click 会被忽略 */
  cv.addEventListener('click', (e) => {
    if (S.traffic._panning || (Date.now() - (S.traffic._panEndAt || 0)) < 400) return;
    lastE = e;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    flush();
  });
}

/* ---------------- 设置（已迁移） ----------------
 v1.0.2：所有设置统一在 MoviePilot 原生配置面板（单页），iframe 内无任何设置。 */

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  /* 详情类弹窗（单台 / 汇总）：遮罩空白点击一律忽略，关闭只用右上角按钮或 Esc。 */
  $('#btnCloseDetail').addEventListener('click', closeDetail);
  $('#btnCloseSummary').addEventListener('click', closeDetail);
  ['#detailModal', '#summaryModal'].forEach((sel) => {
    $(sel).addEventListener('click', (e) => {
      if (e.target === $(sel)) e.stopPropagation();
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' &&
        (!$('#detailModal').hidden || !$('#summaryModal').hidden)) closeDetail();
  });
  document.addEventListener('click', () => closeAllDropdowns());

  // 顶部 4 张卡：右上角「历史数据」清单（纯展示、可无限下滑）
  bindSummaryCards();

  /* 下载器卡片：胶囊开关切换「是否加入图表」；单击卡片其余区域打开详情
     弹窗；汇总卡片打开汇总详情。事件委托挂在 .dl-panel 上。 */
  $('.dl-panel').addEventListener('click', (e) => {
    const sw = e.target.closest('.dl-switch');
    if (sw) {
      e.stopPropagation();
      const holder = sw.closest('[data-v]');
      const v = holder ? holder.dataset.v : '';
      // v1.0.4：单台下载器开关切换「隐藏集合」，直接决定图表是否画该台。
      if (v && v !== 'all') {
        if (S.hidden.has(v)) S.hidden.delete(v); else S.hidden.add(v);
        saveState();
        renderDownloaders();
        renderChart();
      }
      return;
    }
    const chip = e.target.closest('.dl-chip');
    if (!chip) return;
    if (chip.dataset.v === 'all') { openSummary(); return; }
    openDetail(Number(chip.dataset.v));
  });

  bindRangeDropdown(); bindDropdowns(); bindHover(); bindPan();
  let rtimer;
  window.addEventListener('resize', () => {
    clearTimeout(rtimer);
    rtimer = setTimeout(() => {
      $$('.dd-menu:not([hidden])').forEach(keepMenuInViewport);
      if (S.logged) renderChart();
    }, 150);
  });
}

/* ---------------- 在线 / 离线 ----------------
 PWA / Service Worker / 安装到桌面属于独立部署版能力，插件版已精简，
 仅保留网络恢复时自动刷新数据的轻量逻辑。 */
function initPWA() {
  /* 离线提示条 / PWA 已移除；仅保留网络恢复时自动刷新数据。 */
  window.addEventListener('online', () => { if (S.logged) loadAll(); });
}

boot();
