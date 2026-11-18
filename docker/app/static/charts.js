/* 图表引擎：原生 SVG 折线 / 堆叠柱状图，零外部依赖。
 *
 * 绘图区全部由 SVG 矢量图元构成（path / rect / line / text），坐标轴文字
 * 使用与全站 body 一致的字体栈，浏览器缩放时按矢量重新栅格化，永不模糊。
 * 双层结构：数据层 SVG（网格 / 曲线 / 柱 / 悬停，随拖动平移）+
 * 固定坐标轴层 SVG（Y 刻度带 / X 时间标签纹丝不动），由 .chart-viewport 裁剪。
 *
 * 对外接口：drawLines / drawBars / adapt / palette，以及 _geom / _xTicks /
 * _smoothUsed / _fitGap / _shiftPts 自检钩子、帧平移动画、hover、拖动平移。
 * Y 轴左侧留白按最长刻度文字实测宽度动态计算，X 轴标签按可用宽度抽稀，
 * 相邻刻度净空白不少于 2.5 个数字字符，首尾刻度必现。
 * Y 轴把 plotMax 直接 n 等分，最顶一条恒为最大值并落在绘图区顶部；
 * 桌面端 n 由绘图区实际高度自适应（3~10），手机 / 平板恒 6 等分，
 * 两张卡片共用同一 n。颜色随当前深浅主题适配，上传在前、下载在后。
 * 实时速率折线按 times 判定窗口是否真实推进：推进才做形状恒定的左移
 * 补间，未推进直接画终态，避免右端「停顿后重绘」。
 */
'use strict';
window.TTMCharts = (function () {

  const SVG_NS = 'http://www.w3.org/2000/svg';
  /* 桌面端纵坐标刻度数量取消 的「固定 4 等分 / 共 5 个值」，
 改为**按实际绘图区高度自适应**：绘图区越高、每档留白越宽裕就多分几档，
 越矮就少分几档（每档约 55px 视觉间距），clamp 到 3~10 等分。手机 /
 平板（<901px）保持 6 等分（7 个值）逐字一致、
 · 两张卡片共用同一个「共享等分数」：app.js 的 fitAndRedraw 按两个
 .chart-lg 的实测高度算一次再 setTickCount 下发，drawLines / drawBars
 都读同一个值 ⇒ 任意时刻哪怕只有一张卡单独重绘，刻度数量也必然一致；
 · app.js 尚未下发（首帧 / 无 fit / 自动化独立调用）时按传入高度自适应
 兜底；drawLines 的 hForScale 与 drawBars 的 h 都是同一个 cv 的实测
 高度，两图高度由 fitDesktopCharts 统一设定，兜底结果同样一致；
 · 最顶一条刻度恒为 plotMax = 纵坐标最大值，落在 y=pad.t 必现，
 与等分数 n 无关（computeScale 生成 ticks[0..n]，末项恒 = plotMax）。
 h 参数保留仅为兼容既有调用签名。 */
  let _sharedTickN = 0;
  /* 按绘图区高度算「合适」的等分数：扣掉上下 padding（pad.t=14 + pad.b=28）
 得到真实可绘高度，每约 55px 分一档，边界钳到 3~10，避免太疏 / 太密。 */
  function tickCountFor(h) {
    const plotH = Math.max(1, (Number(h) || 0) - 42);
    return Math.max(3, Math.min(10, Math.round(plotH / 55)));
  }
  /* app.js 统一设定共享等分数；返回是否发生变化（供调用方决定是否重绘）。 */
  function setTickCount(n) {
    const v = Math.max(0, Math.round(Number(n) || 0));
    const changed = v !== _sharedTickN;
    _sharedTickN = v;
    return changed;
  }
  function getTickCount() { return _sharedTickN; }
  function yTickCount(h) {
    let desktop = false;
    try {
      desktop = !!(window.matchMedia && window.matchMedia('(min-width:901px)').matches);
    } catch (e) { /* 无 matchMedia：退回手机口径 6 等分 */ }
    if (!desktop) return 6;
    return _sharedTickN > 0 ? _sharedTickN : tickCountFor(h);
  }
  /* 与 style.css body 完全一致的字体栈：SVG <text> 用它渲染，离屏测量也用它，
 保证「文本和界面其它文字一样」且量出的留白宽度与真实渲染严格一致。 */
  const FONT_STACK = '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif';

  /* 离屏测量上下文（仅用于 measureText，不参与任何绘制，避免引入位图）。 */
  const _measureCanvas = document.createElement('canvas');
  const _mctx = _measureCanvas.getContext('2d');
  let _fontPx = 11;
  function setFont(px) { _fontPx = px; _mctx.font = px + 'px ' + FONT_STACK; }
  function textW(s) { return _mctx.measureText(String(s)).width; }
  /* 数字转紧凑字符串：SVG 属性里避免 1.3333333333333 这种超长小数。 */
  function pnum(v) {
    const x = Number(v);
    if (!Number.isFinite(x)) return '0';
    return String(Math.round(x * 100) / 100);
  }
  function xmlEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
  }
  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function palette() {
    return {
      grid: css('--grid', '#25344e'), muted: css('--muted', '#8fa4c0'),
      text: css('--text', '#e8eef8'), panel: css('--panel', '#111c2f'),
      panel2: css('--panel2', '#17243a'),
      up: css('--up', '#fb923c'), down: css('--down', '#38bdf8'),
      accent: css('--accent', '#6366f1'),
    };
  }
  /* 浅色主题下把用户自定义的高亮色压暗，避免白底看不清 */
  function adapt(hex, theme) {
    if (theme !== 'light') return hex || '#8899aa';
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!m) return hex || '#8899aa';
    const k = 0.72;
    return '#' + [1, 2, 3].map((i) =>
      Math.round(parseInt(m[i], 16) * k).toString(16).padStart(2, '0')).join('');
  }

  /* 准备一张 SVG 画布：viewBox 与容器 CSS 像素 1:1，浏览器缩放时按矢量重绘。
 复用同一个 <svg> 节点，只替换内部图元，避免反复创建 DOM。 */
  function prep(host) {
    if (!host) return null;
    const r = host.getBoundingClientRect();
    if (r.width < 20 || r.height < 20) return null;
    let svg = host._svg;
    if (!svg || svg.parentNode !== host) {
      svg = document.createElementNS(SVG_NS, 'svg');
      svg.setAttribute('class', 'ttm-svg');
      host.appendChild(svg);
      host._svg = svg;
    }
    const w = r.width, h = r.height;
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '100%');
    svg.setAttribute('viewBox', '0 0 ' + pnum(w) + ' ' + pnum(h));
    svg.setAttribute('preserveAspectRatio', 'none');
    const compact = w < 480;
    setFont(compact ? 10 : 11);
    return { svg, w, h, compact };
  }
  /* 数据层 / 固定轴层分别提交图元；未启用双层时全部落在数据层。 */
  function commit(p, ap, dataMarkup, axisMarkup) {
    p.svg.innerHTML = dataMarkup + (ap ? '' : axisMarkup);
    if (ap) ap.svg.innerHTML = axisMarkup;
  }
  /* 一个 SVG 文本图元。字体 / 字号与 body 一致，是矢量文本，放大不模糊。 */
  function txt(x, y, str, fill, anchor) {
    return '<text x="' + pnum(x) + '" y="' + pnum(y) + '" fill="' + fill +
      '" text-anchor="' + (anchor || 'start') + '" dominant-baseline="central" ' +
      'font-family="' + FONT_STACK.replace(/"/g, '&quot;') + '" font-size="' +
      _fontPx + 'px">' + xmlEsc(str) + '</text>';
  }
  function emptyMarkup(w, h, text, C) {
    return txt(w / 2, h / 2, text, C.muted, 'middle');
  }

  /* 纵坐标等分数固定、且必须标出最大值刻度。
 曾用 niceStep 生成「整数 nice 值」刻度，但 niceStep 会把
 plotMax/n 向上取整到 1/2/2.5/5/10，实际刻度数随峰值浮动，而且最高一条
 刻度常小于 plotMax —— 用户反馈「纵坐标太少」、最大值那一档也没标出来。
 现改为把绘图映射上限 plotMax 直接 n 等分（n = yTickCount：
 桌面按实际绘图区高度自适应 3~10 / 手机 6）：ticks = 0, plotMax/n, …,
 n·plotMax/n = plotMax，最顶一条刻度值 = plotMax = 纵坐标最大值，
 落在 y=pad.t 明确标出。
 桌面等分数由「实际绘图区高度」决定（tickCountFor），不再是 的
 固定 4；两卡共用 app.js 下发的共享等分数，数量必然一致；手机恒 6。
 plotMax = peak / Y_FILL 保持不变：曲线 / 柱子依旧稳定画到 98% 高度，
 绘图映射与数值口径pad.t=14px 与 segmentPath 的钳制继续提供
 描边 / hover 圆点安全余量，txt 的 dominant-baseline=central 保证
 顶部刻度文字不会被裁切。 */
  const Y_FILL = 0.98;
  function computeScale(v, floor, h) {
    const peak = Math.max(Number(v) || 0, 0);
    const plotMax = peak > 0 ? peak / Y_FILL : Math.max(Number(floor) || 1, 1);
    const n = yTickCount(h);
    const ticks = [];
    for (let i = 0; i <= n; i++) ticks.push(plotMax * i / n);
    return { plotMax, ticks, tickStep: plotMax / n, tickMax: plotMax };
  }
  /* 兼容旧内部调用 / 自检钩子：只返回绘图上限。 */
  function niceMax(v, floor) { return computeScale(v, floor).plotMax; }

  /* 先量出各档 Y 轴刻度文字有多宽，再决定左侧留白，文字不会被裁掉。
 按当前等分数（桌面高度自适应 / 手机 6）的实际刻度量，含顶部 plotMax 最大值。 */
  function makePad(w, scale, fmt, compact) {
    let mw = 0;
    for (let i = 0; i < scale.ticks.length; i++) {
      mw = Math.max(mw, textW(fmt(scale.ticks[i])));
    }
    const want = Math.ceil(mw + (compact ? 9 : 12));
    const floor = compact ? 42 : 58;
    return {
      l: Math.min(Math.floor(w * 0.40), Math.max(floor, want)),
      r: compact ? 26 : 30, t: 14, b: compact ? 26 : 28,
      _textW: mw,
    };
  }
  /* 水平网格线画在数据层，位于曲线 / 柱子下方。
 按当前等分刻度逐条画；动画中间帧 max 变化时刻度线随之伸缩，超出当前
 max 的刻度线跳过（不会画到绘图区外）。稳定帧恒 n+1 条（n = 桌面按绘图区
 高度自适应 / 手机 6，含 0），最顶一条 = plotMax 落在 y=pad.t。 */
  function gridYMarkup(w, h, pad, C, scale, max) {
    let s = '';
    for (let i = 0; i < scale.ticks.length; i++) {
      const t = scale.ticks[i];
      if (t > max * 1.0001) continue;
      const y = pad.t + (h - pad.t - pad.b) * (1 - t / max) + .5;
      s += '<line x1="' + pnum(pad.l) + '" y1="' + pnum(y) + '" x2="' +
        pnum(w - pad.r) + '" y2="' + pnum(y) + '" stroke="' + C.grid +
        '" stroke-width="1" shape-rendering="crispEdges"/>';
    }
    return s;
  }
  /* Y 轴刻度文字画在固定轴层；左侧刻度带用面板底色不透明铺底，遮住数据层
 平移时溢出到 x < pad.l 的曲线。刻度值 = plotMax 的等分（桌面按绘图区高度
 自适应 / 手机 6），最高一条即纵坐标最大值，dominant-baseline=central
 保证不裁切。 */
  function ticksYMarkup(w, h, pad, scale, max, fmt, C, fillBand) {
    let s = fillBand ? '<rect x="0" y="0" width="' + pnum(pad.l) +
      '" height="' + pnum(h) + '" fill="' + C.panel + '"/>' : '';
    for (let i = 0; i < scale.ticks.length; i++) {
      const t = scale.ticks[i];
      if (t > max * 1.0001) continue;
      const y = pad.t + (h - pad.t - pad.b) * (1 - t / max);
      s += txt(pad.l - 7, y, fmt(t), C.muted, 'end');
    }
    return s;
  }
  /* X 轴：按可用宽度估算能放几个标签，自动抽稀；末尾标签在放得下时补上。
 useMeasure=true 时按实测最长标签文字宽度定刻度间距，长日期时间
 标签不会贴在一起；只改变画几个刻度文字，绝不改动数据点数量。
 柱状图的每个时间点是一个「柱组」（1~2 根柱），横坐标文字必须
 落在该组上传/下载两柱的正下方居中，即 groupW*(i+.5)；折线图才是把采样点
 铺满绘图区的 i/(n-1) 口径。此前柱状图复用了折线口径：n=1 时恰好也是 .5
 居中（只是巧合、并未与柱组绑定），n>1 时每个标签都偏离对应柱组半个组宽，
 时间点少时尤其明显。新增 barMode 按柱组中心定位，单点/多点都严格居中。 */
  function axisXMarkup(w, h, pad, labels, C, estW, useMeasure, barMode, edges, axisLabels) {
    const n = labels.length;
    if (!n) return { markup: '', xs: [], unit: estW || 52 };
    /* axisLabels 是「显示用」文本（≤24h 时已去掉 MM-DD 日期），
 labels 仍是原始标签（tooltip 标题用，保留秒 / 日期精度，互不影响）。 */
    const shown = (axisLabels && axisLabels.length === n) ? axisLabels : labels;
    const plotW = w - pad.l - pad.r;
    const y = h - pad.b + 13;
    /* 相邻两个刻度文字之间的「净空白」由 4 个数字字符
 收紧为 **2.5 个数字字符** —— 仍用真实字体的 '0' 宽度量（tabular-nums
 下数字等宽），而不是拍脑袋的固定 px。用户反馈 4 字符偏宽、刻度太少，
 2.5 字符已足够清晰；在守住它的前提下贪心「尽量多放」几个刻度。
 gap 同时用于 unit 占位估算、极窄屏退化判定与贪心避让，改这一处即全部生效。 */
    const digitW = textW('0') || 6;
    const gap = 2.5 * digitW;
    let maxShownW = 0;
    for (let i = 0; i < n; i++) maxShownW = Math.max(maxShownW, textW(shown[i]));
    const unit = Math.max(estW || 52, Math.ceil(maxShownW + gap));
    const X = (i) => barMode
      ? pad.l + plotW * ((i + .5) / n)          // 柱组中心：上传/下载两柱正下方
      : pad.l + plotW * (n === 1 ? .5 : i / (n - 1));
    const asText = (t) => String(t == null ? '' : t);
    /* 一个刻度的文字占位盒：按锚点算出左 / 右边界，用于精确判定净空白。 */
    const box = (i, text, anchor) => {
      const x = X(i), tW = textW(text);
      let L, R;
      if (anchor === 'start') { L = x; R = x + tW; }
      else if (anchor === 'end') { L = x - tW; R = x; }
      else { L = x - tW / 2; R = x + tW / 2; }
      return { x, text, anchor, L, R };
    };
    let s = '';
    const xs = [];
    /* 单点：只有一个刻度，居中显示（折线 / 柱状都落在绘图区中心或柱组中心）。 */
    if (n === 1) {
      const b0 = box(0, asText(shown[0]), 'middle');
      return { markup: txt(b0.x, y, b0.text, C.muted, 'middle'), xs: [b0.x], unit };
    }
    /* 首尾刻度无条件展现：
 - 折线且传 edges：首用 window 范围起点 + start 锚点贴左边界、尾用范围
 终点 + end 锚点贴右边界，与左上角选择的时间范围逐字对齐；
 ≤24h 时 edges / axisLabels 已在 app.js 去掉日期。
 - 柱状（barMode，不传 edges）：首尾就是第一 / 最后一个柱组的标签，
 按 柱组中心定位、middle 锚点，保证「首尾两个刻度要展现」。 */
    let first, last;
    if (edges && !barMode) {
      first = box(0, asText(edges.start || shown[0]), 'start');
      last = box(n - 1, asText(edges.end || shown[n - 1]), 'end');
    } else {
      first = box(0, asText(shown[0]), 'middle');
      last = box(n - 1, asText(shown[n - 1]), 'middle');
    }
    /* 极窄屏：首尾文字本身都塞不下（含 2.5 字符空白）→ 退回均匀抽稀，绝不
 让 start/end 锚点文字互相压盖或溢出。 */
    if (last.L - first.R < gap) {
      const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / unit))));
      let lastX = -1e9;
      for (let i = 0; i < n; i += every) {
        s += txt(X(i), y, asText(shown[i]), C.muted, 'middle');
        lastX = X(i); xs.push(X(i));
      }
      if (n > 1 && (n - 1) % every !== 0 && X(n - 1) - lastX >= unit) {
        s += txt(X(n - 1), y, asText(shown[n - 1]), C.muted, 'middle');
        xs.push(X(n - 1));
      }
      return { markup: s, xs, unit };
    }
    /* 贪心「尽量多放」：首刻度固定后，从左到右逐个考察中间点，只要与左邻
 文字的净空白 ≥ 2.5 数字字符、且不会挤掉尾刻度（同样留 2.5 字符空白）就放。
 用每个刻度各自的实测文字半宽算边界，比按最长文字定步长能多放几个。 */
    s += txt(first.x, y, first.text, C.muted, first.anchor); xs.push(first.x);
    let prevR = first.R;
    for (let i = 1; i < n - 1; i++) {
      const b = box(i, asText(shown[i]), 'middle');
      if (b.L - prevR < gap) continue;      // 与上一个刻度的净空白不足 2.5 数字字符
      if (last.L - b.R < gap) continue;     // 会挤占尾刻度的净空白
      s += txt(b.x, y, b.text, C.muted, 'middle'); xs.push(b.x);
      prevR = b.R;
    }
    s += txt(last.x, y, last.text, C.muted, last.anchor); xs.push(last.x);
    return { markup: s, xs, unit };
  }

  /* 生成一段连续折线的 SVG path（生产路径 smooth=true 用单调三次
 Hermite 保形平滑，精确过每个采样点、段内不过冲；smooth=false 用直线）。
 原先 canvas 版 strokeSegment 的 Fritsch–Carlson 限幅逻辑原样移植。 */
  function segmentPath(pts, smooth, top, bottom) {
    if (!pts.length) return { d: '', dots: [] };
    if (pts.length === 1) return { d: '', dots: [{ x: pts[0].x, y: pts[0].y, r: 1.6 }] };
    let d = 'M' + pnum(pts[0].x) + ' ' + pnum(pts[0].y);
    if (!smooth || pts.length < 3) {
      for (let i = 1; i < pts.length; i++) {
        d += 'L' + pnum(pts[i].x) + ' ' + pnum(pts[i].y);
      }
      return { d, dots: [] };
    }
    const n = pts.length;
    const clampY = (v) => Math.max(top, Math.min(bottom, v));
    const hseg = new Array(n - 1), dseg = new Array(n - 1);
    for (let i = 0; i < n - 1; i++) {
      hseg[i] = pts[i + 1].x - pts[i].x;
      dseg[i] = hseg[i] > 0 ? (pts[i + 1].y - pts[i].y) / hseg[i] : 0;
    }
    const m = new Array(n);
    m[0] = dseg[0]; m[n - 1] = dseg[n - 2];
    for (let i = 1; i < n - 1; i++) {
      if (dseg[i - 1] * dseg[i] <= 0) { m[i] = 0; continue; }
      const w1 = 2 * hseg[i] + hseg[i - 1], w2 = hseg[i] + 2 * hseg[i - 1];
      m[i] = (w1 + w2) / (w1 / dseg[i - 1] + w2 / dseg[i]);
    }
    for (let i = 0; i < n - 1; i++) {
      if (dseg[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      const a = m[i] / dseg[i], b = m[i + 1] / dseg[i], sq = a * a + b * b;
      if (sq > 9) { const t = 3 / Math.sqrt(sq); m[i] = t * a * dseg[i]; m[i + 1] = t * b * dseg[i]; }
    }
    for (let i = 0; i < n - 1; i++) {
      const p1 = pts[i], p2 = pts[i + 1];
      const lo = Math.min(p1.y, p2.y), hi = Math.max(p1.y, p2.y);
      const clampSeg = (v) => Math.max(lo, Math.min(hi, v));
      const c1x = p1.x + hseg[i] / 3, c2x = p2.x - hseg[i] / 3;
      const c1y = clampY(clampSeg(p1.y + m[i] * hseg[i] / 3));
      const c2y = clampY(clampSeg(p2.y - m[i + 1] * hseg[i] / 3));
      d += 'C' + pnum(c1x) + ' ' + pnum(c1y) + ' ' + pnum(c2x) + ' ' +
        pnum(c2y) + ' ' + pnum(p2.x) + ' ' + pnum(p2.y);
    }
    return { d, dots: [] };
  }

  /* ---------------- 实时速率折线「帧平移 / 纵向伸缩」动画 ----------------
 逻辑与 完全一致，仅把每帧的 Canvas 绘制换成重建 SVG 图元。 */
  const ANIM_MS = 300;
  const easeCubicOut = (t) => 1 - Math.pow(1 - t, 3);
  function reduceMotion() {
    try { return !!(window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    catch (e) { return false; }
  }
  function cancelLineAnim(cv) {
    if (cv._anim) {
      cancelAnimationFrame(cv._anim.id);
      if (cv._anim.frame) cv._prevFrame = cv._anim.frame;
      cv._anim = null;
    }
  }
  function animMsFor(n, shiftPts) {
    if (shiftPts <= 0) return ANIM_MS;
    return Math.round(Math.min(650, Math.max(ANIM_MS, ANIM_MS * 60 / Math.max(1, n))));
  }
  function snapLines(scale, lines, n, times) {
    return { scale, n, times: times ? times.slice() : null,
      lines: lines.map((L) => L.values.slice()) };
  }

  /* 绘制一帧 SVG。shiftPts>0 是帧平移中间帧：X 坐标整体左移 shiftPts 个点距，
 绘图区外用 clipPath 裁剪；lines 可含一个额外末点。geomLines 始终为目标终态，
 保证 hover 提示读到真实数值而非平移中间态。 */
  function paintLines(cv, cfg, padScale, dispMax, lines, geomLines, shiftPts) {
    const p = prep(cv); if (!p) return;
    const ap = cfg.axis ? prep(cfg.axis) : null;
    const { w, h, compact } = p, C = palette();
    const n = cfg.labels.length;
    const pad = makePad(w, padScale, cfg.fmt, compact);
    const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
    const X = (i) => pad.l + plotW * (n === 1 ? .5 : i / (n - 1));
    const Y = (v) => pad.t + plotH * (1 - v / dispMax);
    const gap = n > 1 ? plotW / (n - 1) : plotW;
    const shift = shiftPts > 0 ? shiftPts * gap : 0;
    const Xs = (i) => X(i) - shift;
    const smooth = cfg.smooth !== false;
    cv._smoothUsed = smooth;
    cv._fitGap = gap;
    cv._shiftPts = shiftPts || 0;

    const needClip = shift > 0 || lines.some((L) => L.values.length > n);
    const clipId = (cv.id || 'ttm') + '-clip';
    let data = '';
    if (needClip) {
      data += '<defs><clipPath id="' + clipId + '"><rect x="' + pnum(pad.l) +
        '" y="' + pnum(pad.t - 2) + '" width="' + pnum(plotW) + '" height="' +
        pnum(plotH + 4) + '"/></clipPath></defs>';
    }
    data += gridYMarkup(w, h, pad, C, padScale, dispMax);
    let curves = '';
    lines.forEach((L) => {
      const color = L.color, width = L.width || 2;
      let seg = [];
      const flush = () => {
        if (!seg.length) return;
        const sp = segmentPath(seg, smooth, pad.t, h - pad.b);
        if (sp.d) {
          curves += '<path d="' + sp.d + '" fill="none" stroke="' + color +
            '" stroke-width="' + pnum(width) + '" stroke-linejoin="round" stroke-linecap="round"/>';
        }
        sp.dots.forEach((o) => {
          curves += '<circle cx="' + pnum(o.x) + '" cy="' + pnum(o.y) +
            '" r="' + pnum(o.r) + '" fill="' + color + '"/>';
        });
        seg = [];
      };
      L.values.forEach((v, i) => {
        if (v == null) { flush(); return; }
        seg.push({ x: Xs(i), y: Y(v) });
      });
      flush();
    });
    data += needClip ? '<g clip-path="url(#' + clipId + ')">' + curves + '</g>' : curves;

    const hv = cfg.hover;
    if (shift === 0 && hv != null && hv >= 0 && hv < n) {
      const x = X(hv);
      data += '<line x1="' + pnum(x) + '" y1="' + pnum(pad.t) + '" x2="' +
        pnum(x) + '" y2="' + pnum(h - pad.b) + '" stroke="' + C.muted +
        '" stroke-width="1" opacity="0.55"/>';
      geomLines.forEach((L) => {
        const v = L.values[hv];
        if (v == null) return;
        data += '<circle cx="' + pnum(x) + '" cy="' + pnum(Y(v)) + '" r="' +
          pnum(L.width > 1.3 ? 4 : 2.5) + '" fill="' + L.color + '"/>';
      });
    }

    const ax = axisXMarkup(w, h, pad, cfg.labels, C, compact ? 52 : 58,
      true, false, cfg.edges, cfg.axisLabels);
    cv._xTicks = { xs: ax.xs, unit: ax.unit };
    let axis = ticksYMarkup(w, h, pad, padScale, dispMax, cfg.fmt, C, !!ap) + ax.markup;
    commit(p, ap, data, axis);

    cv._geom = { type: 'lines', pad, w, h, n, X, Y, max: dispMax,
      lines: geomLines, labels: cfg.labels, fmt: cfg.fmt, C };
  }

  /* 多系列折线图：lines = [{color,width,values}]，null 表示断线。
 cfg.animate=true 且结构一致时：按 times 判定窗口推进量，
 推进 → 帧平移；未推进 / 结构变化 → 直接画终态。 */
  function drawLines(cv, cfg) {
    const n = cfg.labels.length, vals = [];
    cfg.lines.forEach((L) => L.values.forEach((v) => { if (v != null) vals.push(v); }));
    if (!n || !vals.length) {
      cancelLineAnim(cv);
      const p = prep(cv), ap = cfg.axis ? prep(cfg.axis) : null;
      if (p) commit(p, ap, emptyMarkup(p.w, p.h,
        cfg.empty || '暂无采样数据，等待采集器写入…', palette()), '');
      cv._geom = null; cv._prevFrame = null; cv._animMode = 'none';
      return;
    }
    // scale 带 plotMax（绘图映射）与等分 ticks（含最大值刻度）。
    /* 桌面等分数按实际绘图区高度自适应（tickCountFor），手机恒 6；
 两卡共用 app.js setTickCount 下发的共享等分数 ⇒ 刻度数量一致，
 最高一条刻度仍是 plotMax（顶端必现）。绘图区高度由 app.js 按
 innerHeight 动态分配，本函数把实测高度传给 computeScale。 */
    const hForScale = cv.getBoundingClientRect().height || 560;
    const scale = computeScale(Math.max.apply(null, vals.concat([0])), 1024, hForScale);
    const max = scale.plotMax;
    const target = cfg.lines;
    const prev = cv._prevFrame;
    const canAnim = cfg.animate === true && !reduceMotion() && prev &&
      n > 1 && prev.n === n && prev.lines.length === target.length &&
      prev.lines.every((pv, i) => pv.length === target[i].values.length);

    cancelLineAnim(cv);
    if (!canAnim) {
      paintLines(cv, cfg, scale, max, target, target, 0);
      cv._prevFrame = snapLines(scale, target, n, cfg.times);
      cv._animMode = 'none';
      return;
    }

    /* 按时间轴对齐判定真实推进桶数。 */
    const tNew = cfg.times, tOld = prev.times;
    let shiftPts = 0;
    if (tNew && tOld && tNew.length === n && tOld.length === n && n > 1) {
      /* rate 折线末点时间已对齐 window.end（不再是等间隔的桶起点），
 用「首末平均间隔」会把 dt 算大、帧平移判定失真。改用相邻点间隔
 times[1]-times[0]（恒等于桶宽 step），帧平移节奏与 一致。 */
      const dt = tNew[1] - tNew[0];
      if (dt > 0) shiftPts = (tNew[0] - tOld[0]) / dt;
    }
    if (!(shiftPts > 0 && shiftPts <= Math.min(3, n / 2) &&
          Math.abs(shiftPts - Math.round(shiftPts)) < 0.02)) shiftPts = 0;

    const frame = snapLines(scale, target, n, cfg.times);
    /* 窗口未推进直接画目标帧终态，不做逐帧补间（消除长实时范围右端
 停顿后重复绘制的观感）。 */
    if (shiftPts === 0) {
      paintLines(cv, cfg, scale, max, target, target, 0);
      cv._prevFrame = frame;
      cv._animMode = 'none'; cv._shiftTarget = 0; cv._animLines = null;
      return;
    }

    const fromMax = prev.scale.plotMax, fromLines = prev.lines;
    const add = Math.round(shiftPts);
    const animMs = animMsFor(n, shiftPts);
    const t0 = performance.now();
    const animLines = target.map((L, i) => Object.assign({}, L, {
      values: fromLines[i].slice(0, add).concat(L.values),
    }));
    const state = { id: 0, frame: frame };
    cv._anim = state;
    cv._animMode = 'shift'; cv._shiftTarget = shiftPts;
    cv._animMs = animMs; cv._animLines = animLines;
    const step = (now) => {
      if (cv._anim !== state) return;
      const t = Math.min(1, (now - t0) / animMs), e = easeCubicOut(t);
      if (t >= 1) {
        paintLines(cv, cfg, scale, max, target, target, 0);
        cv._anim = null; cv._prevFrame = frame;
        return;
      }
      const dispMax = fromMax + (max - fromMax) * e;
      paintLines(cv, cfg, scale, dispMax, animLines, target, shiftPts * e);
      state.id = requestAnimationFrame(step);
    };
    state.id = requestAnimationFrame(step);
  }

  /* 堆叠柱状图：每个 x 点画 1~2 根柱（上传 / 下载），柱内按下载器分段堆叠。 */
  function drawBars(cv, cfg) {
    const p = prep(cv); if (!p) return;
    const { w, h, compact } = p, C = palette();
    const ap = cfg.axis ? prep(cfg.axis) : null;
    const n = cfg.groups.length;
    const upOn = !!cfg.dirs.up, downOn = !!cfg.dirs.down;
    const count = (upOn ? 1 : 0) + (downOn ? 1 : 0);
    if (!n || !count) {
      commit(p, ap, emptyMarkup(w, h, cfg.empty || '请至少选择「上传」或「下载」', C), '');
      cv._geom = null; return;
    }

    const totals = [];
    cfg.groups.forEach((g) => {
      if (upOn) totals.push(Number(g.up) || 0);
      if (downOn) totals.push(Number(g.down) || 0);
    });
    // 与折线共用同一套「等分刻度 / 最大值刻度必现」逻辑。
    /* 与 drawLines 共用 computeScale / yTickCount（桌面按绘图区高度自适应
 的共享等分数 / 手机 6 等分），两卡刻度数量必然一致；h 为实测绘图区高度。 */
    const scale = computeScale(Math.max.apply(null, totals.concat([0])), 1024, h);
    const max = scale.plotMax;
    const pad = makePad(w, scale, cfg.fmt, compact);
    const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
    const groupW = plotW / n;

    /* 新增需求：数据点（柱组）较少时适当调宽柱宽，充分利用绘图区。
 的柱宽被 34 / 18px 绝对上限卡死 —— n=2 时 groupW 可能有几百
 像素，柱子却只有 34px，两侧大片留白。做法：以「组宽 × 占比」为主，
 占比与绝对上限都随 n 减小而放宽；点密集（n≥24）时完整回落到 
 的细柱口径，避免拥挤。双方向额外保证两根柱 + 间隙不超过组宽。 */
    const sparse = Math.max(0, Math.min(1, (24 - n) / 20));  // n<=4→1，n>=24→0
    const ratio = count === 1 ? 0.56 + 0.22 * sparse : 0.34 + 0.14 * sparse;
    const denseCap = count === 1 ? 34 : 18;
    const sparseCap = count === 1 ? 132 : 78;
    const cap = denseCap + (sparseCap - denseCap) * sparse;
    /* 在时间点少时把柱子调得很宽，相邻时间点的两组柱几乎贴
 在一起，分不清哪两根属于同一时间点。这里给柱宽加一道硬上限：相邻柱组
 之间（上一组最后一根柱右边缘 → 下一组第一根柱左边缘）至少留 2 个柱宽
 的空白；组内上传/下载两柱仍保持小间隙，表示「同一个时间点」。
 组占宽 = count*bw + (count-1)*gap
 组间空白 = groupW - 组占宽 >= 2*bw
 => (count+2)*bw + (count-1)*gap <= groupW
 n===1 只有一个时间点，不存在「组间」，保留 的宽柱填充。密集档位
 （n 大、groupW 小）算出的上限可能比 细柱口径还小，用 Math.max 以
 细柱口径保底，维持 「点密集回落 」口径、不把细柱再压细。 */
    const gap = Math.min(3, groupW * .06);
    let bw = Math.min(groupW * ratio, cap);
    if (count === 2) bw = Math.min(bw, (groupW - 4) / 2);
    if (n > 1) {
      const fineBw = Math.min(groupW * (count === 1 ? 0.56 : 0.34), denseCap);
      const room = (groupW - (count - 1) * gap) / (count + 2);
      bw = Math.min(bw, Math.max(room, fineBw));
    }
    /* 本月 / 上月 / 全部不再抽稀，窄屏可能出现 30 个柱组，
 groupW 随之变小。柱子允许按上面 的 ratio / cap / room 公式
 一起缩窄，但最窄保留 3px 保证可见。
 「两个柱组之间的留白保持现有标准」＝ 的 (groupW-4)/2 硬上限
 与 room 公式、组内 gap 一律不动；「横坐标刻度密度保持现有标准」＝
 axisXMarkup 的 2.5 数字字符净空白抽稀逻辑不动。仅把柱宽下限由
 2px 提到 3px，不为了塞点数去压缩留白或减少刻度。 */
    bw = Math.max(3, Math.min(bw, groupW * 0.92));

    let data = gridYMarkup(w, h, pad, C, scale, max);
    cfg.groups.forEach((g, idx) => {
      const cx = pad.l + groupW * (idx + .5);
      if (cfg.hover === idx) {
        data += '<rect x="' + pnum(pad.l + groupW * idx) + '" y="' + pnum(pad.t) +
          '" width="' + pnum(groupW) + '" height="' + pnum(plotH) + '" fill="' +
          C.accent + '" opacity="0.10"/>';
      }
      const cols = [];
      if (upOn) cols.push({ parts: g.upParts || [], x: 0 });
      if (downOn) cols.push({ parts: g.downParts || [], x: 0 });
      if (count === 1) cols[0].x = cx - bw / 2;
      else { cols[0].x = cx - bw - gap / 2; cols[1].x = cx + gap / 2; }

      cols.forEach((col) => {
        let y = h - pad.b;
        const alpha = (cfg.hover == null || cfg.hover === idx) ? .94 : .45;
        const parts = col.parts;
        parts.forEach((seg, si) => {
          const v = Number(seg.value) || 0;
          if (v <= 0) return;
          const inset = si < parts.length - 1 ? .9 : 0;
          const bh = Math.max(.5, plotH * (v / max) - inset);
          y -= bh;
          data += '<rect x="' + pnum(col.x) + '" y="' + pnum(y) + '" width="' +
            pnum(bw) + '" height="' + pnum(bh) + '" fill="' + seg.color +
            '" opacity="' + pnum(alpha) + '"/>';
        });
      });
    });

    /* 柱状图标签按柱组中心定位（第 8 参数 barMode=true），
 折线图调用不传该参数、仍用 i/(n-1) 的采样点铺满口径。 */
    const ax = axisXMarkup(w, h, pad, cfg.labels, C, compact ? 56 : 64,
      false, true, null, cfg.axisLabels);
    cv._xTicks = { xs: ax.xs, unit: ax.unit };
    const axis = ticksYMarkup(w, h, pad, scale, max, cfg.fmt, C, !!ap) + ax.markup;
    commit(p, ap, data, axis);

    cv._geom = { type: 'bars', pad, w, h, groupW, max, scale, bw, gap, groups: cfg.groups,
      labels: cfg.labels, tipTitles: cfg.tipTitles || null,
      dirs: cfg.dirs, fmt: cfg.fmt, C };
  }

  return { drawLines, drawBars, adapt, palette,
    /* 桌面端共享等分数（按实际绘图区高度自适应）的下发 / 自检接口。 */
    tickCountFor, setTickCount, getTickCount,
    _strokeSegment: segmentPath, _FIT_MIN_GAP: 5,
    _ANIM_MS: ANIM_MS, _easeCubicOut: easeCubicOut, _cancelLineAnim: cancelLineAnim,
    _animMsFor: animMsFor };
})();
