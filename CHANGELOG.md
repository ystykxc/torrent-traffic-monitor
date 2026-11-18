# 更新日志（CHANGELOG）

> 本仓库同时托管两种部署形态的版本历史：**一、独立 Docker 版（v9 ~ v50）** 与 **二、MoviePilot V3 插件版（v1.0.2 ~ v1.0.32）**。两者统计口径同源，但插件版按 MoviePilot 宿主规范做了精简与原生化改造。

## 一、独立 Docker 版（v9 ~ v50）


> 本文件归并了项目 **v9 ~ v48** 的全部版本更新记录（此前逐版堆叠在 `README.md` 里，
> 现已集中归档，README 只保留当前版本的功能与部署说明）。历史条目按原样保留，
> 其中的界面细节、验证数据与镜像文件名均对应各自版本，仅供回溯。
>
> **当前项目版本：v50**。镜像文件 `torrent-traffic-monitor-image-amd64-v48.tar`
> 中的 `v48` 是镜像构建批次号，与项目迭代版本号相互独立，按发布要求保持不变；
> 导入后的镜像 tag 恒为 `torrent-traffic-monitor:1.0.0`。

---

### v50（正式发布 · 收尾定版）

本次在 v48 代码基础上做收尾与正式发布，**功能逻辑零改动**，主要变更如下：

| 项目 | 内容 |
| --- | --- |
| **代码归并** | 清除源码中逐版本累积的「补丁叙事」注释（约 800 处），把各模块头部统一重写为**当前设计说明**；修正文档与实现不一致之处（如 waitress 线程数 4→12）；统一命名与注释风格。经 Python `tokenize` 与注释区逐项比对，验证**代码逻辑零改动**，`py_compile` / `node --check` 全部通过。 |
| **部署默认值调整** | 两个 compose 的端口映射由 `127.0.0.1:${WEB_PORT:-8080}:8080` 改为 `${WEB_PORT:-8080}:8080`（监听宿主机所有网卡），**默认允许局域网内其他主机直接访问** `http://<NAS 内网 IP>:8080`。注释中保留了改回「仅本机访问」与「只放行单个内网 IP」的写法。 |
| **版本固定** | 项目迭代版本固定为 **v50**：`app/__init__.py` 增加 `__version__` / `VERSION` 常量，Service Worker 缓存升到 `ttm-shell-v50`。镜像 tag 仍为 `1.0.0`，镜像文件名保持 `...-v48.tar` 不变。 |
| **项目结构** | 按标准 GitHub 开源项目结构重整：源码、文档、工具、图片资源分目录存放，补 `CHANGELOG.md`、`.env.example`。 |
| **交付文档** | 新增两份 Word 图文介绍与部署文档（简要版 / 详细版），除「深浅双主题」功能介绍外，所有界面截图统一使用**浅色主题**。 |

> v49 为内部整理版本，未单独发布；v48 之后直接定版 v50。

---

### v48

> 本轮两处调整：**手机端实时速率 / 流量统计卡片的「时间范围」下拉框改成和桌面端一致（5 个选项高，其余靠右侧滚动条下拉）**，以及**桌面端两张卡片绘图区纵坐标取消「固定 5 个刻度」，按实际绘图区高度自适应刻度数量，两卡数量一致、最顶端刻度必现**。前者把 v44 的桌面专用 CSS 规则提升为全端全局规则；后者只改前端 `charts.js` / `app.js` 的刻度分配逻辑，**无数据库迁移**、**后端 `app/*.py` 与 `index.html` 零改动**、流量统计口径沿用 v15 零改动。

| 需求 | 实现 |
|---|---|
| **1. 手机端时间范围下拉框与桌面端一致（5 项高 + 右侧滚动条）** | v44 把「固定 5 个可选项高度」做在 `@media (min-width:901px)` 桌面专用块里，手机 / 平板（≤900px）仍把 11~12 个范围选项全部铺开（实测 390×844 下弹出框高约 374px、无滚动条）。v48 把整组规则从桌面块中**移出并放到所有 `@media` 之后的全局块**（层叠优先级最高）：`.chart-controls #rateRangeMenu` / `#trafficRangeMenu` 统一 `box-sizing:border-box` + `padding:0 6px 6px` + `max-height:calc(30px × 5 + 26px + 8px) = 184px`，`.dd-item` 固定 30px、`.dd-title` 固定 26px 且 `position:sticky;top:0`，`overflow-y:auto` / `overflow-x:hidden` / `overscroll-behavior:contain`。桌面端与手机端 computed style 逐项实测完全一致（`184px` / `clientHeight 182` / `scrollHeight 362` / 可见 5 项 / 单项 30px / 标题 26px sticky / 默认滚动条）；滚到底最后一项完整可见，第 6 项起靠下拉框右侧竖向滚动条往下拉出。仅用两个 id 精确限定，**方向下拉 / 顶部四小卡片「历史数据」下拉 / 触发按钮 / 选项文案 / radio / 选中逻辑全部零改动**；v46 的「不自定义 `::-webkit-scrollbar`、回落浏览器默认滚动条（与 `.hist-list` 同源）」继续保留，桌面端相对 v47 逐项零改动。 |
| **2. 桌面端纵坐标刻度数按实际绘图区高度自适应（两卡一致、顶端必现）** | v43 起桌面端 Y 轴固定 4 等分（0 之外 4 档、共 5 个刻度值），但 v43 的绘图区高度是按 `window.innerHeight` 动态分配的（实测 1920 宽下 `innerHeight` 1080→768 时绘图区 307→151px），固定 5 档在高绘图区偏疏、矮绘图区偏密。v48 取消固定：`charts.js` 新增 `tickCountFor(h)`，按「绘图区高度 − `pad.t`14 − `pad.b`28」每约 **55px** 分一档、`Math.max(3, Math.min(10, round(...)))` 钳在 3~10 等分，导出 `setTickCount(n)` / `getTickCount()`；`app.js` 新增 `syncTickCount()`，在 `fitAndRedraw()` 里高度调整完成后读两个 `.chart-lg` 的实测高度算一次并下发为**共享等分数**，`drawLines` / `drawBars` 的 `computeScale()` 都读它 —— 即使只单独重绘一张卡（切换范围 / 轮询刷新），两张绘图区刻度数量也严格一致；共享值随窗口高度 / 901px 断点变化实时重算并强制重绘两图。`computeScale()` 仍把 `plotMax` 直接 n 等分生成 `ticks[0..n]`，**末项恒 = `plotMax` = 纵坐标最大值，落在 `y=pad.t=14` 必现**（与 n 无关）；`plotMax = peak / 0.98`、网格线、留白测量、曲线 / 柱子饱满度、Y 轴自适应上限与流量统计口径全部零改动。实测 1920 宽下 `innerHeight` 1080 / 960 / 900 / 860 / 820 / 768 对应绘图区 307 / 247 / 217 / 197 / 177 / 151px、等分数 5 / 4 / 3 / 3 / 3 / 3、刻度数 6 / 5 / 4 / 4 / 4 / 4，两卡逐档一致且顶端刻度 `y=14`；手机 / 平板（<901px）共享值清 0、`yTickCount()` 自动回落到 v42 及以前的 6 等分（7 个值），与 v47 逐项零改动。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v48.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v47 包逐文件哈希比对，仅 `app/static/charts.js` / `app/static/app.js` / `app/static/style.css` / `app/pwa/sw.js` / `docker-compose.offline.yml` / `README.md` 变化，`index.html` / 后端 `app/*.py` 逐文件**零改动**。真实 Chromium 桌面 1920×1080 / 1600×900、平板 900、手机 390×844（深 / 浅主题）逐项核对：两个范围菜单固定 184px / 可见 5 项 / 单项 30px / sticky 标题 26px / 默认滚动条 / 滚到底最后一项可达，手机端与桌面端逐项一致、桌面端相对 v47 零改动；桌面 6 档可用高度下刻度数按绘图区高度 5→3 等分自适应、两卡一致且等于共享值 +1、顶端最大值刻度 `y=14` 必现，运行时改窗口高度实时跟随、单独重绘一卡仍一致；手机 / 平板仍 6 等分、绘图区 380 / 480px 与 v47 逐项一致。重跑 v47（158/158）、v46（44/44）、v45（103/103）、v44（86/86）、v43（83/83）全部历史回归均通过。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v48`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：只提供 v48 的 `.tar` / `.zip`；随包仍保留《安全加固与重新部署指南-v35.md》及《同类项目对比与安全审查-v34.md》《流量统计口径深度解析-v15.md》两份历史报告。

> 本次 `torrent-traffic-monitor-image-amd64-v48.tar` 的 SHA256：`3cd7333952027c480238ef7be70757c8ff2e03153e1a298e34626285b17c3ed0`

### v47

> 本轮两处纯外观微调：**顶栏右侧两枚胶囊按钮去掉图标改纯文字、缩短并严格等宽、中间留白加宽**，以及**桌面端顶部项目图标适当调小一点，不再顶满最上面一行**。胶囊改动桌面端与手机端一并生效，图标只动桌面端（`≥901px`）。全部是 `index.html` / `app.js` / `style.css` 前端改动，**无数据库迁移**、**后端 `app/*.py` 与 `charts.js` 零改动**、流量统计口径沿用 v15 零改动。

| 需求 | 实现 |
|---|---|
| **1. 顶栏两枚胶囊：去图标 / 缩短 / 等宽 / 加大间距（桌面 + 手机端）** | `index.html` 里 `<span class="pill-txt">● 采集中</span>` 与 `<span class="pill-txt">⚙ 设置</span>` 分别改为纯文字「采集中」「设置」，只保留文字本体。`app.js` 的 `setHealth()` 同步去掉动态拼接的 `'● ' + text` 前缀（否则运行时圆点会被重新写回），改为只写文字本体，兼容旧缓存 HTML 的分支一并处理；状态色仍由 `.bad` class 控制，与圆点无关。`style.css` 让两枚胶囊共用**同一个 `min-width:60px`**（基础 `.pill` 由 `76px`、手机断点由 `66px` 统一改为 `60px`）—— 删图标后「采集中」3 个字与「设置」2 个字字数不同，靠 `min-width` 兜底两枚都恰好 60px，真实 Chromium 实测桌面 1920/1600、平板 900、手机 390 四档**常态严格等宽**、较原来缩短 16 / 6px；异常长文案（如「等待首轮采集」）仍按既有 `min-width` 机制自然撑开、`white-space:nowrap` 不裁切，行为零回归。`.top-actions` 两按钮间距由 `9px`（桌面 / 平板）/ `6px`（手机）适当加宽到 `14px` / `10px`，视觉更平衡。v45 引入的 `.pill-txt` + `text-box-trim` 字形居中方案完整保留，删掉图标后纯中文 ink 上下 / 左右偏差实测 0.0px（比带图标时更居中）。 |
| **2. 桌面端顶部项目图标适当调小（仅桌面端）** | `≥901px` 桌面端此前为「一页展现」把 `.topbar` 上下内边距压到 `4px`，而 `.topbar .logo` 仍是 `30px`，加上上下各 4px 后整行 39px、30px 图标几乎顶满整行高度。v47 只改这一处：`.topbar .logo` 由 `30px` 调到 **`26px`**（`font-size:18→16px`、`border-radius:9→8px`），整行高度 39→35px，图标上下各留出呼吸空间、不再顶死；顶部标题、胶囊高度、主内容布局均不改动，v43 的 `fitDesktopCharts()` 按 `innerHeight` 动态分配绘图区高度的逻辑不受影响。手机端（≤560px）.logo `30px` 与平板 / 通用基础 `.logo` `38px`、`radius` 等**逐项零改动**，实测手机 / 平板 logo 尺寸与 v46 完全一致。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v47.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v46 包逐文件哈希比对，仅 `index.html` / `app.js` / `style.css` / `app/pwa/sw.js` / `docker-compose.offline.yml` / `README.md` 变化，`charts.js` / 后端 `app/*.py` 逐文件**零改动**。真实 Chromium 桌面 1920×1080 / 1600×900、平板 900、手机 390×844（深 / 浅主题）逐项核对：两枚胶囊纯文字无 `●` / `⚙`、常态严格等宽 60px、间距 14 / 10px、桌面 logo 26px / 顶栏 35px、手机与平板 logo 尺寸逐项零改动、按钮文字 ink 上下 / 左右居中、异常长文案撑开且不裁切、`setHealth()` 动态更新仍兼容 `.pill-txt`。重跑 v46 全量验证（38/38）、v45 全量回归（91/91）、v44（80/80）、v43（83/83）全部通过。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v47`。**流量统计口径沿用 v15，零改动**。

### v46

> 本轮两件小事：**删除主页底部那句说明文案**（桌面端 / 手机端一并删），以及**把桌面端两个「时间范围」弹出框的竖向滚动条样式改成和顶部四小卡片「历史数据」弹出框完全一致**。两处都是纯前端样式 / DOM 精简（`index.html` / `style.css`），**无数据库迁移**、**后端与 `charts.js` 零改动**、流量统计口径沿用 v15 零改动。

| 需求 | 实现 |
|---|---|
| **1. 删除主页底部「单容器 · SQLite · 零外部依赖 · 数据保存在 data/traffic.db」** | `index.html` 里 `</main>` 前那一行 `<footer class="footer">…</footer>` 直接删除；桌面端与手机端共用同一份 DOM，一句删除两端同时生效。`style.css` 里 3 处 `.footer` 规则（第 329 行基础样式、手机断点 `padding:6px 0 0`、桌面断点 `padding:1px 0 0`）随元素一起清理，不留死规则。v43 的 `fitDesktopCharts()` 以 `document.querySelector('main').getBoundingClientRect().bottom` 作为「真实内容底边」，删掉页脚后 `main` 自然变矮、`fixedH` 减小，两个绘图区平分的可用高度相应多出一行，**一页展现 / 两卡等高 / 4 等分刻度逻辑逐项不受影响**；登录层、设置页里其它含「单容器 / SQLite」字样的说明文案均**不在本次范围**，保持原样。 |
| **2. 两个「时间范围」弹出框的竖向滚动条与顶部小卡片弹出框统一** | 根因：v44 为桌面端（≥901px）「时间范围（单选）」弹出框做固定 5 项高度 + 内部滚动时，额外给 `#rateRangeMenu` / `#trafficRangeMenu` 加了 `::-webkit-scrollbar` 自定义滚动条（`width:9px`、track 透明、thumb `rgba(148,163,184,.55)` + `border-radius:8px`），而顶部四小卡片「历史数据」弹出框的滚动容器 `.hist-list` 从未自定义，用的是**浏览器默认滚动条**，于是两个位置的滚动条一个粗一个细、样式明显不同。**v46 删除这 3 条 `::-webkit-scrollbar` 规则**（`width` / `track` / `thumb`），也不引入 `scrollbar-width` / `scrollbar-color`，让两个范围菜单回落到与 `.hist-list` 同源的浏览器默认滚动条。真实 Chromium 计算样式实测：v45 里范围菜单 `::-webkit-scrollbar` 为 `9px` / thumb `rgba(148,163,184,0.55)` / 圆角 `8px`，而顶部小卡片是 `auto` / 透明 / `0px`；**v46 两处 `scrollbar width` / `thumb background` / `thumb radius` / `scrollbar-width` / `scrollbar-color` 全部逐项相等**。`--dd-opt-h:30px`、标题 `sticky`、`max-height:5×30+26+8`、右侧竖滚动条滚动展现、以及手机端（≤900px）弹出框 DOM / 样式 / 行为**全部保持 v44 原样**，只统一滚动条外观。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v46.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v45 包逐文件哈希比对，仅 `index.html` / `style.css` / `app/pwa/sw.js` / `docker-compose.offline.yml` / `README.md` 变化，`app.js` / `charts.js` / 后端 `app/*.py` 逐文件**零改动**。真实 Chromium 桌面 1920×1080 与手机 390×844 逐项核对：`.footer` 元素在两端均不存在、那句文案全站无残留、页面其余内容 / 布局无位移；两个范围菜单与顶部小卡片历史弹出框的滚动条计算样式逐项相等（v45 基线不相等），范围菜单仍固定 5 项高度、`sticky` 标题常驻、内容可滚动到底全部可达，手机端弹出框逐项零改动。重跑 v45 全量验证（91/91）、v44 全量回归（80/80）、v43 全量回归（83/83）全部通过。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v46`。**流量统计口径沿用 v15，零改动**。

### v45

> 本轮两件事：**桌面端「运行状态」卡片恢复按正常顺序 / 宽度排版**，以及**桌面端与手机端全站按钮文字统一上下、左右居中**。两处都是纯前端（`index.html` / `app.js` / `style.css`），**手机端「运行状态」分组布局逐项零改动**，**无数据库迁移**，流量统计口径沿用 v15 零改动。

| 需求 | 实现 |
|---|---|
| **1. 桌面端「运行状态」不再强制固定前两行卡片，按正常顺序宽度排版** | v39 为了让手机端第二行「实时速率采样间隔 / 流量统计采样间隔」与第三行「实时速率采样轮次 / 流量统计采样轮次」上下对应，把前 4 张卡片拆进 `#aboutLead` 并固定成 `repeat(2, minmax(0,1fr))` 的 2 列网格、其余 5 张仍留在 `#aboutInfo` 的 `auto-fit` 网格 —— 这个分组被同步到了桌面端，桌面端就变成「前 4 张各占半屏宽 + 后 5 张挤成一行」，卡片宽度明显不一致。**v45 在 `renderAbout()` 里按 `FIT_MQ`（`min-width:901px`）分流**：桌面端把 `#aboutLead` 清空并 `hidden`，9 张卡片按原始顺序全部渲染进 `#aboutInfo` 的同一个 `repeat(auto-fit, minmax(150px,1fr))` 网格，按容器宽度自动换行、每张等宽；手机 / 平板（<901px）仍走原两容器分组，第二行与第三行继续上下对应、逐项零改动。同时在 `installFitWatchers()` 的 901px 断点 `change` 回调里补一次 `renderAbout()`，窗口跨断点时实时重排（与 v43 绘图区高度重算共用同一个监听器）。无数据时也会把 `#aboutLead` 复位，避免切回手机端留下隐藏容器。 |
| **2. 桌面端 + 手机端全部按钮文字上下 / 左右居中** | 逐项核对主界面、设置 5 个分页、登录层、单台 / 汇总 / 测试 / 调色板弹窗、回到最新按钮等全部按钮：原先只有一部分是 `inline-flex` + `align-items:center` + `justify-content:center`，登录「登录」/「⟲ 回到最新」/ 调色板 HSV·RGB 标签 /「完成」/ 各弹窗「✕ 关闭」仍是 `inline-block` 或 `block`，靠 `text-align` + `padding` 排版，字高与上下留白不严格对称。`style.css` 新增一条统一规则，把上述按钮类改为 `inline-flex` + `align-items:center` + `justify-content:center` 并补齐 `text-align:center` / `vertical-align:middle`；**只改排布方式，不动 font-size / line-height / padding / width / height / min-height**，所有按钮盒子尺寸逐像素不变。`.dd-trigger` / `.card-dd-trigger` 内部是「文字 + ▾」两端对齐，保留 `justify-content:space-between` 只统一垂直居中；外观设置页两枚带颜色方块的 `.theme-choice` 用户已确认无此问题，**显式排除、零改动**。顶部两枚胶囊另把文字包成 `.pill-txt` 独立块，先由 `.pill` 的 flex 精确居中，再用 `@supports (text-box-trim: trim-both)` 渐进增强：`text-box-trim:trim-both` + `text-box-edge:cap alphabetic` 按当前系统字形的 cap / alphabetic 边界裁掉多余 leading，让**可见字形本身**精确上下居中（按字体自适应，不写死补偿像素，兼容中英文 / emoji 混排的不同字体）；不支持该特性的浏览器回退到 `line-height:1` + flex 居中，胶囊盒尺寸不变。`setHealth()` 同步改为只更新 `.pill-txt` 的文字，并兼容旧版缓存 HTML。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v45.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v44 包逐文件哈希比对，仅 `index.html` / `app.js` / `style.css` / `app/pwa/sw.js` / `docker-compose.offline.yml` / `README.md` 变化，后端 `app/*.py` 与 `charts.js` 逐文件零改动。真实 Chromium 逐项核对桌面 1920×1080 与手机 390×844 的全部按钮：统一后所有按钮均为 `inline-flex` + `align-items:center` + `justify-content:center`（下拉触发器为 `space-between`）、左右文字边界偏差 `hDiff≈0`、盒子尺寸 / 行高 / 内边距与 v44 逐像素一致；两枚胶囊文字 ink 上下偏差由 **1.25px 收敛到 0.25px**（4 倍像素实测），深色 / 浅色主题一致。桌面端「运行状态」9 张卡片落在同一 `auto-fit` 网格、顺序正确、每张等宽、`#aboutLead` 隐藏；手机端仍为 v39 的 2 列分组、第二 / 三行上下对应，与 v44 逐项一致；跨 901px 断点实时重排通过。**v45 全量验证 91/91 通过**，重跑 v44 全量回归 **80/80** 与 v43 全量回归 **83/83** 通过（时间范围弹出框 / 汇总线口径 / 桌面一页展现 / 两卡等高 / 4 等分刻度零回归）。附两张效果图：`v45-changes-compare.png`（桌面运行状态 / 顶栏胶囊 / 手机端三组合对比）与 `desktop-about-v45.png`（桌面运行状态卡片区放大）。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v45`。**流量统计口径沿用 v15，零改动**。

### v44

> 本轮两件事：**桌面端时间范围弹出框固定高度 + 内部滚动**，以及**修复实时速率曲线「汇总速度低于下载器速度之和」的偶发 bug**。需求 1 是纯桌面端 CSS（手机端零改动）；需求 2 的根因在后端 `chart.py` 的插值与前端 `app.js` 的降采样两处「汇总线与各下载器线各自独立处理」，修复后汇总线恒等于各下载器线之和。**无数据库迁移**，流量统计口径沿用 v15 零改动。

| 需求 | 实现 |
|---|---|
| **1. 桌面端时间范围弹出框固定 5 个可选项高度 + 右侧竖向滚动条** | `style.css` 在 `@media (min-width:901px)` 块内用 id 精确限定 `#rateRangeMenu` / `#trafficRangeMenu`：单个可选项固定 **30px**、标题「时间范围（单选）」固定 **26px** 且 `position:sticky` 常驻顶部、菜单 `max-height = 5×30 + 26 + 下内边距 6 + 边框 2 = 184px`（`border-box`）、`overflow-y:auto` + 自定义 `::-webkit-scrollbar` 明显滚动条（不设 `scrollbar-width` / `scrollbar-color`，避免标准属性压制自定义滚动条）。于是弹出框恰好**完整显示 5 个可选项**，速率卡片 12 档 / 流量卡片 11 档中剩余选项通过弹出框右侧竖向滚动条滚动展现、滚动到底最后一项可达，单选交互与其它下拉（方向 / 顶部卡片历史）不受影响。用 id 限定 + 仅 ≥901px 生效，**手机端（≤900px）DOM / 样式 / 行为逐项零改动**（仍为原 380px 上限、12/11 项全展开、不滚动）。 |
| **2. 修复「汇总速度低于下载器速度之和」（5 台有 1 台有速度、汇总却是 0）** | 根因是汇总线与各下载器线在两处被**各自独立处理**、破坏「汇总 = 各下载器之和」：① 后端 `chart.py` 的 `_fill_rate_gaps()` 对汇总线也独立线性插值 —— 汇总线因「总有下载器写了 0 速率」而处处有值、不会被插值，个别下载器偶发漏采的桶却被线性插值补上速度，该桶就出现「汇总 0 < 单下载器 100」；② 前端 `app.js` 的 `downsample()` 在 avg 模式对每条线独立窗口平均，各下载器采样落在不同桶 / 0 值桶把汇总 avg 稀释（跨界面窗口实测汇总 100 < 各下载器之和 200）。修复：后端只对**各下载器线**插值，汇总线随后按各下载器线**逐点重新求和**（就地覆盖，保持 `sum_up` / `sum_down` 的同一列表引用让 `summary` 峰值同步）；前端降采样后同样按各下载器线逐点重算汇总线。两处都保证「汇总线恒等于各下载器线之和」，全 None 的点仍保持 None（v21 头 / 尾留白语义不变）。`traffic` 的 sum 模式本就线性、不受影响。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v44.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v43 包逐文件哈希比对，仅 `chart.py` / `app.js` / `style.css` 三个源码文件变化。后端构造临时 DB 复现「5 台仅 1 台有速度 + 漏采」：修复前 `live` 桶 20 出现「汇总 0.0 < D3 100.0」，修复后 **0 处违反**；四种场景（漏采 / 活跃时段不同 / 5 台都有速度 / 头尾大缺口）× 四个范围（live / 1h / 6h / 12h）共 **16/16** 组「汇总线逐点 = 各下载器线之和」与 `summary` 峰值同步全部通过。真实 Chromium **80/80 项通过**：桌面 1440 / 1920 / 1200 三档两卡弹出框均固定 184px、恰好 5 项完整可见、单项 30px、右侧滚动条（`scrollHeight 392 / 362 > clientHeight 182`）、12/11 档单选 value 唯一且滚动到底可达、≤900px 不生效、方向 / 历史下拉不受影响；**手机 390×844 与 v43 逐项完全一致**（8 项 computed style / 几何全同）；`downsample('avg')` 汇总线不变量 0 违反、跨界面窗口汇总由旧逻辑稀释值 100 变为正确的 200、`traffic/sum` 与 `n<=M` 分支同步通过。重跑 v43 全量验证 **83/83** 通过，桌面一页展现 / 两卡等高 / 4 等分刻度 / 手机端零回归。附两张效果图：`desktop-range-menu-v44.png`（全页、弹出框打开）与 `range-menu-scroll-demo-v44.png`（初始 5 项 / 滚动到底对比）。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v44`。**流量统计口径沿用 v15，零改动**。

### v43

> 本轮**继续纯桌面端调整（手机端零改动）**，修正 v42「写死绘图区 240px」在真实浏览器里仍超出一屏的问题。核心是：**1920×1080 是屏幕物理分辨率，浏览器标签栏 / 地址栏 / 书签栏 + 操作系统任务栏会占掉一大截，页面真正可用的 `window.innerHeight` 远小于 1080**；v42 只在 `innerHeight≈1080` 的理想视口下刚好放下，真实窗口（约 820~960px）必然出现纵向滚动条。v43 改为**运行时先检查实际可用高度、再实时按这个高度调节**两张卡片的绘图区高度；同时再压缩顶栏 / 四张小卡 / 绘图区↔图例距离 / 图例行间距等留白，并把两卡纵坐标**固定 4 个刻度（不含 0）**。改动只落在前端 `app.js` / `charts.js` / `style.css`，后端 `app/*.py` 逐文件零改动，**不涉及数据库迁移**。

| 需求 | 实现 |
|---|---|
| **1. 先检查实际可用高度，再实时动态调节绘图区** | `app.js` 新增 `fitDesktopCharts()`：运行时读 **`window.innerHeight`**（浏览器内容区真实可用高度，已扣除标签栏 / 地址栏 / 书签栏 / 系统任务栏），用 `main` 底边 + 滚动偏移算出文档真实内容底边，减去两个绘图区当前高度得到「固定内容高度」，再按 `(innerHeight - 16px 安全余量 - 固定内容高度) / 2` 平分给两卡绘图区，用 inline `height` 覆盖 CSS 回退值并触发两卡重绘。**不写死任何 px**：窗口 / 可用高度一变就重算 —— 监听 `window.resize`、`visualViewport.resize`、`matchMedia('(min-width:901px)').change` 与 `ResizeObserver`（`main` / 汇总卡 / 下载器卡片 / 两张图例 / 区间小卡），rAF 防抖；`fitDesktopCharts` 用「与当前高度差 ≤1px 不改动」打断观察器回环，稳定后不再重绘。实测 `innerHeight - 2×绘图区高` 在 1080 / 960 / 900 / 860 / 820 / 768 六档恒为 **486px**，绘图区高度依次为 297 / 237 / 207 / 187 / 167 / 141px，**六档全部无纵向滚动条**、内容底边各留 16px 余量；运行时同一页面把窗口高度 960→860→1080→820 改一遍，绘图区实时变为 237→187→297→167px。仅桌面端（≥901px）启用，≤900px 清除 inline 交还 CSS 的 480 / 380px。 |
| **2. 继续压缩留白，把空间让给两个主绘图区** | `style.css` 的 `@media (min-width:901px)` 块在 v42 基础上再收紧：顶栏 padding 7→**4px**、logo 38→**30px**、胶囊 34→**26px**、标题 17→15px；`main` 上下 9/12→**6/8px**；`.panel` 内边距 8/12→**6/12px**、卡片间距 7→**5px**、面板标题 `margin-bottom` 5→**3px**、标题 15→14px；四张汇总小卡 `gap` 6→**4px**、`padding` 4→**2px**、标题行 `min-height` 24→**18px**、数值行 `margin-top` 3→**1px**；下载器卡片 `gap` 4→**3px**、`.dl-chip` padding 3/7→**2/7px**；控件行 `margin-bottom` 5→**3px**、下拉 26→**24px**；「区间上传 / 下载」小卡 padding 5/10→**3/10px**、数值 15→14px；**绘图区 ↔ 图例文字距离 `margin-top` 4→1px**、**图例本身行间距 `row-gap` 4→1px**、图例项 `line-height` 1.5→**1.25**；页脚 padding 3→**1px**。 |
| **3. 两卡纵坐标固定 4 个刻度（不含 0）** | `charts.js` 把 v42 的「按绘图区高度自适应 `yTickCount(h)`」改为**按视口宽度固定**：桌面（≥901px，与 CSS 断点一致）`yTickCount()` 返回 **4** —— `plotMax` 4 等分得 `0 / ¼ / ½ / ¾ / max` 共 5 个刻度值，**0 之外正好 4 个**；手机 / 平板（<901px）仍返回 6（7 个值）逐字不变。两卡共用 `computeScale`，**刻度数量必然一致**；`ticks` 最高项恒为 `plotMax`，仍画在 `y = pad.t`，**顶端最大值刻度必现**。`gridYMarkup` / `ticksYMarkup` / `makePad` 按当前等分数逐条绘制与留白，`Y_FILL` / 绘图映射 / 数值口径零改动。 |
| **4. 两卡绘图区高度一致** | 两卡共用同一套 `.chart-lg` 与同一个动态计算结果（`fitDesktopCharts` 对 4 个 `.chart-lg` 宿主统一设同一 `height`），**绘图区严格等高**；`charts.js` 的 `prep()` 按宿主实际高度重建 SVG `viewBox`，刻度密度与柱状几何随高度自适应。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v43.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v42 包逐文件哈希比对，仅 `app.js` / `charts.js` / `style.css` 三个前端文件变化，后端 `app/*.py` 逐文件零改动。真实 Chromium **83/83 项通过**：桌面六档可用高度（1080 / 960 / 900 / 860 / 820 / 768）全部无滚动条、两卡绘图区等高、`innerHeight - 2×绘图区高` 恒为 486px、Y 刻度固定 5 个值（`1.02 TB / 780.73 GB / 520.48 GB / 260.24 GB / 0 B`）且两卡一致、顶端 `1.02 TB` / `1.02 TB/s` 落在 `y = pad.t` 必现；运行时改窗口高度图表实时跟随；v42 对照在 `innerHeight=820` 下内容 1043px 确实超出；桌面 11 项 computed style 留白均较 v42 收紧；**手机 390×844 与 v42 逐项完全一致**（绘图区 380px、Y 刻度 7 个值、14 项区块高度、图例间距、柱状几何全部相同、无 inline 高度覆盖）；1080×1920 竖屏无滚动条。附两张效果图：`desktop-1920x900-v43.png`（模拟真实浏览器窗口可用高度 900px）与 `desktop-1920x1080-v43.png`（全屏视口）。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v43`。**流量统计口径沿用 v15，零改动**。

### v42

> 本轮为**纯桌面端布局调整（手机端零改动）**：把实时速率与流量统计两张卡片的**绘图区高度**从 560px 下调到 240px，并适度收紧顶栏标题行、四张汇总小卡、下载器卡片、流量统计的「区间上传 / 下载」小卡的行距与边框留白、卡片之间的留白，删除下载器卡片标题下的说明文字，把腾出的空间尽量留给两个主绘图区 —— **1920×1080 桌面一页即可完整展现整个页面、不再出现纵向滚动条**。两卡共用 `.chart-lg`，**绘图区高度严格一致**；绘图区变矮后按高度自适应**适当减少纵坐标刻度数量**，**两卡刻度数量一致、最顶端纵坐标（最大值刻度）仍必现**。改动只落在前端 `style.css` / `charts.js` / `index.html`，后端 `app/*.py` 逐文件零改动，**不涉及数据库迁移**。

| 需求 | 实现 |
|---|---|
| **1. 两个卡片绘图区高度下调且一致** | `style.css` 新增 `@media (min-width:901px)` 块，把 `.chart-lg` 由 560px 改为 **240px**（绘图区 `h - pad.t - pad.b = 198px`）。两张卡片共用同一个类，绘图区高度严格相等；`≤900px` 的 480px 与手机端 380px **一律不动**（媒体查询不重叠，手机端零改动）。 |
| **1b. 纵坐标刻度适当减少、两卡一致、顶端必现** | `charts.js` 把固定 `Y_TICKS = 6` 改为按绘图区实际高度自适应：新增 `yTickCount(h)` —— 高度 ≥380px（手机 380 / 平板 480 / 旧桌面 560）恒保持 **6 等分**（手机端逐字不变）；只有 v42 的桌面矮绘图区按「相邻刻度净间距 ≥36px（桌面 11px 字体约 3 倍行高）」减少等分数，最少 2 等分。240px → `plotH = 198` → **5 等分（6 个刻度值，比手机少一档）**。`computeScale(v, floor, h)` 接收两卡各自的容器高度（`drawLines` 用 `cv.getBoundingClientRect().height`、`drawBars` 用 `prep()` 的 `h`），两卡高度相同 ⇒ **刻度数量必然一致**；`ticks` 最高一项恒为 `plotMax`，`gridYMarkup` / `ticksYMarkup` 仍把它画在绘图区顶部 `y = pad.t`，**顶端纵坐标必现**。`makePad` 按实际刻度量文字宽度留白，`Y_FILL` / 绘图映射 / 数值口径零改动。 |
| **2. 压缩其它区域留白，把空间让给绘图区** | 同一个 `@media (min-width:901px)` 块内收紧：顶栏 `padding` 12→7px；`main` 上下留白 16/28→9/12px；`.panel` 内边距 12/14→8/12px、卡片间距 12→7px；面板标题行 `margin-bottom` 9→5px、标题 `line-height` 1.5→1.3；四张汇总小卡 `padding` 7/9→4/9px、`margin-bottom` / `gap` 9/8→6/6px、数值行 `margin-top` 6→3px；下载器卡片 `gap` 7→4px、`.dl-chip` 上下 `gap` 2→1px、`padding` 5/8→3/7px；控件行 `margin-bottom` 8→5px、下拉触发高度 30→26px；「区间上传 / 下载」小卡 `padding` 8/10→5/10px、数值字号 17→15px、`margin-bottom` 8→5px；图例 `margin-top` 6→4px；页脚 `padding` 6→3px。 |
| **2b. 删除下载器卡片第二行说明文字** | `index.html` 删掉下载器面板标题下那段「单击任一卡片查看详情…名称完整显示、类型/在线标签在右下角」的 `<p class="hint">`。该段在手机端本就由 `@media (max-width:560px)` 隐藏，删除后**手机端视觉零变化**；桌面端少占一行，进一步腾出高度。 |
| **3. 1080p 一页完整展现、无滚动条** | 真实 Chromium 1920×1080 完整页面（5 台下载器、两卡均有数据）实测：v41 内容高 **1851px**（需滚动），v42 压到 **1043px**、`scrollHeight = innerHeight = 1080`，**无纵向滚动条**、余量约 37px；1080×1920 竖屏同样无滚动条。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v42.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；相对 v41 包逐文件哈希比对，仅 `index.html` / `charts.js` / `style.css` 三个前端文件变化，后端零改动。真实 Chromium **34/34 项通过**：桌面 1920×1080 无滚动条、两卡绘图区均 240px、Y 刻度数均 6 个值（v41 为 7）、顶端刻度 `1.02 TB` / `1.02 TB/s` 落在 `y = pad.t` 必现、说明文字已删、四类区块高度确实收紧；**手机 390×844 与 v41 逐项完全一致**（绘图区 380px、Y 刻度 7 个值、顶端刻度、14 项区块高度、柱状几何 `bw / gap / groupW / padT / padB` 全部相同）；1080×1920 竖屏同样无滚动条。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v42`。**流量统计口径沿用 v15，零改动**。

### v41

> 本轮按使用反馈修正**流量统计卡片的数据点取数逻辑**：① 「本月 / 上月」在手机端被前端按画布宽度抽稀成固定 12 组、中间日期数据被合并吞掉；② 「全部」范围按数据库跨度给出合适的自然日历粒度。**后端 `app/chart.py` 新增「全部」流量图的自然日 / 月 / 季度 / 年分桶**（速率图「全部」保持原自适应小时桶不变），**前端 `app.js` 对三个范围豁免降采样**、`charts.js` 柱宽下限 2px→3px。数值口径（累计计数器差值 / SUM 字节 / `spans` / `window`）沿用既有实现，`traffic` 采样类与其它自然周期分桶零改动。**不涉及数据库 schema 迁移**，历史数据完全兼容，升级只需替换镜像重新 `docker load -i` / compose 部署。

| 需求 | 实现 |
|---|---|
| **1. 本月 / 上月数据点设置逻辑（桌面 + 手机）** | **根因**：后端 `_traffic_period()` 早已是「本月＝`local.day` 个点（1~31，按当前日号递增）、上月＝`(first-lm).days` 个点（该月实际天数 28~31）」的按天分桶、每天一组上传 / 下载柱；但 `app.js` 的 `targetPoints('traffic')` 下限写死 **12**，`renderChart()` 又对所有非 live 的 traffic 走 `downsample(data, maxPts, 'sum')` —— 手机端画布窄、`maxPts=12`，于是 28~31 个日桶被均匀合并成 12 组，**中间日期的数据被求和吞掉、不再单独展示**。`renderChart()` 新增 `KEEP_ALL`：`traffic` 且 `range ∈ {month, lastmonth, all}` 时把目标点数抬到 `data.labels.length`，`downsample` 的 `n <= M` 分支直接原样返回，桌面 / 手机统一零降采样。其余范围（今日 / 昨日 / 实时等）仍走原抽稀口径，后端本月 / 上月分桶零改动。 |
| **1b. 点密时柱子缩窄，最窄 3px；留白与刻度标准不变** | `charts.js` 的 `drawBars()` 把柱宽下限 `Math.max(2, …)` 改为 **`Math.max(3, …)`**：点密（如手机端上月 31 组）时 `groupW` 变小，`ratio / cap / room` 公式会自动把柱子缩窄，最窄保留 **3px** 保证可见。**「两个柱组之间的留白保持现有标准」**＝ v36 的 `(groupW-4)/2` 硬上限与 `room` 公式、组内 `gap = min(3, groupW*.06)` 一律不动；**「横坐标刻度密度保持现有标准」**＝ `axisXMarkup()` 的 `2.5 * digitW` 净空白抽稀逻辑不动，点密时按同一标准自动少放几个刻度（首尾仍无条件必现）。仅改柱宽下限，不为了塞点数去压缩留白或减少刻度。 |
| **2. 「全部」范围自适应自然粒度** | `_buckets()` 对 `all` 按 `metric` 分派：`metric=traffic` 走新增的 `_all_traffic_buckets()`，`metric=rate` 仍走 `_all_buckets()` 自适应小时桶（保持 v32「点数给足」的折线密度，实测 115~120 点不变）。新函数按 `db_min_ts` → 当前时刻的跨度算「自然天数 / 自然月数 / 自然季度数」，阈值**严格大于**且级联覆盖取最粗：默认 **自然日**；`days > 30` → **自然月**；`months > 24` → **自然季度**；`quarters > 20` → **自然年**。各档点数上限恰好 30 / 24 / 20。桶按自然日历边界切分（本地墙上时间），月 / 季度 / 年不等宽，`seconds` 取相邻边界真实差值；`build()` 新增 `hourly-all-natural` 分支，按 `hourly` 表冗余 `day` 列 `GROUP BY` 后用二分把每天映射到所属自然单位桶并 `SUM` 字节。标签分别为 `MM-DD` / `yy/mm` / `yyQn` / `YYYY`，`window.label` 起点对齐自然单位首日、终点夹到当前时刻。 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v41.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过。后端用临时 DB 逐档核实：10 天 / 恰好 30 天 → 日粒度（10 / 30 点）、31 天 / 10 个月 / 恰好 24 个月 → 月粒度、25 个月 / 恰好 20 季度 → 季度粒度、21 季度 / 跨 8 年 → 年粒度，`count_only` 与完整桶数一致、桶边界连续；`chart.build('all','traffic')` 四种粒度的 `bucket_count` / 标签 / SQL 聚合数值（汇总 999 / 1332）/ `window.label` 全部正确，`chart.build('all','rate')` 仍为 115~120 点、未受影响。真实 Chromium 无头渲染 **35/35 项通过**：手机端 v40 会把本月 14 天 / 上月 31 天 / 全部 30 组都合并成 12 组，v41 逐一保留 14 / 31 / 30 / 24 / 20 / 7 个数据点，桌面端同样保留；点密时柱宽实测恰好 3px、组间留白 2.5~3.3px > 0、组内间隙保持 `min(3, groupW*.06)`、X 轴刻度净空白 ≥ 2.5 数字字符且首尾必现；点少时柱子仍正常调宽。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 返回 `{"ok":true}`。SW 缓存升到 `ttm-shell-v41`。**流量统计口径沿用 v15，零改动**。

### v40

> 本轮按使用反馈做 **3 项纯前端 UI 调整**：流量统计柱状图横坐标刻度语义、桌面端主界面铺满与下载器卡片自适应排版、两张卡片 X 轴刻度净空白收紧。**后端 Python（`app/chart.py` 等）逐文件零改动** —— 分桶 / 聚合 / 累计计数器差值 / `spans` / `window` / `series` 数值口径完全不变，改的只是「展示用文字」与 CSS；`style.css` 沿用 v37 归并成果继续**就地修改**、在既有断点块内调整，不在末尾追加同名覆盖。**不涉及数据库 schema 迁移**，历史数据完全兼容，升级只需替换镜像重新 `docker load -i` / compose 部署（步骤见下方「3. 启动」与本节的 compose 提示）；v35 引入的《安全加固与重新部署指南-v35.md》安全内容与部署步骤本轮未变、继续适用。

| 需求 | 实现 |
|---|---|
| **1. 流量统计卡片横坐标＝时间段中间时刻** | 每组上传 / 下载柱覆盖一个时间桶 `spans[i]=[a,b)`，而 `charts.js` 的柱状图刻度按**柱组中心** `X(i)=pad.l+plotW*((i+.5)/n)` 定位、落在两柱正下方居中；此前文字用「桶起点 `a`」，与居中位置语义不符。`app.js` 新增 `fmtSpanMid(sp)` 取 `(a+b)/2` 作为刻度文字（中点落在整分钟输出 `HH:MM`，桶宽使中点带半分 / 秒时补秒输出 `HH:MM:SS`，保证是真实中点、不抹成 `x:02`）。**仅对「时间段」类范围生效**（`NATURAL_RANGES` 之外：实时 / 1 / 6 / 12 小时 / 今日 / 昨日），周 / 月 / 年 / 全部是「某一个日期」标签、整天取中间无意义，保持原日期刻度。**首 / 尾两个刻度是明确例外**：仍「优先对齐当前选择时间范围的首尾时间」——直接用区间文字 `window.label` 的两端覆盖中间时刻，与实时速率卡片的 `edges`、左上角范围文字逐字一致（≤24h 同样去掉 `MM-DD` 前缀）；`n===1` 只有一个柱组时首尾同刻度，保留中间时刻更贴合居中语义。`labels`（tooltip 标题）与 `tipTitles`（时间段标题）、`spans`、分桶、聚合一律不动 |
| **2. 桌面端主界面铺满 + 下载器卡片自适应列数** | ① `main{max-width:1480px;margin:0 auto}` 是宽屏左右几百像素空白的病根，改为 `max-width:none` 横向铺满；左右「正常留白」由 `main` / `.topbar` 的 `padding:… clamp(18px,1.4vw,36px) …` 提供，随屏宽平滑增大且顶栏与内容对齐，窄屏仍由 900 / 560 断点覆盖成 11 / 9px。② `.dl-row-items` 由「死死卡住一行 2 个」的 `repeat(2,minmax(0,1fr))` 改为 `repeat(auto-fit,minmax(300px,1fr))`：桌面按容器宽度自动增减列数、空列折叠后 `1fr` 均分，既铺满又不留半屏空白；**300px 保底列宽**保证每张小卡的名称 / ↑↓ 完整速率 / 类型标签都有位置，`fitChipNames()` 的缩字号 / 换行兜底仍在，绝不因位置不够而省略或裁切。③ 在既有 `@media (max-width:1200px)` 块内恢复固定 2 列（手机 `@media (max-width:560px)` 本就是 2 列），保证中等 / 窄屏排版零退化。汇总卡独占一行，不受影响 |
| **3. 图例 X 轴刻度净空白 4 → 2.5 个数字字符** | `charts.js` 的 `axisXMarkup()` 里 `gap = 4 * digitW`（`digitW = measureText('0')` 实测宽度）改为 **`2.5 * digitW`**。该 `gap` 同时用于 `unit` 占位估算、极窄屏退化判定与中间刻度贪心避让，改一处即折线 / 柱状两张卡片同时生效；在守住清晰度下限的前提下尽量多放几个横坐标刻度。同步更新相关注释，历史行为（首尾必现、按净空白贪心、极窄屏安全退化）全部保留 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v40.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：`node --check` 三份 JS、`python -m py_compile` 全部后端模块语法通过；后端 `app/*.py` 与 v39 逐文件哈希一致（数值口径零改动，v35↔v39 的 216 / 48 组图表数值回归结论沿用）。真实 Chromium 无头渲染逐项验证：流量统计「时间段」范围刻度文字为中间时刻、首尾与区间文字逐字一致、日期类范围保持日期标签、刻度净空白实测为 `2.5 × measureText('0')` 且刻度数不少于 v39；桌面多视口下 `main` 铺满（无 1480px 上限）、下载器卡片列数随宽度自适应且每张卡片内容无溢出 / 无省略号、≤1200px 与手机端仍 2 列。离线镜像 `docker load -i` 往返正常、容器冷启动 `/api/health` 200、镜像内静态文件确含 v40 改动。SW 缓存升到 `ttm-shell-v40`。**流量统计口径沿用 v15，零改动**。

### v39

> 本轮按使用反馈**修正 v38 把 rate 折线末点对齐到含尾桶余秒的 `window.end` 后「绘图范围比选择范围多几秒」的问题**，并调整两张卡片的纵坐标刻度、不限速图标、采集页表单顺序与关于页运行状态布局。后端 `app/chart.py` 仅把「**展示窗口右端**」与「**SQL 查询右端**」分离，**统计数值 / 分桶 / 聚合 / 累计计数器差值口径零改动**，`traffic` 柱状数据完全不变；`style.css` 沿用 v37 归并成果继续**就地修改**，不在末尾追加同名覆盖。**不涉及数据库 schema 迁移**，历史数据完全兼容，升级只需替换镜像重新 `docker load -i` / compose 部署（步骤见下方「3. 启动」与本节的 compose 提示）；v35 引入的《安全加固与重新部署指南-v35.md》安全内容与部署步骤本轮未变、继续适用。

| 需求 | 实现 |
|---|---|
| **1. 绘图范围不再多几秒（用户要求「对所有时间选择范围一一验证」）** | **先给核实结论：v38 修过头了，用户反馈成立**。v24 起 `_sample_buckets()` 为「不丢掉不足一个完整桶的尾部采样」，把窗口右端取成 `window_end = end_aligned + extra`，其中 `extra = int(now - end_aligned)` 是当前时刻越过最后一个对齐桶边界的余秒（0 ~ `step-1`）。v38 把 rate 折线末点 `times[-1]` 直接对齐到这个 `window_end`，于是 tooltip 首末跨度 = `选择范围 + extra`：**实时 5 分钟档（`step=5`）多 0~4 秒、`now` 落在整分后 2 秒即「多 2 秒」**；6h（15s/点）、12h（30s/点）最多多 14 / 29 秒。新建 `verify_range_v39.py`，**独立按每个档位语义算出「选择范围」**（不引用 `data.window`），用 **4 个带小数余秒的 `now` × 12 档 × 2 metric** 交叉比对：v38 的采样类 4 档（live / 1h / 6h / 12h）**14 处多绘制**（`now=…002.7` 时 live 恰 `+2.0s`、1h `+2s`、6h `+7s`、12h `+22s`），自然周期档因 `int()` 截断还少 <1 秒；traffic `spans` 48/48 区间覆盖完整。**修法**：`build()` 新增 `disp_end = 窗口起点 + 选择范围秒数`（live 取 `live_span`、1h/6h/12h 取 `RATE_RANGES`、自然周期 / 「全部」取 `round(window_end - start)` 消除亚秒抖动），`rate` 的 `times[-1]` / `labels[-1]`、`window.start/end`、`window_label` 右端统一对齐 `disp_end`；**SQL 查询右边界仍用含 `extra` 的原 `window_end`**，尾部采样不丢，`series` / `spans` / `bucket_count` / offset / 聚合 / 累计计数器差值一律不动。修复后 **48 / 48 通过**：采样类 4 档全时刻 **0 误差**，逐档既不多绘制也不少绘制；traffic `spans` **48 / 48** 覆盖到选择范围 |
| **2. 纵坐标固定 6 个刻度（0 除外）且标出最大值刻度** | v35（5.4）起 `computeScale()` 用 `niceStep(plotMax/6)` 把步长上取整到 `1/2/2.5/5/10` 的 nice 数，导致**刻度数随峰值在 5~6 条（含 0）之间浮动**、且最高一条常小于 `plotMax`（实测 7.7GB 档只有 5 条、最大值刻度 `8.0G` 而绘图上限 `8.44G`）—— 即「纵坐标太少」且「最大值没标出」。v39 改为把绘图映射上限 `plotMax = peak / 0.98` **直接 6 等分**：`ticks = 0, plotMax/6, …, plotMax`，恒 **7 条**（0 除外正好 **6 个**），**最顶一条 = 纵坐标最大值 `plotMax`**、落在绘图区顶部 `y=pad.t`，`tickMax === plotMax`；`niceStep()` 作为不再使用的死代码删除。**绘图映射 / 曲线饱满度 / 数值口径零改动**，`makePad()` 按实际刻度量宽度自动适配留白，`txt()` 的 `dominant-baseline=central` 保证顶部文字不裁切。`axis_y_v39.js` **121 通过 / 0 失败**（6 档峰值 × 3 视口 × 折线 / 柱状，含 0 与 TB 级、等间距、网格线同 y、v38 对照组刻度数浮动）；真实 Chromium 补充验证顶部最大值刻度 `getBBox().y ≥ 0` 不裁切 |
| **3. 下载器详情页「不限速」图标去掉背景圆** | 单台详情弹窗与汇总详情里逐台展示的卡片共用 `dtHeadHTML()` → `dtLimit()`。原来不限速时 `∞` 被 `<b class="dt-inf">` 包成 `17×17px`、圆角 50%、带边框和 `--bg2` 底的圆。v39 **就地修改** `.dt-inf`，删掉 `display:inline-grid` / `place-items` / `width` / `height` / `border-radius:50%` / `border` / `background`，只保留字号 / 字重 / 颜色 / 基线对齐，`∞` 变成纯字符；HTML 结构与 `title` / `aria-label` 无障碍标注不变。真实 Chromium 深 / 浅主题 × 桌面 / 手机：`border-radius=0px`、`border=0px`、背景透明、`display:inline`，占位宽度 **17px → 9.28px**，仍是 2 个 `∞`；有限速时仍显示 `fmtRate()` 数值，不受影响 |
| **4. 设置 → 采集 表单重排** | 三个分组由「实时速率采样间隔 → 流量统计采样间隔 → 「实时」时间范围」改为**「实时」时间范围 → 实时速率采样间隔 → 流量统计采样间隔**，`form-actions` 保存按钮与 `collectCurrent` 当前生效说明仍在最下。仅移动 `index.html` 里的三组 `<h3>/<p>/<div class="opt-row">` 块，`id`（`liveOptions` / `pollOptions` / `trafficPollOptions`）与 `renderCollect()` / 保存逻辑零改动。真实 Chromium 1000px / 390px 下三个标题视觉 y 严格递增，DOM 顺序与 id 顺序一致 |
| **5. 关于 → 运行状态前两行** | 原来 9 项全塞进一个 `auto-fit` 网格，行内容随宽度浮动。v39 拆出 `#aboutLead`（复用 `.about-info` 卡片样式，新增 `.about-lead{grid-template-columns:repeat(2,minmax(0,1fr))}` **固定 2 列**）承载前 4 项：**第一行** = 在线下载器数量 + 「实时」窗口时间范围，**第二行** = 实时速率采样间隔 + 流量统计采样间隔；其余 5 项（两种采样轮次 / 时区 / 最后更新 / 采集状态）仍在 `#aboutInfo` 按原 `auto-fit` 排列，**内容与顺序完全不变**。`renderAbout()` 对旧版缓存 HTML（无 `#aboutLead`）做了兼容回退，信息不丢。真实 Chromium 1000px / 390px：四项 computed 为 2 列、两行各两项同 y 且第二行更低，其余 5 项逐项一致 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v39.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：Python / JS 语法全通过；模块单元测试 **43 通过 / 0 失败**；v34↔v35 图表数值 **120 组零差异**（统计口径本轮未变、结论沿用）。**v38↔v39 数值零回归**：`regress_v39.py` 动态加载两版 `chart.py`，对 **3 个 now × 12 range × 2 metric × 3 offset = 216** 组合逐字段比对，`series / summary / spans / bucket_count / offset / max_offset / at_latest / downloaders` 全严格相等、`labels/times` 前 n-1 项与 traffic 全项逐字节一致 —— **216 通过 / 0 失败**，42 个 rate 组合末点被修正为 `disp_end`、78 个组合的 window 展示区间被修正。**全时间范围核实**：`verify_range_v39.py` **48 / 48**（4 时刻 × 12 档，rate 零多零少、traffic 区间 48/48）。**Y 轴**：`axis_y_v39.js` **121 通过 / 0 失败**，真实 Chromium 顶部刻度不裁切。**v39 综合浏览器验证**：`browser_v39.py` **53 通过 / 0 失败**（源码级 5 项断言、需求 3 v38/v39 CSS 对照 4 视口主题、需求 4 DOM + 视觉 y、需求 5 真实 `renderAbout()` 两行布局、需求 2 真实字体 Y 轴）。回归：`axis_v38.js`、`geom_v36.js`、`tip_v37.py`、`css_equiv.py`、v34↔v35 数值对比全部复跑通过。**v39 CSS 等价**：`css_equiv_v39.py` 声明级确认唯一变化为 `.dt-inf` 删除 7 项圆形 / 边框 / 尺寸声明 + 新增 `.about-lead` 一条规则；真实 Chromium **914 万项**对比，差异全部落在详情页与运行状态区域、其它组件及配色零差异 —— **11 通过 / 0 失败**。真实容器 HTTP 端到端 **62 通过 / 0 失败**；离线镜像 `docker load -i` 往返正常、冷启动 health 200，镜像内静态文件确含 v39 改动。SW 缓存升到 `ttm-shell-v39`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：只提供 v39 的 `.tar` / `.zip`；随包仍保留《安全加固与重新部署指南-v35.md》及《同类项目对比与安全审查-v34.md》《流量统计口径深度解析-v15.md》两份历史报告。

> 本次 `torrent-traffic-monitor-image-amd64-v39.tar` 的 SHA256：`9788d99916b5bfa251050b4f9497c70634634bca153d3ad2e20ed0edf56d3155`

### v38

> **v39 更正**：本节需求 1b 把 rate 折线末点对齐到 `window.end` 后，**绘图范围反而比选择范围多了几秒** —— `window.end` 是 SQL 查询右端，还含 v24 的尾部余秒 `extra = int(now - end_aligned)`（实时 5 分钟档多 2 秒、12h 档最多多 29 秒）。已在 **v39 需求 1** 用 4 个时刻 × 12 档逐一核实并修复：把「展示窗口右端」与「SQL 查询右端」分离，SQL 仍查到右端以免丢尾部采样，详见上方「上一版（v39）」需求 1。

> 本轮按使用反馈**修正 v37 遗留的「绘图时间范围少一桶」问题**，并调整 X 轴刻度密度、合计行配色与详情页布局。**改动涉及后端 `app/chart.py`**（仅折线展示用的时间轴端点标签），但**统计数值 / 分桶 / 聚合 / 累计计数器差值口径零改动**，`traffic` 柱状数据完全不变；`style.css` 沿用 v37 归并成果继续**就地修改**，不在末尾追加同名覆盖。**不涉及数据库 schema 迁移**，历史数据完全兼容，升级只需替换镜像重新 `docker load -i` / compose 部署（步骤见下方「3. 启动」与本节的 compose 提示）；v35 引入的《安全加固与重新部署指南-v35.md》安全内容与部署步骤本轮未变、继续适用。

| 需求 | 实现 |
|---|---|
| **1a. X 轴刻度：≤24h 去日期、4 数字字符空白、尽量多放** | v37 把刻度压得太少（手机端基本只剩头尾 + 中间一个），还带日期浪费空间。v38：① 用 `window.end - window.start <= 86400 + 120` 判定短范围，**≤24 小时（含实时 / 1 / 6 / 12 / 24 小时 / 昨日 / 本周等）横坐标只显示时间、去掉 `MM-DD ` 前缀**，>24h 保留日期以区分跨天；② 新增 `axisLabels` 与 `labels` 分离 —— 前者只管 X 轴显示（可去日期），后者保留原始精度给 tooltip，**弹窗数据一字不变**；③ 重写 `charts.js` 的 `axisXMarkup()`：用真实 `canvas.measureText('0')` 算出 `gap = 4 * digitW`，再按 `text-anchor=start/middle/end` 精确计算每个刻度文字的占位盒 `[L,R]`、以**净空白**判定（不再用整格 `unit` 粗估）；**首 / 尾刻度无条件必现**（折线用 `edges` 边界锚贴齐绘图区左右边界、柱状图首尾居中），中间刻度从左到右贪心放置，满足 `b.L - prevR >= gap` 且不挤占尾刻度 `last.L - b.R >= gap` 才放，从而在绝不重叠的前提下**尽量多放几个刻度**；极窄屏塞不下时安全退化为等距抽稀、不裁切。效果（真实 Chromium 系统字体实测）：手机 360px 折线刻度 **3 个 → 5 个**，桌面 1000px **9 个 → 12 个**。**流量统计柱状图用同一套逻辑**：先保证首尾两个刻度，再按 4 个数字字符净空白贪心多放，柱组中心定位（v36）不变 |
| **1b. 绘图时间范围完整（修 v37 遗留，用户要求「对所有时间选择范围一一验证」）** | **先给核实结论：v37 没解决，用户反馈成立**。v37 的核实脚本 `verify_xaxis.py` 有盲点 —— 它把 `times[-1]-times[0]+step` **主动补一个桶宽**当作绘图跨度，再用 `cover - 2*step` 容差，把「少一桶」判成正常。真实原因：`times` / `labels` 是**桶起点**，n 个点首末跨度 = `span - step`；rate 折线把 n 个点按 `i/(n-1)` 铺满绘图区，最右点被标成 `end - step`，用户从悬停 tooltip 的「单点时刻」看到的就是「实时 5 分钟档只有 4 分 55 秒，少 5 秒」。v38 新建 `verify_range_v38.py` **不再补桶宽**、直接量化 `window.end - times[-1]`，对 **12 档 × 2 metric 全量核实**：修复前 rate **12 / 12 档全部少绘制一桶**（live 5 分档少 5 秒、1h 少 5 秒、6h 少 15 秒、12h 少 30 秒、昨日少 3600 秒、上月少 86400 秒…）。**修法**：`chart.py` 的 `build()` 对 `metric == "rate" and n >= 2`，把 `times[-1]` / `labels[-1]` 对齐 `window.end`（各分桶函数给 bucket 增加 `lfmt`，让末端刻度复用同一时间格式）；**`series` / `spans` / `window` / `bucket_count` / offset / SQL 分桶 / 聚合 / 累计计数器差值零改动**。前端三处配套：`app.js` 的 `downsample()` 降采样后末点仍对齐原 `data.times[n-1]`（否则手机端降采样会复现「少一桶」）；`loadChart()` 非 live 档签名首项由 `times[-1]` 改为 `times[0]`，避免末点随每次请求变化导致无谓重绘；`charts.js` 帧平移动画的 `dt` 由 `(tNew[n-1]-tNew[0])/(n-1)` 改为 `tNew[1]-tNew[0]`（末点对齐后时间点不再等间隔）。**traffic 柱状图按「区间」语义绘制**，`spans` 本就覆盖到 `window.end`、tooltip 显示的是时间段而非单点时刻，「单点跨度少一桶」对它不适用，**数值口径零改动、无需修改**。修复后 rate **12 / 12 档绘图范围完整**（逐档 `times[0] = window.start`、`times[-1] = window.end`、`win.end - times[-1] = 0s`），traffic `spans` **12 / 12** 覆盖到 `window.end` |
| **2. 流量统计绘图区弹出框：合计流量颜色对齐顶部四卡** | 流量统计柱状图点击 / 悬停明细框里，合计行的 ↑ 上传 / ↓ 下载此前是普通文字。v38 给合计上传 / 下载分别包 `<b class="u">` / `<b class="d">`，复用 v37 已有的 `.tooltip .u{color:var(--up)}` / `.tooltip .d{color:var(--down)}`，与页面最顶部四张小卡片 `.card-vals .v.up` / `.v.down` 的上传 / 下载文字取的是**同一组 CSS 变量** `--up` / `--down`。真实 Chromium computed color 逐项比对：深色 `rgb(251, 146, 60)` / `rgb(56, 189, 248)`、浅色 `rgb(234, 107, 31)` / `rgb(2, 132, 199)`，与顶部卡片完全相等；合计仍排最前（v37 的 `.tip-sum.lead` 与桌面 / 手机一致），各下载器明细顺序、数值口径零改动 |
| **3. 下载器详情页布局再收紧** | 点击下载器卡片弹出的详情页、以及汇总详情里逐台展示的下载器详情一并生效。沿用 v37 归并后的 `.dt-head` 基础规则**就地修改**（桌面基础规则 + 手机 `@media` 同步），不在末尾追加同名覆盖：① 桌面列间距 `gap: 8→4px`、卡片左内边距 `var(--dt-pad)→3px`（右 / 上 / 下不变），手机 `gap: 6→3px`、左内边距 `2px` → qB / TR 圆图标与右侧三行文字**整体再左移**、**图标与文字更靠近**；② `.dt-r` 由 `flex:0 1 auto` 改为 `flex:0 0 auto` **不收缩**，右侧「实时速率 / 限速 / 剩余空间」三行 `nowrap` 完整显示，压缩全部交给左栏；③ `.dt-url` 字号 **12→10px**（手机 10→9px），并改 `nowrap + overflow:hidden + text-overflow:ellipsis`，用 `display:block` 覆盖 `.dt-line` 的 flex —— 否则文本被包成匿名 flex item，`text-overflow:ellipsis` 不生效且 `min-width:auto` 会撑破不收缩。真实 Chromium 量化：桌面图标左移 `29→22px`、文字左移 `101→90px`、图标文字间距 `8→4px`、地址 `12→10px`；手机 `21→15px` / `73→64px` / `6→3px` / `10→9px`；**超长地址 + 超长限速压测**下地址仍单行、不与右侧重叠、不换行 |

**升级 / 重新部署（compose）**：本轮无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v38.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：Python / JS 语法全通过；新增模块单元测试 **43 通过 / 0 失败**；v34↔v35 图表数值 **120 组零差异**（统计口径本轮未变、结论沿用）。**v37↔v38 数值零回归**：`regress_v38.py` 用动态模块同时加载两版 `chart.py`，对 **12 range × 2 metric × 3 offset = 72** 组合逐字段比对，`series / summary / spans / window / bucket_count / offset / max_offset / at_latest / downloaders` 全严格相等 —— **72 通过 / 0 失败**，其中 36 个 rate 组合的末点被修正为 `window.end`，traffic 完全不变。**全时间范围核实**：`verify_range_v38.py` 12 档 × 2 metric，rate **12 / 12** 绘图完整、traffic `spans` **12 / 12** 覆盖到 `window.end`。**X 轴几何**：`axis_v38.js` **98 通过 / 0 失败**（折线 n=60/720/11/2/1、桌面 / 手机 / 极窄、≤24h 去日期与 >24h 带日期对照、4 数字字符净空白、贪心多放、tooltip 原始 labels、柱状 n=24/5/2/1 柱组中心与极窄不裁切），v36 柱状图几何回归 **41 通过 / 0 失败**。**v38 综合浏览器验证**：`browser_v38.py` **105 通过 / 0 失败**（源码级断言、真实字体 `measureText` 刻度、需求 2 深浅主题 computed color 逐项相等、需求 3 桌面 / 手机左移量化与超长压测）；v37 流量弹窗合计在前 `tip_v37.py` **46 通过 / 0 失败** 回归。**CSS 等价性**：`css_equiv_v38.py` 两层 —— 声明级（tinycss2）确认 v37→v38 只有 `.dt-head` / `.dt-r` / `.dt-url` 三条规则变化、属性集合符合预期；真实 Chromium **9 视口 × 深浅主题 × 1089 元素 × 466 属性（含自定义属性与伪元素）= 913 万项**对比，所有差异都落在详情页组件树（`.dt-*` 与 `detail-body` / `modal-detail` 容器因 `.dt-head` 变矮产生的连锁高度），**顶栏 / 卡片 / 图表 / 图例 / 设置 / 下拉 / tooltip 等其它组件零差异、颜色类属性零差异**；另复跑 v37 归并等价 `css_equiv.py` 零差异。真实容器 HTTP 端到端回归 **62 通过 / 0 失败**；离线镜像 `docker load -i` 往返正常、冷启动 health 200，镜像内静态文件确含 v38 改动。SW 缓存升到 `ttm-shell-v38`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：只提供 v38 的 `.tar` / `.zip`；随包仍保留《安全加固与重新部署指南-v35.md》及《同类项目对比与安全审查-v34.md》《流量统计口径深度解析-v15.md》两份历史报告。

> 本次 `torrent-traffic-monitor-image-amd64-v38.tar` 的 SHA256：`b33e203bc82796a013c06bf1ce2adc433a2051d8e1aae5822533cba0ef035caa`

### v37

> **v38 更正**：本节需求 1「绘图数据范围并未变短」的核实结论**不成立** —— v37 的核实脚本主动给末尾补了一个桶宽并放宽容差，把「少一桶」判成正常。真实情况是折线最右点比 `window.end` 少一个桶宽（实时 5 分钟档少 5 秒），已在 **v38 需求 1b** 按全部 12 档逐一核实并修复，详见上方「本次更新（v38）」。

> 本轮是**纯前端 UI 调整 + CSS 工程化归并**：后端 Python 代码与 v35/v36 逐文件哈希一致、零改动，按使用反馈调整 2 处图表交互，并对累积 20 余个版本的 `style.css` 做**一次整体归并**。**不涉及数据库 schema 迁移**，历史数据完全兼容，升级只需替换镜像重新 `docker load -i` / compose 部署（步骤见下方「3. 启动」与本节的 compose 提示）；v35 引入的《安全加固与重新部署指南-v35.md》安全内容与部署步骤本轮未变、继续适用。

| 需求 | 实现 |
|---|---|
| **1. 实时速率卡片横坐标首尾刻度对齐所选范围** | **先给核实结论**：对全部 12 个档位逐一比对 `chart.build()` 的 `window.start/end` 与绘图点 `times[0]/times[-1]`，**0/12 档绘图数据范围比选择范围短** —— 折线 X 轴本就用 `i/(n-1)` 从 `pad.l` 铺满到 `pad.l+plotW`，buckets 完整覆盖 `[start,end)`，绘图区没有变短。病根在**刻度展示**：① 旧 `axisXMarkup()` 抽稀后，末尾补标签要满足 `X(n-1)-lastX>=unit` 才补，12 档 × 桌面/手机 共 24 组合里 **7 组**最右刻度停在窗口终点前好几个桶（1 小时档差 3.7 分、上月桌面差 2640 分、全部档桌面差 41413 分）；② 首尾标签用 `text-anchor=middle`，中心压在边界上、视觉左右各内缩半格。二者叠加看着像「范围缺了一截」。**修法**：折线且传入 `edges={start,end}` 时，首刻度用起点文本 + `start` 锚贴绘图区左边界、尾刻度用终点文本 + `end` 锚贴右边界，两者**无条件显示**，中间刻度仍按 `every` 抽稀但避开首尾文字占位；两端文本直接取自 `app.js` 拆分的 `window.label`，与左上角「范围」文字逐字一致。柱状图（v36 柱组居中）不传 `edges`、完全保持原逻辑；绘图区过窄塞不下两端文字时安全退回原抽稀逻辑、绝不溢出。拖动 offset 变化后 `windowLabel` 随 `loadChart` 更新，首尾刻度始终是当前绘图区真实起止 |
| **2. `style.css` 整体归并（报告 5.5 技术债）** | 《同类项目对比与安全审查-v34.md》5.5 指出 `style.css` 由 v14/v18/v21/v25/v28/v31/v32/v34 共 8 段补丁区叠加、其后又叠 v36，存在同特异性覆盖与「顺序坑」。本轮做一次整体归并。**关键约束：不能跨 `@media` 聚合同名选择器** —— 文件后半的 v31/v32/v34 是刻意放在 `@media` 之后的「全局收紧」规则，靠后置位置覆盖窄屏值；首版「按选择器折叠到末次位置」算法就因此把窄屏 `.pill` 的 `font-size` 从 11px 错改成 12px（被浏览器逐属性比对抓到）。最终采用**保序 · 声明级去重**：只删除「同 (media 条件, 选择器) 组里后面还有同名同 `!important` 声明」的冗余声明（这些声明本就不可能胜出），**不移动任何声明的相对顺序**，再合并相邻同断点块、删净全部历史版本补丁注释、改为按功能分区的导读。结果：规则数 608→587、删除 **104 条**冗余声明、行数 **1145→787**、注释从 115 段历史版本号收敛为功能分区标题；文件头写入「后续改样式请直接改对应规则、不要在末尾追加同名选择器覆盖」的迭代约束，消除继续迭代踩覆盖顺序坑的隐患 |
| **3. 流量统计点击/悬停弹窗：合计在前** | 流量统计柱状图点击 / 悬停弹出的明细框，原顺序「标题 → 各下载器明细 → 合计」，v37 调整为「标题 → **合计** → 各下载器明细」。合计行移到最前并加 `.lead` 类，CSS 把它的分隔线由 `border-top` 改到 `border-bottom`（与下方明细分隔），桌面与手机端、深浅主题一致；明细仍按选中顺序完整列出所有下载器（0 流量也显示）、数值与配对逻辑零改动 |

**升级 / 重新部署（compose）**：本轮纯前端、无 DB 迁移，历史数据完全兼容。离线镜像版：

```bash
cd /vol1/docker/torrent-traffic-monitor
docker load -i torrent-traffic-monitor-image-amd64-v37.tar
docker compose -f docker-compose.offline.yml up -d --force-recreate
```

源码构建版把 `docker load -i` 换成 `docker compose -f docker-compose.yml up -d --build --force-recreate`。完整步骤（含 `.env` 强账号、`SECRET_KEY` 备份、lucky 反代边界防护、可信代理网段）见随包《安全加固与重新部署指南-v35.md》，本轮未变。

**验证**：Python / JS 语法全通过；后端 `.py` 与 v35/v36 逐文件哈希一致（零改动）；新增模块单元测试 **43 通过 / 0 失败**；v34↔v35 图表数值 **120 组零差异**；真实容器 HTTP 端到端回归 **62 通过 / 0 失败**。**CSS 归并等价性**是本轮重点：声明级严格等价（1737 个胜出键 / 值全一致），并用真实无头 Chromium 对归并前后做 **9 视口 × 深浅主题 × 1089 元素 × 466 属性（含自定义属性与伪元素）= 913 万项逐属性比对，零差异**；期间用「同一份 CSS 自比」的 control 组定位并排除了 `transition` 动画中间态造成的假阳性（`transform: 8.62px` / `font-size: 11.85px` 一类非终值），确认差异来自动画而非归并。**需求 1**：`charts.js` 折线 X 轴几何自检 **44 通过 / 0 失败**（首尾刻度贴齐边界、中间刻度避让、极窄屏安全退化、柱状图不受影响），v36 柱状图几何回归 **45 通过 / 0 失败**，12 档数据范围核实脚本结论明确（0/12 变短、7/24 尾刻度不到终点）。**需求 3**：源码级 + 真实 Chromium（1440 桌面 / 390 手机 × 深浅主题）**46 通过 / 0 失败**（DOM 顺序、视觉上下、分隔线方向、文本内容）。镜像内静态文件确含 v37 改动，`docker load -i` 往返正常。SW 缓存升到 `ttm-shell-v37`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：只提供 v37 的 `.tar` / `.zip`；随包仍保留《安全加固与重新部署指南-v35.md》及《同类项目对比与安全审查-v34.md》《流量统计口径深度解析-v15.md》两份历史报告。

> 本次 `torrent-traffic-monitor-image-amd64-v37.tar` 的 SHA256：`36352f6f29035174fb2ff1bf7b9d2eee28266ceedccf312ed796e58336f00525`

### v36

> 本轮是**纯前端 UI 微调**：后端 Python 代码与 v35 逐文件哈希一致、零改动，按使用反馈调整 6 处界面细节，桌面端与手机端同步生效。**不涉及数据库 schema 迁移**，历史数据完全兼容，升级只需替换镜像重新 `docker load -i` / compose 部署；v35 引入的《安全加固与重新部署指南-v35.md》安全内容与部署步骤本轮未变、继续适用。

| 需求 | 实现 |
|---|---|
| **1. 柱状图时间点分组留白 + 横坐标居中** | 流量统计卡片：① v35 的「点少调宽柱宽」会让相邻时间点的两组柱几乎贴在一起，v36 给柱宽加一道硬上限 —— 相邻柱组之间至少留 **2 个柱宽**的空白（组内上传 / 下载两柱仍保持 3px 小间隙，表示同一时间点）；`n=1` 单点没有「组间」概念，保留宽柱填充；点密集（`n≥24`）仍回落 v34 细柱口径、不把细柱再压细。② 横坐标文字此前复用折线图的 `i/(n-1)` 定位，而柱状图每个时间点其实是一个「柱组」，标签应落在 `groupW*(i+.5)` 的柱组中心；`axisXMarkup()` 新增 `barMode` 按柱组中心定位，**单个时间点 / 多个时间点都严格位于上传下载两柱正下方居中**（折线图调用不传该参数、口径不变） |
| **2. 测试连接结果只在弹窗展示** | 已保存下载器（配置表「测试」）与新增 / 编辑下载器（表单「测试连接」）的结果一律只由 `testModal` 独立结果窗口展示，删除页面右下角 `#formMsg` 里的测试结果文本；按钮保留「测试中…」禁用态与 12 秒兜底（只更新按钮文字）。`#formMsg` 仍只用于保存表单的「已保存 / 请填写地址 / 密码留空表示保持原值」等反馈 |
| **3. 账户设置删除提示文本** | 删除「当前登录：xx。不点『退出登录』会一直保持登录状态。」整句；同步移除对 `#accountName` 的两处 JS 赋值，避免删元素后空指针。修改账号后的反馈简化为「已保存」 |
| **4. 图例下载器间距加宽 2 个中文字符字号** | 实时速率 / 流量统计两张卡片的图例，项间距由 8px 加宽到 **30px**（≈ 原 8px + 2 个中文字符字号 22px）。间距统一由 CSS 变量 `--lg-gap` 定义，`renderLegend()` 直接读取该变量计算每行可放几项，保证 JS 列数计算与 CSS 实际间距严格一致、不会窄屏换行错乱；桌面 / 手机端由同一变量同步生效，≤360px 特例同样跟随 |
| **5. 详情页图标对齐 / 文字贴紧 / 右侧不换行 / 留白收紧** | ① qB / TR 圆图标左移并水平左对齐：图标列宽度收到与 SVG 等宽、`place-items:center start`，圆外边缘与下方「种子总数」文字最左侧**严格对齐**（统一用 `--dt-pad` 定义卡片内左右留白，桌面 10px / 手机 8px，单台详情与汇总详情逐台卡片都成立）。② 图标与右侧名称 / 地址 / 版本 / IO 的间距 14→8px（手机 8→6px）、图标列 74→64px（手机 48→46px），文字左移幅度比图标更大、与图标贴得更紧。③ 右侧「实时速率 / 限速 / 剩余空间」三行去掉 `flex-wrap:wrap` 与 `max-width:70%`，改为整行 `nowrap`，长文本只挤压可收缩的左栏，右侧三行固定本行、**不允许因文本过长而换行**。④ 卡片内文字到边框的留白、行间距、统计块 / 分区标题 / 逐台卡片间距整体收紧（`.dt-head` padding 14→10、`.dt-main` gap 6→4、`.dt-stats` gap 9→6、`.dt-stat` padding `10px 12px`→`7px 10px` 等），桌面基础规则、v31 末尾覆盖块与两处媒体查询同步收紧，一页能展示更多内容 |
| **6. 桌面端与手机端同步** | 除特别说明外，上述图例间距、柱状图、详情页对齐 / 不换行 / 留白在 1440px 桌面与 390px 手机视口下均由同一套规则或配套媒体查询生效 |

**验证**：Python / JS 语法全通过；后端 `.py` 与 v35 逐文件哈希一致（零改动）；新增模块单元测试 **43 通过 / 0 失败**；v34↔v35 图表数值 **120 组零差异**；`charts.js` 柱状图几何自检 **45 通过 / 0 失败**（`n=1/2/3/4/24` × 单 / 双向 × 桌面 / 窄屏，逐项断言组间空白 ≥ 2 柱宽、标签命中柱组中心）；真实无头 Chromium 在 **1440 桌面 + 390 手机** 两种视口下 **14 项断言全通过**（图例间距精确 30px、图标左边缘与「种子总数」文字 `diff=0`、右侧三行 `nowrap` 且同一行、留白收紧、柱状图留白与居中）；真实容器 HTTP 端到端回归 **62 通过 / 0 失败**；镜像内静态文件确含 v36 改动，`docker load -i` 往返正常。SW 缓存升到 `ttm-shell-v36`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：只提供 v36 的 `.tar` / `.zip`；随包仍保留《安全加固与重新部署指南-v35.md》及《同类项目对比与安全审查-v34.md》《流量统计口径深度解析-v15.md》两份历史报告。

> 本次 `torrent-traffic-monitor-image-amd64-v36.tar` 的 SHA256：`c525c9f89f3850b18ce916f77c8630d2c93f426faf606d630bb85e29d08fc3bd`

### v35

> 本轮是**结构性重构 + 全量安全加固**：按《同类项目对比与安全审查-v34.md》第 5 部分修复 5 项技术债、第 6 部分修复 R1~R12 安全风险，并新增「柱少时自适应调宽柱宽」。涉及数据库 schema 迁移与登录 / 部署习惯变化，**建议按随包的《安全加固与重新部署指南-v35.md》重新通过 compose 部署**；该指南同时给出「代码修不了、必须部署侧配合」的详细应对方案（lucky 边界层 / HTTPS + HSTS / IPv6 防火墙 / 可信代理 / 密钥备份 / 多进程前提 / CSRF 约束）与完整重新部署步骤。

| 需求 | 实现 |
|---|---|
| **5.1【高】长短窗口数据源拼接** | 报告指出的最大结构性技术债：短窗口靠 `UNION ALL samples + traffic_samples` 混表、每次请求三处 `MIN(ts)` 全表扫描、为算 `max_offset` 还要重复调一次 `_buckets()`。v35 引入 Beszel/Netdata 式**分层物化**：`rollup_1m`（分钟）/ `rollup_1d`（天）由后台幂等生成；升级时把 `samples` 里的历史流量增量一次性迁入 `traffic_samples`，彻底删掉 `UNION ALL`；`db.bounds()` 加 30 秒 TTL 缓存替代三处 `MIN(ts)`；`_buckets(count_only=True)` 只算桶数用于 offset 预算，顺带修掉超大 offset 导致的自然周期日期溢出；短窗口流量按数据边界路由到 `traffic-raw` 或 `rollup-1m` **单表查询**。`hourly` 仍是写时预聚合，顶部卡片与 `stats.py` 口径不变。**全 12 range × 2 metric × 5 组 offset 共 120 组 v34↔v35 数值对比零差异** |
| **5.2【中】双线程隐含耦合** | 速率线程的瞬时状态（在线 / 速率 / 错误 / extra）与速率基线全部放内存 `_live` / `_rate_base`，`record_rate_sample()` **只写 `samples` 一张表**，不再每 0.1 秒 `UPDATE downloader_state`；`downloader_state` 只由流量线程维护累计基线。`mark_offline(..., source=...)` 区分 rate / traffic，避免在线状态互相覆盖；`get_states()` 合并 DB 基线与内存实时态，API 外形不变 |
| **5.3【中】轮询 → 推流** | 新增 `/api/stream` SSE + `EventBus`（每种事件最小发布间隔 1 秒，避免 0.1 秒档把前端压垮）；采集完成推一次增量通知，前端用 `fetch()` + `ReadableStream` 读取（可带 `Authorization` 头，不用 `EventSource`），收到 `rate` / `traffic` 只做局部刷新；带 `retry: 3000`、keep-alive 注释帧、断线重连、90 秒看门狗与轮询降级。waitress 线程 4 → 12 给长连接留余量；订阅在响应生成器内创建 / 释放，避免名额泄漏 |
| **5.4【中】`niceMax` 贴合与刻度语义冲突** | `charts.js` 把**绘图映射**与**刻度**解耦：`plotMax = peak / Y_FILL(0.98)` 只负责纵向饱满度；`ticks = 0, step, 2·step …` 由 `niceStep()` 生成 1/2/2.5/5/10 的 nice 整数刻度，网格与刻度文字按 `scale.ticks` 绘制；折线与堆叠柱共用 `computeScale()`，动画帧改用 `prev.scale.plotMax` 做纵向伸缩。v34 的 `niceMax()` 保留为兼容钩子 |
| **新增：柱少时自适应调宽柱宽** | 流量统计卡片按实际柱子数量 `n` 计算 `sparse = clamp((24-n)/20)`：点少时放宽柱宽比例与像素上限（单柱最高 132px / 双柱 78px），点密集（n≥24）回落 v34 细柱口径；双方向柱宽仍受 `(groupW-4)/2` 约束、最终钳在 `groupW*0.92` 内，不会压在一起或撑破绘图区 |
| **5.5【低】工程化与可观测性** | 单行 JSON 结构化日志（`password` / `token` / `authorization` 等敏感字段自动 scrub）；采集失败分类计数；新增 `/api/metrics`（Prometheus text，`?format=json` 调试视图）暴露运行时长、采集轮次、失败数、在线数、会话数、rollup 行数、SSE 订阅 / 发布 / 节流数；`rollup.status()`；`wal_checkpoint(TRUNCATE)` 并发失败降级 PASSIVE，不再打断清理或刷异常栈。**注释明确当前缓存 / 限流 / EventBus 只在单进程多线程下成立**，多进程需 Redis + Pub/Sub |
| **第 6 部分安全：R1~R12 全部代码修复** | R1 `BOOTSTRAP_*` 启动即建强账号（`must_change=0`）；R2 新增 `netsafe.py`（禁非 http/https、环回 / 链路本地 / 云元数据 / 保留地址，解析全部 A/AAAA 防 DNS rebinding）+ 已保存地址白名单 + **URL 变更且未显式填新密码时拒绝测试**（堵死凭据外泄）；R3 测试错误统一文案、原始异常只写日志；R4 `client_ip()` 仅可信代理网段采信 XFF 最后一跳，waitress 加 `--no-clear-untrusted-proxy-headers` 保留原始头；R5 30 天滑动 + 90 天绝对上限 + UA/IP 绑定 + 旧会话作废；R6 health 收敛 `{"ok":true}`、status 去用户名；R7 全套安全响应头 / CSP；R8 PBKDF2 600000 轮 + 旧哈希透明升级；R9 下载器密码 `enc:v1:` 加密（零第三方依赖，**多密钥回退 + 启动 rekey** 兼容密钥变更）；R10 全局限流 + 严格路径独立配额 + 256KB body 上限；R11 compose 端口绑定 `127.0.0.1`；R12 `audit_log` 表 + `/api/audit`。**R13 CSRF 在当前认证机制下不可利用**，约束与全部部署侧应对方案见《安全加固与重新部署指南-v35.md》 |

**验证**：Python / JS 语法全通过；新增模块单元测试 **43 通过 / 0 失败**；v34↔v35 图表数值 **120 组零差异**；真实 HTTP 端到端回归 **62 通过 / 0 失败**（鉴权、安全响应头、全 range×metric 图表、超大 offset、metrics / audit、SSE hello 与真实推流事件、SSRF 与错误回显、会话 UA/IP 绑定、限流、超大 body、logout）；离线镜像 `docker load -i` 往返正常。SW 缓存升到 `ttm-shell-v35`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：延续 v30 起的交付策略，只保留 v35 的 `.tar` / `.zip`，删除 v34 及更早的版本化产物；随包新增《安全加固与重新部署指南-v35.md》，并保留《同类项目对比与安全审查-v34.md》与《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v35.tar` 的 SHA256：`e9e0819116e0625176b3496bdcd49d447d4e5a7a79499fac03250ccd85431d03`

### v34

| 需求 | 实现 |
|---|---|
| **1. 桌面端设置页分页导航改为横向，与手机端一致** | 原实现里 `.settings-body` 是「140px 左侧导航列 + 右栏」两列网格、`.settings-nav` 竖向排列，只有 ≤900px 媒体查询才切成横向（v14）。v34 在 `style.css` 末尾追加补丁，用 `.modal.modal-settings` 前缀把全端统一成「上：横向导航行 / 下：分页内容」两行网格：`.settings-nav` 改 `flex-direction:row` + 横向可滚 + 底部细线，按钮不拉伸；同时压过 v31 的 `.settings-nav{padding-right:10px}` 与 v14 末尾的 `align-items/align-self:flex-start` 等高特异性旧规则。桌面与手机现在用同一套布局，分页切换逻辑、选中态、冻结标题行全部不变 |
| **2. 绘图区纵向范围由 82% 提升到 98%** | `charts.js::niceMax()` 原用 `peak / 0.82`（v25 起），峰值只占绘图区约 82% 高度、顶部固定留 18% 空白。v34 引入 `Y_FILL = 0.98`，`target = peak / Y_FILL`，并把「nice 数压低峰值」的兜底阈值从 `0.78` 改成 `Y_FILL - 0.04`，使任何量级下纵向利用率稳定在 **94%~98%**。折线与堆叠柱共用同一个 `niceMax()`，两张卡一起生效；`pad.t=14px` 与 `segmentPath()` 的 `[pad.t, h-pad.b]` 钳制仍保留描边 / hover 圆点安全余量，峰值不会被裁切 |
| **3. 删除两卡片第二行说明、统一图例样式** | `index.html` 删除「实时速率」「流量统计」两张卡片 `.panel-head` 里的第二行 `p.hint` 说明文字（下载器卡片的说明保留）。图例改成同一套 DOM、按断点切换：**桌面端 = 下载器名称 + 颜色方块 + 箭头 + 「上传 / 下载」**，流量统计卡片在末尾追加完整流量数据；**手机端 = 下载器名称 + 箭头**，流量统计卡片在末尾追加紧凑流量数据，颜色方块与「上传 / 下载」字样由 CSS 收起。`app.js` 给实时速率图例补上「上传 / 下载」文字，流量图例结构不变；`style.css` 用 `min-width:561px` / `max-width:560px` 两组规则显隐 `.sq` / `.lg-lb` / `.v-full` / `.v-short`，窗口缩放即时生效、无需重新渲染图例。`renderLegend()` 的固定字号、自适应列数、不缩字号不省略等排版规则全部保留 |
| **4. 同类项目对比与公网暴露安全审查（报告）** | 新增独立报告《同类项目对比与安全审查-v34.md》：公网检索 qBittorrent WebUI / VueTorrent / Flood / Prometheus+Grafana+qbittorrent-exporter / Netdata / Glances / vnStat / ntopng / Beszel / PT Nexus 等使用广、经大量验证的项目，与本项目在采集架构、存储与降采样、流量口径、前端渲染、认证与部署形态上逐项对比，指出逻辑 / 代码 / 算法可优化点（自动 rollup 重构、双线程写竞争、轮询→SSE、刻度与绘图上限解耦等）；并针对 **lucky 反代 + 三级域名公网访问** 场景全量审查代码，列出 13 项风险（默认账号竞速、认证后 SSRF 与下载器凭据外泄、反代下登录限速失真、10 年 token、未鉴权接口泄露、缺安全响应头等）与可直接采用的加固补丁。**本轮按需求只做 UI 三项改动，未改动认证 / 网络相关代码**——这些修复会改变现有登录与部署习惯，需你确认后实施 |

**验证**：Python / JS 语法全通过；无头 Chromium 在桌面 1440 与手机 390 两种视口下核对设置页导航为横向、两张卡片无第二行说明、桌面图例含方块与「上传 / 下载」、手机图例无方块且流量卡片带数值、峰值绘制到绘图区 98% 附近、零 JS 错误；真实 HTTP 端到端回归 `/api/settings` 与全 range × metric 结构；离线镜像 `docker load -i` 起容器往返正常。SW 缓存升到 `ttm-shell-v34`。**流量统计口径沿用 v15，零改动**。

> **产物仍只保留最终版**：延续 v30 起的交付策略，只保留 v34 的 `.tar` / `.zip`，删除 v33 及更早的版本化产物；同时新增《同类项目对比与安全审查-v34.md》随包提供。

> 本次 `torrent-traffic-monitor-image-amd64-v34.tar` 的 SHA256：`a263dbc843ddb0bf72f968def4f4b336e10c1564f82b433237403fb044da6909`

### v33

| 需求 | 实现 |
|---|---|
| **1. 绘图区改为 SVG 矢量，放大不再模糊** | 先回答排查结论：绘图区**不是**后台画好再放上来的图片，而是前端 `charts.js` 用**原生 Canvas 实时绘制的双层位图**（数据层 `#rateChart` / `#trafficChart` + 固定坐标轴层 `#rateAxis` / `#trafficAxis`）。浏览器放大页面时位图被插值拉伸，曲线、柱、文字一起发糊；`prep()` 里虽按 `devicePixelRatio` 放大过位图，但页面缩放改变的是 CSS 像素与 DPR 的对应关系，仍会模糊。v33 把绘图引擎重写为**原生 SVG**：折线是 `<path>`、堆叠柱与悬停高亮是 `<rect>`、水平网格是 `<line>`、Y 轴刻度与 X 轴时间标签是 `<text>`，字体栈与全站 `body` 完全一致（桌面 11px / 窄屏 10px）。SVG 的 `viewBox` 与容器 CSS 像素 1:1，浏览器缩放时按矢量重新栅格化，**曲线、图表、文字与界面其它文字一样清晰，放大不模糊**。双层结构、`_geom` / `_xTicks`、帧平移动画、hover 提示、拖动平移接口全部保持兼容，`app.js` 绘制调用零改动；`index.html` 把 4 个 `<canvas>` 换成同 id 的 `<div>` 容器，`style.css` 增加 `.ttm-svg` 撑满样式，关于页文案改为「原生 SVG 矢量绘图」 |
| **2. 采样间隔拆成「实时速率 / 流量统计」两套，实际采样也分做** | `config.py`：实时速率沿用原档位并在 **0.2 秒与 1 秒之间补 0.5 秒**，即 `0.1 / 0.2 / 0.5 / 1 / 3 / 5 / 10 秒`；新增流量统计档位 **`5 秒 / 10 秒 / 30 秒 / 1 分钟 / 5 分钟 / 10 分钟 / 30 分钟`**；**默认实时速率 5 秒、流量统计 1 分钟**（`poll_interval=5`、`traffic_interval=60`，环境变量 `POLL_INTERVAL` / `TRAFFIC_INTERVAL`）。`collector.py` 拆成 `collector-rate` 与 `collector-traffic` **两个独立采集线程**：各有自己的间隔、唤醒事件、客户端缓存与累计计数器基线，**各自独立向下载器取数**（qB 的 `sync/maindata` 增量 rid / 累计值缓存必须按线程隔离，否则两个循环互相消费 rid 会冲乱基线）。速率线程只写 `samples`（实时速率曲线）并更新状态 / 速率字段；流量线程只写新增的 `traffic_samples`（短窗口流量点）+ `hourly`（小时桶分摊）并更新流量基线，账本完全隔离、互不覆盖。`downloader_state` 新增 `rate_last_*` 三列（`init_db()` 用 `ALTER TABLE` 幂等补齐旧库），流量统计沿用 `last_dl_total / last_up_total / last_ts`，升级不丢基线。**统计口径沿用 v15，零改动**：仍只用累计计数器差值，异常轮次记 0、基线不清空。`main.py` 的 `/api/settings` GET/POST 同时支持两个字段（缺省沿用当前值，兼容旧前端），`/api/health` / `/api/overview` 暴露两套间隔与轮次；设置 → 采集 页拆成「实时速率 · 采样间隔」「流量统计 · 采样间隔」「实时窗口」三组 chip。相应地，**流量统计卡片的时间范围单选项删除「实时」**（`TRAFFIC_RANGE_ORDER` 去掉 `live`，历史 localStorage 里的 live 自动回落到「今日」），实时速率卡片仍保留全 12 档 |
| **3. 绘图点密度判定：绘制点不得超过采样数据量** | `chart.py` 在计算绘图桶 `step` / 桶数后加一道判定：**速率图** `step` 不小于实时速率采样间隔（向上取整到整数秒），**流量统计短窗口** `step` 不小于流量统计采样间隔且桶数按 `span // step` 收敛（不再固定 12 个等分桶）。于是「绘制点数 ≤ 窗口内采样点数」恒成立：例如 1 小时窗口、实时速率 5 秒采样，绘制点由 v32 的 1800 个收敛到 **720 个**（不再出现 2 秒一个绘制点、却只有 5 秒一个采样点，导致多个绘制点共用同一采样值、插值后数值一致而无效增加绘图次数）；流量统计 1 分钟采样时 1 小时窗口绘制点 ≤ 60，30 分钟采样时 ≤ 2。流量统计短窗口的数据源同步切到 `traffic_samples`（`UNION ALL` 升级前 `samples` 里的历史 `inc`，不丢旧数据），速率图只读 `samples` 的速率列、不受流量采样点影响。`build()` 新增 `traffic_interval` 参数，全 12 range × 2 metric 结构自检通过 |

**默认采样率与绘图点密度对照（v33，1 小时窗口）**

| 设置 | 实时速率采样点数 | 速率图绘制点数 | 流量统计采样点数 | 流量图绘制点数 |
|---|---|---|---|---|
| 实时 5 秒 / 流量 1 分钟（默认） | 720 | ≤ 720 | 60 | ≤ 12 |
| 实时 10 秒 / 流量 5 分钟 | 360 | ≤ 360 | 12 | ≤ 12 |
| 实时 5 秒 / 流量 30 分钟 | 720 | ≤ 720 | 2 | ≤ 2 |

> **产物仍只保留最终版**：延续 v30 起的交付策略，只保留 v33 的 `.tar` / `.zip`，删除 v32 及更早的版本化产物。
>
> 验证：后端断言全通过（配置默认值 / 7+7 档位 / 新表与新列 / 需求3 绘制点 ≤ 采样点 / 全 12 range × 2 metric 结构 / UNION 兼容 / 设置持久化）；真实 HTTP 端到端断言全通过（两条线程各自轮次与落库、`/api/settings` 双字段独立保存与即时生效、`/api/health` 反映新间隔）；无头 Chromium 验证绘图区**零 `<canvas>`**、四张 SVG 齐全、`<path>` / `<rect>` / `<line>` / `<text>` 均为矢量图元、刻度文字字体与 `body` 一致、流量统计卡片范围下拉已无「实时」、放大 200% 零 JS 错误。SW 缓存升到 `ttm-shell-v33`。**流量统计口径沿用 v15，零改动**，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v33.tar` 的 SHA256：`d8890ffce64307de93d9bf98be18db61f919009b9578408e9abb09d5b70817f8`

### v32

| 需求 | 实现 |
|---|---|
| **1. 继续彻底修复长实时范围曲线右端重绘** | 继续核对后定位到 v31 漏掉的**真正根因**在 `app.js::loadChart()` 的**数据签名**：签名含各系列末尾值，而 live 尾桶 AVG 每秒随新采样变化 ⇒ 签名每秒变 ⇒ `renderChart()` → `paintLines()` 每秒 `clearRect()` 清空整张数据层再全量重画，右端最新点每秒被擦掉重画一次；长窗口（30 分钟 `step=10s`）窗口推进很慢，观感就是「停顿后又被重绘」。v31 只在 `charts.js::drawLines()` 取消逐帧补间，没拦住「每秒全量重画」。参考 [PT Nexus v4.0.2](https://github.com/sqing33/PTNexus) `InfoView.vue` 的 ECharts 方案（`setInterval(fetchSpeedData,1000)` + `setOption` 由框架调度、数据未变化不 `setOption`），v32 让 **live 档周期刷新的签名只认 `times[0]`、点数和 series id**：窗口未推进就完全跳过重绘（连 `clearRect()` 都不执行），只有窗口真正推进才画一次并走 `shift` 帧平移。非 live 档保留原签名（含末尾值），切范围 / 拖动 / 增删下载器等非周期刷新一律照常重画。实测 30 分钟窗口 **13 次 1 秒周期刷新只触发 2 次 `drawLines`**（v31 约 13 次），且每次重绘都伴随 `times[0]` 推进；逐帧诊断确认不再出现「右端彩色像素先归零再画回」的擦除帧。**统计口径零改动** |
| **2. 提高 1/6/12 小时、今日、昨日的绘制点密度** | 后端 `chart.py` 新增 `RATE_DENSITY_ANCHORS=((3600,2),(21600,15),(86400,60))` 与 `_rate_target_step(span)`：按窗口跨度线性插值出「目标绘制点间隔」——**1h→2s/点、6h→15s/点、12h→30s/点、24h/昨日→60s/点**，中间跨度按比例插值（3h→7s/点、45min→2s/点、18h→45s/点）。`_sample_buckets()` 的 1h/6h/12h 与 `_rate_natural_buckets()` 的 fine 分支（今日/昨日，`samples` 保留期覆盖得到时）都按目标 step 给足点，`RATE_STEP_MAX_POINTS=2000` 兜底；**live 档仍按 `RATE_MAX_POINTS=180` 配套实时动画节奏**。前端 `app.js` 把 `targetPoints('rate')` 的上限改为**绘图区像素宽度**、`downsample()` 改为均匀分组恰好输出 M 个点，实现「**1 像素最多 1 个绘制点**」：算出一像素挤了多个点就按比例降密度，点数不超像素宽则原样保留、细节不丢。**统计口径零改动**（速率仍 AVG、流量仍 SUM，流量采样类仍固定 12 等分桶，`_fill_rate_gaps()` 头尾仍保持 None） |
| **3. 下载器列表取消竖向滚动框、按钮扁长化** | `style.css` 取消 `.table-wrap.config-table` / `.config-table` 的 `max-height`（桌面原 250px），不管多少台已保存下载器都直接铺开在页面上；顺序 ↑↓ 与操作 4 个按钮由 `40×30` 改为 **`44×26`**（横向略拉长、高度降低），视觉更扁长协调。实测 5 台与模拟 25 台下 `scrollHeight == clientHeight`、无竖向滚动框；桌面按钮精确 `44×26`，手机端沿用原布局不越界 |
| **4. 两张图纵坐标刻度 4 → 6** | `charts.js` 新增 `Y_TICKS=6`，`makePad()` / `gridY()` / `ticksY()` 三处循环由 `i<=4` / `i/4` 改为 `i<=Y_TICKS` / `i/Y_TICKS`，两张图纵坐标**非零刻度由 4 个增到 6 个**（连同 0 基线共 7 个刻度值 / 7 条网格线，与旧版「4 个非零 + 0 基线」口径一致）。实测速率图 `21.71 / 18.09 / 14.47 / 10.85 / 7.24 / 3.62 MB/s + 0 B/s`、流量图同样 7 档 |
| **5. 精确对齐 HSV 代码框与 RGB 的 R 值框** | 废弃 v31 的硬编码 `.cc-row .cc-hex{margin-left:15px}`（靠字体度量猜像素，桌面/手机各偏差 0.2px 且换字体就失效），改为**结构化同构 DOM**：`index.html` 把 HSV 行改成 `<label class="cc-numlike"><span class="cc-pfx">R:</span><input class="cc-hex"></label>`，RGB 行的 `R:` / `G:` / `B:` 也统一包成 `.cc-pfx`；`style.css` 用 `.cc-numlike .cc-pfx{visibility:hidden}` 让两行前缀等宽、`.cc-row .cc-tag{width:36px;min-width:36px;flex:none}` 固定标签列。实测桌面 1440 / 手机 390 下 HSV 代码框与 R 值框 `boundingClientRect.left` **差值均为 0.00px** |
| **6. 桌面端历史数据下拉框加宽 4 个中文字符** | 桌面端 4 张小卡片右上角历史数据下拉框由 `328px` 加宽到 **`384px`**（`min-width:288px→344px`），加宽量＝项目口径「4 个中文字符 ≈ 56px」；`.hist-list{overflow-x:hidden}` 消除底部横向滑杆。手机端保持 `328px` 不越屏。实测桌面菜单 `384px`，真实 / 压力数据下行与菜单均无横向溢出；「下载数据 ~ 日期」留白由 26~50px 提升到 **54~78px** |
| **7. 修复桌面端 3 个卡片描述被强制换行到第三行** | 桌面端 `.panel-head` 改 `position:relative`，右上角 `.pan-head-right` / `#lastUpdate` 改 `position:absolute;top:0;right:0`，让 `.ph-left` 独占整行宽度，第二行描述不再被右上角第一行文字挤到第三行。实测 1440 下 `下载器 / 实时速率 / 流量统计` 三个卡片 `.ph-left` 宽度比均为 **1.0**、hint 均为 **1 行**、右上角控件不越右边界且不与描述重叠 |
| **产物仍只保留最终版** | 延续 v30 起的交付策略：只保留 v32 的 `.tar` / `.zip` / 5 张 `preview-v32-*.png`，删除 v31 及更早的版本化产物 |

**绘制点密度对照（v32，桌面 1440 绘图区 1266px）**

| 时间范围 | 目标间隔 | 后端点数 | 桌面前端点数（≤ 绘图区像素宽） |
|---|---|---|---|
| 1 小时 | 2s / 点 | 1800 | 1266 |
| 6 小时 | 15s / 点 | 1440 | 1266 |
| 12 小时 | 30s / 点 | 1440 | 1266 |
| 今日（24h） | 按当前跨度插值（今日 0 点起，当前 1s / 点） | 随时刻递增 | ≤ 1266 |
| 昨日（24h） | 60s / 点 | 1440 | 1266 |

> **预览图 / 产物精简**：每版只保留 5 张主要界面图；v32 生成 5 张 `preview-v32-*.png` 并删除 v31 的 5 张。**交付产物只保留最终版**（旧版 tar / ZIP / 预览图不随版本累积）。

> 验证：本轮 **123 项断言全通过**（76 项 API / 静态资源回归 + 15 项实时动画与绘制点密度 + 32 项桌面·手机几何 / 主题 / PWA 专项），另加历史菜单真实数据专项复核；`_rate_target_step()` 锚点与单调性单测通过；长实时窗口 13 次刷新仅 2 次重绘且均伴随窗口推进；全量 12 range × 2 metric 结构完整；深浅主题切换、390px 手机端、manifest / sw.js 均正常，零 JS 错误；离线镜像 `docker load -i` 起容器往返正常。SW 缓存升到 `ttm-shell-v32`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v32.tar` 的 SHA256：`3f08e947d1df3e0c12f2e7db7fb77c00d6709f90c423632959a8071e04d8a8ba`

### v31

| 需求 | 实现 |
|---|---|
| **1. 修复长实时范围曲线右端「先露白、停顿、又重绘一遍」** | 逐帧 hook Canvas 绘制后定位根因：后端 live 窗口按 `poll_interval` 整数倍分桶，30 分钟窗口 `step=10s`，**每 10 秒才推进 1 桶**；而前端固定 1 秒刷新，其中约 9/10 的刷新**窗口根本没动**，只是尾部桶 AVG 随新采样变了。v30 对这些「未推进」刷新仍做 300ms / 约 20 帧逐点纵向补间（`scale`），画完再停顿约 700ms，于是长窗口下右端看起来「停顿一下、尾端又被重新绘制一遍」。短窗口 `step=1s` 每次刷新都推进、始终走帧平移，所以 3 分钟以内不明显，桌面端要到 30 分钟才暴露。**修复**：`charts.js::drawLines()` 中 `shiftPts===0`（窗口未推进）直接 `paintLines(...目标帧...)` 画终态、`_animMode='none'`，并立即更新 `_prevFrame`；**只有 `times` 判定窗口真实推进（`shiftPts>0`）才执行 `shift` 帧平移动画**。彻底删掉 `scale` 逐帧补间路径，保留 v30 的「动画帧全程用目标帧真实新值、形状恒定」逻辑，**统计口径、`times` / 分桶 / 采样点数量一律零改动**。实测 30 分钟窗口 11 次刷新里 **10 次单帧直接终态、1 次 20 帧帧平移**；3 分钟窗口 6 次刷新**全部仍是帧平移**，无 JS 错误 |
| **2. 全局留白 / 行距收紧、胶囊降高、绘图区高度翻倍** | `style.css` 末尾追加 v31 覆盖层：`.topbar` / `.panel` / `main` / `.card` / `.modal` / `.summary-grid` / `.panel-head` / `.hint` / `.chart-controls` / `.stats-summary` / `.legend` / `.dl-strip` / `.form-grid` / `.opt-row` 等的 `padding / gap / margin / line-height` 统一缩小；**全站胶囊按钮 `--btn-h:34px → 30px`**（用 `:root, :root[data-theme="dark"], :root[data-theme="light"]` 三选择器压过主题特异性），`.btn / .pill / .chip / .st-nav / .dd-trigger` 等 padding 同步收紧并锁 `height:30px`；**实时速率与流量统计两张图绘图区高度翻倍**：`.chart-lg` 桌面 **560px** / ≤900px **480px** / ≤560px **380px**（原 280 / 240 / 190px）。按新要求**不再保证手机首屏放下整张速率卡片**，只要首屏能看到绘图区即可 —— 实测 390×844 绘图区 `top=520 < 844`、桌面 1440×900 `top=559 < 900`，均首屏可见 |
| **3. 采样间隔新增 0.1 / 0.2 秒（放在最前）** | 全链路打通小数秒：`config.py` 的 `POLL_INTERVAL_CHOICES=(0.1, 0.2, 1, 3, 5, 10)`、新增 `POLL_INTERVAL_LABELS`、`in_choices()` 用 `1e-9` 容差匹配浮点、`_float_env()` 解析环境变量、下限由 `1` 放宽到 `0.1`；`main.py` 启动读库与 `POST /api/settings` 都改 `float()` 解析并归一到预设档位，返回选项带中文标签；`collector.py::set_interval()` 改 `max(0.1, float())`，`_loop()` 的 `_wake.wait()` 下限由 `max(1.0, …)` 改为 `max(0.01, …)`，否则亚秒档会被旧下限抬回 1 秒；`chart.py` 两处分桶把 `int(poll_interval)` 改为 `math.ceil(float(...))`，**图表 `times` / 桶边界仍按整数秒对齐**，亚秒档只提高 `samples` 写库密度与桶内 AVG 细腻度。前端 `renderCollect()` 用 `Number(o.value)` 取值，无需改动。实测 0.1 秒档保存 / 回显 / `/api/health` / `/api/chart`（`n=180, step=10, times 全 int, 无 None`）全部正常，**流量统计口径零改动** |
| **4. 固定右上角当前时间范围文字并与卡片名称对齐** | 拖动图表时「⟲ 回到最新」按钮出现 / 隐藏会让 `.pan-head-right` 高度变化，导致区间文字上下跳动。v31 给 `.pan-head-right` 设 `align-items:flex-start; min-height:22px`，`.pan-range` 与 `.latest-btn` 均 `align-self:flex-start`、`line-height:22px`，文字行盒恒定并与左侧卡片名称同一水平线。实测桌面 1440 / 手机 390 下 `#ratePanRange` 与 `.panel-head h2` **对齐差 0px**，按钮显隐前后文字位移 **dx=0 dy=0** |
| **5. 曲线颜色设置：HSV 代码框后移与 RGB R 框对齐** | 设置页 `.cc-block` 内第一行 `HSV∶` 代码框原本比第二行 `RGB∶` 的 R 值框偏左。v31 给 `.cc-row .cc-hex` 加 `margin-left:15px`，使两行数值框左边缘对齐。实测桌面对齐差 **0.2px**、手机 **-0.2px**（亚像素级，视觉完全对齐） |
| **6. 范围 / 方向按钮、弹出框、弹出框内胶囊按内容缩短并两端对齐** | `.chart-controls .ctrl-top` 保持 `space-between`，`.ctrl-dropdowns` `margin-left:auto`；`.dd-trigger` 由固定最小宽改为 `min-width:0; width:auto; padding:0 9px`，`.dd-menu` 改 `width:max-content; max-width:min(240px,86vw)`，`.dd-item` padding 收紧，胶囊与菜单都缩到刚好放下文字。实测桌面范围按钮 **114.4px** / 方向 **85.1px**、范围菜单 120px / 方向菜单 131.5px，手机 107.9 / 81px，**范围贴左、方向贴右，左右间隙均 0**，零换行零越屏 |
| **产物仍只保留最终版** | 延续 v30 起的交付策略：只保留 v31 的 `.tar` / `.zip` / 5 张 `preview-v31-*.png`，删除 v30 及更早的版本化产物 |

**实时曲线动画判定对照（v31 vs v30）**

| 场景 | v30 | v31 |
|---|---|---|
| 窗口未推进（长实时范围下占绝大多数） | 300ms / 约 20 帧 `scale` 逐点纵向补间 → 停顿 → 右端像被重绘 | **直接画目标帧终态（1 帧，`_animMode='none'`）** |
| 窗口真实推进 1 桶 | `shift` 帧平移（目标帧真实值、形状恒定） | 不变，仍为 `shift` 帧平移 |
| 短实时范围（step=1s） | 每次刷新都 `shift` | 不变，每次刷新都 `shift` |
| 右端「停顿后重绘」观感 | 30 分钟窗口明显 | 消失 |

> **预览图 / 产物精简**：每版只保留 5 张主要界面图；v31 生成 5 张 `preview-v31-*.png` 并删除 v30 的 5 张。**交付产物只保留最终版**（旧版 tar / ZIP / 预览图不随版本累积）。

> 验证：1315 项断言全通过（784 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 18 项内存专项 + 29 项 v31 浏览器专项 + 58 项 v31 专项 + 95 项离线容器往返）；`niceMax()` 12 组峰值占比全落在 78%~82%；离线镜像 `docker load -i` 起容器往返正常，镜像内源码文件与图标哈希一致。SW 缓存升到 `ttm-shell-v31`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v31.tar` 的 SHA256：`5f5bd132f816f313afac5eae39a0bbdd9c9030284ca876f52fdf3147f24c51b6`

### v30

| 需求 | 实现 |
|---|---|
| **速率卡片「时间范围」与「方向」回到同一行** | v29 把时间范围下拉移进了标题行右上角，位置不对。v30 把它移回 `.ctrl-top`，与方向下拉同一行：**时间范围在最左、方向在最右**（与流量统计卡片完全一致），标题行右上角只保留「回到最新」+ 区间文字。移除 v29 的 `justify-content:flex-end` 覆盖，让 `.ctrl-top` 默认 `space-between` 与 `.ctrl-dropdowns` 的 `margin-left:auto` 生效。实测 1440 / 1280 / 1152 / 1024 / 900 / 768 / 560 / 390 / 360 / 320px 共 10 档宽度，两控件始终同行、范围贴左 / 方向贴右、零换行零越屏 |
| **手机端区间文字恢复一行** | v29 在 `@media(max-width:560px)` 给 `.pan-range` 加了 `white-space:normal` + `max-width:88px` 导致换行。v30 恢复 `white-space:nowrap` 并去掉宽度限制；范围下拉移走后右上角只剩按钮 + 文字，空间充足。实测 560 / 390 / 360 / 320px，实时速率与流量统计两张卡片的区间文字都单行、不截断、不越屏 |
| **实时速率曲线：修复左移「反弹」与形状变化（含采样点核对）** | 实测后端 live 窗口每 `step` 秒才推进 1 个桶，而前端 1 秒刷新里约 89% 的请求**窗口根本没动**（只是尾部桶 AVG 随新采样刷新）；v29 无条件做 1 点距帧平移，这些刷新就「先左移、终态再跳回原位」＝**反弹**。且 v29 动画帧用「上一帧全部旧值 + 新末点」，窗口推进时末桶因 v24 尾部并入逻辑重算 AVG（实测 **28/29 点严格左移、仅 1 点变**），终态换成目标帧值时那点跳变＝「采样点取数变化 / 形状变化」。v30 按 `times` 判定真实推进桶数 `shiftPts`：**推进了**才做帧平移，动画帧 = 上一帧最前 `shiftPts` 个点补左边缘 + **目标帧全部 n 个真实新点**，整条曲线预偏移再以 cubicOut 左移回来，全程用真实新值、**形状恒定**，e=0 / e=1 分别与前后终态逐点重合；**没推进**就只做同一时间点数值与 Y 轴上限的纵向补间（上下伸缩），X 平移恒为 0、绝不空移弹回。另按用户要求：实时档前端不再按画布宽度降采样，**给足绘图区采样点密度**（避免聚合窗口滑动改变取数）；采样间隔长导致点数偏少时按点数自适应**放慢左移速度**（300ms → 最长 650ms）。**核对结论**：窗口推进时 28/29 点严格左移，仅末桶因 v24 尾部并入重算 AVG 有 1 点差异，属正常重算且已由动画平滑过渡，**统计口径零改动**，无需调整采样点数量 |
| **历史数据菜单内容改为中轴两侧两端对齐** | 宽度 328px 保持不变，仅调排版：每行以中轴线分成等宽左右两半、各半 `space-between` 两端对齐 —— 左半「周期名称（最左）… ↑ 上传数据（最右）」，**上传单位 `B` 是左半最后一个字符**；右半「↓ 下载数据（最左）… 周期时间（最右）」，**下载箭头 `↓` 是右半第一个字符**；两半之间仅 12px（手机 8px）留白。**不新增任何展示要素**，仍是名称 / 上传 / 下载 / 时间四项。实测 1440 / 768 / 390 / 360 / 320px 五档，`B` 贴中轴左、`↓` 贴中轴右，零重叠零越屏 |
| **产物只保留最终版** | 按新要求，交付目录**只保留最终版**的离线镜像 `.tar`、源码 ZIP 与 5 张预览图；v12~v29 的全部历史 tar / ZIP、v24 分享包 / 源码包、上一版 5 张预览图全部删除。后续每次更新同理，只给最后一版 |

**实时曲线动画判定对照（v30 vs v29）**

| 场景 | v29 | v30 |
|---|---|---|
| 窗口没推进（1 秒刷新里多数） | 仍左移 1 点距 → 终态跳回 = 反弹 | 只纵向伸缩，X 平移恒 0 |
| 窗口推进 1 桶 | 旧帧值 + 新末点，终态换值 → 1 点跳变 | 全程目标帧真实值，形状恒定 |
| 采样点密度 | 按画布宽度降采样（聚合窗口会滑动） | 实时档不降采样，给足后端点数 |
| 左移速度 | 固定 300ms | 点数少时自适应 300→650ms |

> **预览图收敛 / 产物精简**：自 v28 起每版只保留 5 张主要界面图；v30 生成 5 张 `preview-v30-*.png` 并删除上一版 5 张。**自 v30 起交付产物只保留最终版**（旧版 tar / ZIP / 预览图不再随版本累积）。

> 验证：1257 项断言全通过（784 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 18 项内存专项 + 29 项 v30 浏览器专项 + 95 项离线容器往返）；`niceMax()` 12 组峰值占比全落在 78%~82%；离线镜像 `docker load -i` 起容器往返正常，镜像内源码文件与图标哈希一致。SW 缓存升到 `ttm-shell-v30`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v30.tar` 的 SHA256：`04a3799f02a0a8785f29ca8445da22674722ce832b1a8c6dd2e168516373dc61`

### v29

| 需求 | 实现 |
|---|---|
| **桌面端速率卡片控件归位右上角** | v28 的 `.panel-head{flex-wrap:wrap}` 在 **≤1024px** 会把右上角「回到最新 / 区间文字」整组挤到卡片下一行左侧，时间范围下拉也一直放在第二行左侧。v29 把 `.panel-head` 改为**强制不换行**（左侧 `flex:1;min-width:0` 弹性收缩、右侧 `flex:none;flex-wrap:nowrap`），并把**时间范围下拉移入标题行右上角**，与「回到最新」按钮、区间文字同一行（顺序：范围下拉 → 回到最新 → 区间文字，区间文字仍在最右侧）；下拉改为向左展开避免越屏，方向下拉在控件行靠右对齐。实测 1440 / 1280 / 1152 / 1024 / 900 / 768 / 560 / 390 / 360 / 320px 共 10 档宽度，控件始终钉在卡片右上角、**零换行、零越屏** |
| **实时速率曲线改「帧平移」动画（参照并修正 PT Nexus v4.0.2）** | 逐行核对 [PT Nexus v4.0.2](https://github.com/sqing33/PTNexus) 的 `webui/src/views/InfoView.vue`：`fetchSpeedData` 每秒 `setOption()` 全量替换 series data、`smooth:true`、依赖 ECharts 默认 `animationDurationUpdate=300` / `cubicOut`。**发现其实现缺陷**：ECharts 按「数据项索引」补间，而实时窗口每推进一个桶整条数据左移一位，索引 j 的新值其实是旧帧索引 j+1 的值（经 downsample 滑动平均后二者都变），于是曲线在左移中持续**形变**，末点先沿用旧值、再突然改画最后一段 —— v28 的逐点插值同病。v29 改为**按时间轴对齐的帧平移**：动画帧数据 = 上一帧全部点 + 本帧真实最新末点，**不做任何逐点数值插值，形状恒定**；每帧整条曲线沿 X 轴平移 `e` 个点距，新末点以真实值从右边缘滑入、绘图区外裁剪；同时 y 轴上限从旧 max 补间到新 max，曲线随纵坐标变化**上下伸缩**；终态直接画目标帧。动画被交互 / 新帧打断时基准帧落到目标帧，杜绝末点回退跳变；`prefers-reduced-motion`、结构变化、非周期刷新仍直接画终态。实时档 1 秒刷新、保形 Hermite 平滑、数据签名节流、Y 轴自适应口径均零改动 |
| **历史数据下拉真正缩窄 4 个中文字符** | v28 桌面把 440px 改成 384px，但手机端 `min(384px,100vw-16px)` 在 390 屏被夹成 **374px，与 v27 的 `min(440px,…)`=374px 完全相同**，这正是用户反馈「没有修改到」的根因。v29 桌面 / 手机统一 **328px**（再缩 56px ≈ 4 个中文字符）、`min-width` 288px、列间距 10px；实测桌面 328px、手机 390 屏 328px（不再被夹成 374px），本周 `11-09~11-15` 长日期与中间 ↑↓ 数据各留 33px 以上、**零重叠、零越屏** |
| **HSV / RGB 两模式调色结果色块尺寸一致** | 固定 `.cp-left` 最小高度（桌面 140px / 手机 104px）与 `.cp-code` 行高（16px），RGB 模式只调字号不改占位；`.cp-preview` 显式 `box-sizing:border-box`。实测两模式色块都是 76×76px（手机 52×52px）、左列 132×140px、代码行 16px，**尺寸完全一致**，切换模式不再抖动 |
| **多级弹窗背景阴影只保留一层** | 「设置 → 测试结果 / 调色板」是二级弹窗，两层 `rgba(3,8,18,.72)` 遮罩叠加后背景近全黑。用 `:has()` 让 DOM 靠前的可见遮罩背景透明，只保留最顶层一层 0.72 遮罩；弹窗本体阴影不受影响。实测双层弹窗时**仅 1 个非透明遮罩** |

**PT Nexus v4.0.2 帧平移对照（v29）**

| 环节 | PT Nexus v4.0.2 | 本项目 v29 |
|---|---|---|
| 实时刷新 | 1000ms `setOption()` 全量替换 | 实时档 1000ms / 其余 5000ms，页面隐藏暂停 |
| 动画机制 | ECharts 默认按**索引**补间 → 左移时曲线形变 | **按时间轴对齐的帧平移**：形状恒定，只左移 + 纵向伸缩 |
| 末点 | 先沿用旧末值、再突变并补画末段 | 真实新值从右边缘滑入，旧末点平移为倒数第二点 |
| Y 轴上限 | `yAxisMax *= 1.2` | v25 自适应 `niceMax()`，动画中补间上限 |
| 曲线拟合 | `smooth:true` | 保形 Hermite（精确过采样点、段内不过冲） |

> **预览图收敛**：自 v28 起项目产物**只保留最后一版预览图，每版 5 张主要界面图**；v29 生成 5 张 `preview-v29-*.png` 并删除上一版 5 张，不再随版本累积。

> 验证：1267 项断言全通过（800 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 18 项内存专项 + 23 项 v29 浏览器专项 + 95 项离线容器往返）；离线镜像 `docker load -i` 起容器往返正常，镜像内源码文件与图标哈希一致。SW 缓存升到 `ttm-shell-v29`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v29.tar` 的 SHA256：`5a4a2897f3bf0dd97b531f09fb2fa5b3619212be25e7619254712c3d958c1b12`

### v28

| 需求 | 实现 |
|---|---|
| **设置页颜色说明删净、曲线颜色设置改两行布局** | 删除下载器设置页顶部关于颜色设置的整段 `<p class="hint">`。原 v27 「上传 / 下载各一行」的 `.cc-line` 改成 `.cc-block` **两块**：每块左侧 `.cc-side` 放「上传 / 下载」文字与颜色方块，**整体垂直居中于右侧两行中间**；右侧 `.cc-fields` 分两行 —— 第一行 `HSV∶` + 大写 hex 代码框，第二行 `RGB∶` + R / G / B 三个数值框。两种数值仍与取色器、调色板、自动分配双向同步，键盘可直接输入 |
| **调色板结果色块移到三条滑块左侧** | 点色块弹出的 HSV / RGB 调色板，把结果色块与颜色代码从滑块**上方**移到**左侧并整体垂直居中**（`.cp-body` 由 `align-items:start` 改 `center`，`.cp-left` 独占左列）：**色块在上、代码在下**；HSV 显示 `#F56C6C` 大写样式、RGB 显示 `RGB(245,108,108)`，RGB 代码较长时 JS 给 `#cpCode` 加 `.is-rgb` **自动调小字号**（桌面 12→11px、手机 10→9px）。手机端 `.cp-body` 不再上下堆叠，改为 `100px / 1fr` 左右栅格，保持左右布局不越屏 |
| **实时速率折线按 PT Nexus v4.0.2 重做动画与刷新** | 逐行核对 [PT Nexus v4.0.2](https://github.com/sqing33/PTNexus)（`webui/src/views/InfoView.vue`、`server/internal/service/stats/speed.go`）：实时档 `setInterval(fetchSpeedData, 1000)`、`series.smooth:true` / `showSymbol:false` / `yAxisMax *= 1.2`、靠 `setOption()` 增量更新触发 ECharts 默认动画。本项目用原生 Canvas 做等价实现：① **实时档刷新由 5 秒改为 1 秒**、其余档仍 5 秒、`document.hidden` 暂停；② 折线默认 `smooth:true`，沿用 v18 的单调三次 Hermite / Fritsch–Carlson **保形拟合**（精确过采样点、段内不过冲、不抹平瞬时峰值）；③ `ANIM_MS = 300` 对齐 ECharts `animationDurationUpdate`、`easeCubicOut(t)=1-(1-t)³` 对齐 `cubicOut`，记住上一帧 `{max, lines.values, n}`，结构一致时用 `requestAnimationFrame` 对 **Y 轴上限与每条折线逐帧补间**；④ 固定 `padMax` 画左侧刻度避免动画中坐标轴抖动，`dispMax` 用于插值中的映射与刻度数字；⑤ `prefers-reduced-motion`、结构变化、hover / 拖动 / resize / 切主题等非周期刷新直接画终态；⑥ `loadChart()` 增加**数据签名**（末点时间 / 点数 / 每条线末值），周期性轮询若数据未变则跳过重绘与动画，只更新区间文字，避免 1 秒轮询反复空转 |
| **「历史数据」下拉缩窄 4 个中文字符宽** | v27 为消除长日期重叠把菜单统一加宽到 440px，但桌面偏宽。v28 按约 14px/字缩窄 4 个中文字符（56px）到 **`width:min(384px, 100vw - 16px)`、`min-width:344px`**，`.hist-row` 列间距 16→12px；实测桌面 384px / 手机 374px，本周 `11-09~11-15` 等长日期与中间 ↑↓ 数据仍各有 60px 以上留白、**零重叠、零越屏** |
| **「增加下载器」测试连接按钮补齐反馈** | 旧表单按钮只写一行 `#formMsg` 小字、无按钮态、与配置表「测试」的独立弹窗体验不一致，用户感觉「点了没反应」。v28 统一为：点击后按钮 `disabled` + 文案「测试中…」、`formMsg` 立即显示「正在测试连接…」、**12 秒慢响应兜底**提示，成功 / 失败都调用 `openTestResult()` 弹出与配置表同款的独立结果窗口（连接状态 / 实时上传下载速率 / 版本 / 类型 / 地址），`finally` 复位按钮 |

**PT Nexus v4.0.2 速率图实现对照（v28）**

| 环节 | PT Nexus v4.0.2 | 本项目 v28 |
|---|---|---|
| 实时刷新 | `setInterval(fetchSpeedData(mode, true), 1000)` | 实时档 1000ms / 其余档 5000ms，页面隐藏暂停 |
| 曲线拟合 | `smooth: true`、`showSymbol: false` | `smooth: true` + 保形 Hermite、无采样点圆点 |
| Y 轴上限 | `yAxisMax *= 1.2` | v25 自适应 `niceMax()`（峰值占 78%~82%），动画中逐帧补间 |
| 更新动画 | `setOption()` 增量更新 → ECharts 默认 `animationDurationUpdate` | `ANIM_MS=300` + `cubicOut` + `requestAnimationFrame` 补 `max` 与 `values` |
| 空转规避 | — | 数据签名节流，未变则跳过重绘 |

> **预览图收敛**：自 v28 起项目产物**只保留最后一版预览图，每版 5 张主要界面图**，历史各版（`preview-v7`~`preview-v27`，共 422 张）全部清理，不再随版本累积。

> 验证：**1256 项断言全通过（785 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 18 项内存专项 + 27 项 v28 浏览器专项 + 95 项离线容器往返）**；离线镜像 `docker load -i` 起容器往返正常，镜像内源码文件与图标哈希一致。SW 缓存升到 `ttm-shell-v28`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v28.tar` 的 SHA256：`5c4939b07f3fe4847b90397533bb2743fd2cfb224130720c06577ec4a8dbf019`

### v27

| 需求 | 实现 |
|---|---|
| **「历史数据」下拉统一加宽，长日期不再与中间数据重叠** | 顶部 4 张卡右上角触发文案由「历史周期 ▾」改为「**历史数据 ▾**」（菜单标题仍为「历史周期数据」）。v26 菜单宽 320~380px、行用 grid `minmax(0,1fr) auto minmax(0,1fr)`，日期列可被压到 0 宽，`white-space:nowrap` 的长日期（本周 `11-10~11-16`）便溢出压住中间 ↑↓ 数据。v27 把菜单**统一加宽到 440px**（`min-width:400px`、`width:min(440px, 100vw - 16px)`），行改为 **`max-content / minmax(0,1fr) / max-content`**：名称与时间两列按内容完整宽度分配、绝不收缩，中间 1fr 吸收剩余宽度并居中，两端对齐。手机端同步夹在 `100vw - 16px` 内、压缩字号与留白，配合 `keepMenuInViewport()` 水平夹取，320 / 360 / 390px 都不重叠、不越屏。无限下滑、每次展开回到最近周期等逻辑零改动 |
| **默认配色改用 PT Nexus 源码精确色板并按顺序分配** | 逐行核对 [PT Nexus](https://github.com/sqing33/PTNexus) 流量统计页 `vue3/src/views/InfoView.vue`，找到它真正的默认色板与分配逻辑：`uploadColors = ['#F56C6C','#E6A23C','#D98A6F','#FAB6B6','#F7D0A3']`、`downloadColors = ['#409EFF','#67C23A','#8A2BE2','#A0CFFF','#B3E19D']`，`color: colors[index % colors.length]` —— **上传一组暖色 / 下载一组冷色，按下载器顺序固定分配**。v25 从用户截图逐点取色得到的是这套标准色的近似值（±2~3 误差），v27 直接采用源码精确值并补 5 组同风格协调色凑满 10 组；`next_palette_index()` 与前端 `autoColors()` 同时改为 `count % len`，与 PT Nexus 一致 —— 新增第 n 台正好拿到第 n 组，默认配色好看且 5 台区分度最高。新增 `palette_v27` 幂等迁移，只替换仍是 v25 / v16 系统默认的下载器，**手动改过的自定义配色原样保留**，历史流量数据零影响 |
| **曲线颜色设置区与调色板整体重做** | 废弃 v26 两个布局差异很大的 HSV / RGB 面板，改为统一「曲线颜色设置」区块：左上标题、右上保留「自动分配」按钮；第二 / 三行是**完全一致的模板** —— `上传 / 下载　颜色方块　HSV∶代码框　RGB∶R 数值框 G 数值框 B 数值框`。所有数值框**既返显**自动分配与调色板调出的结果，**也支持键盘直接输入**；点颜色方块弹出独立调色板：顶部居中是沿用现版样式的 **「HSV 调色板 / RGB 调色板」二选一胶囊**，左侧结果色块 + 当前模式结果代码（HSV 为 `#F56C6C` 大写样式，RGB 为 `RGB(245,108,108)`），右侧统一三条滑块（HSV＝色调 / 饱和度 / 明度，RGB＝红 / 绿 / 蓝三原色），每条左侧指标名、右侧数值输入框，滑块与输入框实时互相同步并同时调整颜色。隐藏的 `<input type=color>` 保存唯一颜色真值，保存时仍以它为准。**代码框 / 调色结果 / 配置表悬停标题 / 示例配置 / 本文档里所有可见的 HSV 颜色代码字母统一大写**（数据库仍存小写 hex） |

**PT Nexus 精确默认色板（v27，界面展示大写）**

| 顺序 | 上传 | 下载 |
|---|---|---|
| 1 | `#F56C6C` 珊瑚红 | `#409EFF` 亮蓝 |
| 2 | `#E6A23C` 琥珀橙 | `#67C23A` 草绿 |
| 3 | `#D98A6F` 赭棕 | `#8A2BE2` 亮紫 |
| 4 | `#FAB6B6` 浅粉 | `#A0CFFF` 浅蓝 |
| 5 | `#F7D0A3` 浅杏 | `#B3E19D` 浅绿 |

> 验证：**1251 项断言全通过（781 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 18 项内存专项 + 26 项 v27 浏览器专项 + 95 项离线容器往返）**；离线镜像 `docker load -i` 起容器往返正常，镜像内源码文件与图标哈希一致。SW 缓存升到 `ttm-shell-v27`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v27.tar` 的 SHA256：`3a84202d55367d2030287c4ef0799669a22366553ac83747dee67e59cda7803f`

### v26

| 需求 | 实现 |
|---|---|
| **实时速率折线整体调细、汇总与单台两级明显区分** | 旧版汇总线 `3.2px` / 单台 `1.7px` 都偏粗。v26 把**汇总线降到原单台粗细 `1.7px`**、**单台再调细到 `0.9px`**，两者接近 2 倍差距、一眼可分；hover 拐点圆点也按粗细分级（汇总 `4px` / 单台 `2.5px`），强化区分。折线与堆叠柱的其它绘制逻辑、Y 轴自适应口径零改动 |
| **顶部 4 张卡片右上角改为「历史周期数据」清单（不再是单选）** | 卡片**恒显示当前时间周期**（今日 / 本周 / 本月 / 本年）的上传下载合计，右上角胶囊样式不变、文案固定为「历史周期 ▾」提示可下拉。菜单标题统一为 **「历史周期数据」**；每行模板 **`周期名称` ＋ `↑ 上传值 ↓ 下载值`（与卡片同格式、同色） ＋ `该周期时间`**，三块用 grid `1fr / auto / 1fr` 排版：**名称左、数据居中、时间右**（两端对齐），字号统一 12px、块间留白 12px、**内容完整不省略**；菜单加宽到 320~380px 且夹在 `100vw - 16px` 内，配合视口夹取保证不越屏。**「单选后把历史数据填进小卡片」的功能与 `S.period` / `ttm_period` / radio 相关代码全部删除**。4 张卡统一首屏固定 10 个历史周期，向下滚动**按批加载更早周期、不设最早下限**（后端 `/api/periods/page` 按 `start / count` 生成任意序号的周期，超出采集起始的周期数据为 0 但仍照常列出）；**每次重新展开菜单都重置 `start=0`、滚动归零，默认回到距当前最近的周期** |
| **全项目内存优化：长跑 >1 个月稳定 ≤50MB** | 实测容器跑一天 RSS 由 30MB 涨到 110MB。压测定位为**分配器把堆扩到并发峰值后不归还**（多核 glibc 默认按线程开大量 arena + waitress 8 线程 + 每请求反复新建 SQLite 连接 / 构造图表对象），非逐轮泄漏。v26 组合治理：① `Dockerfile` 加 **`MALLOC_ARENA_MAX=2`** 限制 glibc arena 数量、waitress **`--threads=8 → 4`** 压低并发峰值；② 新增 `app/memory.py`，采集循环**每 60 秒 `gc.collect()` + `malloc_trim(0)`** 主动归还空闲页，清理 samples 时截断 WAL；③ `db.conn()` 加 `PRAGMA cache_size=-512 / mmap_size=0`，削平每连接约 2MB 的瞬时 page cache；④ 详情 / 汇总缓存改为 **TTL 惰性释放 + 条目上限**、登录失败记录过期清理、启动时 `gc.freeze()` 冻结常驻对象；⑤ 前端页面隐藏时暂停轮询（不发请求、不分配图表对象）。**流量统计口径、所有 API 数值零改动** |
| **设置页颜色选择器：HSV 调色板 + RGB 三滑块，两种模式** | 保留原有 **HSV 原生取色器**（点色块打开系统 HSV 调色板）与可粘贴的 `#RRGGBB` 文本框；新增 **RGB 模式**：上传 / 下载各一组 **R / G / B 三滑块（0~255）+ 实时数值 + 色块预览 + 当前色值**，滑动即时换算 hex。两种模式用胶囊 tab 切换、共用同一份颜色值**双向同步**（任一处改动都写回取色器，保存恒以取色器为准），切换到 RGB 时按当前色自动回填滑块。排版为纵向「模式条 + 面板」，RGB 面板双栏自适应、窄屏自动换行 |

**内存压测**（同一脚本 9600 次 API 请求 / 8 并发，记录进程 RSS；采集线程照常每 3 秒轮询 5 台下载器写库）：

| 场景 | 起始 | 结束 | 增长 | 峰值 |
|---|---|---|---|---|
| v25 基线（原配置，无 arena 限制） | 37.0 MB | 81.2 MB | +44.2 MB | 81.2 MB |
| v26 代码 + 同进程模型（**仅代码层优化**：trim / PRAGMA / 缓存 / gc.freeze） | 36.2 MB | 57.5 MB | +21.3 MB | 57.5 MB |
| **v26 容器真实配置**（上面再叠加 `MALLOC_ARENA_MAX=2` + waitress 4 线程 + 60s 回收） | 36.4 MB | **42.9 MB** | **+6.6 MB** | 43.8 MB |

分离变量可见：**代码层回收把增长砍掉一半（+44.2 → +21.3），容器层限制 arena 数量与并发峰值再压到 +6.6**。中间那行用的是开发服务器（本项目容器从不使用），仅用于拆分贡献；真实容器是最后一行，全程稳定在 42~44MB、呈锯齿回落（每次 `trim` 把空闲页还给内核），无随时间累积的趋势，**长跑稳态远低于 50MB 目标**。

> 验证：**1268 项断言全通过（798 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 18 项内存专项 + 26 项 v26 浏览器专项 + 95 项离线容器往返）**；另用 node 直接执行 `niceMax()` 对 12 组峰值逐一验证，Y 轴占比全部落在 78%~82%，三组内存压测数据见上表。离线镜像 `docker load -i` 起容器往返正常，镜像内 18 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v26`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v26.tar` 的 SHA256：`e7d32be1f869eeed050a8e6aad32995ec1710e4c7ae656b266b2c1932d9dbe5e`

### v25

| 需求 | 实现 |
|---|---|
| **实时速率 / 流量统计纵坐标按当前显示范围自适应缩放** | 旧版 `niceMax()` 把上限取整到 1 / 2 / 5 / 10 量级再乘 1.15，又把最小上限抬到 1024，导致峰值常常只占绘图区 20%~50%，所有曲线和柱子挤在下半部分、小数值系列互相重叠。v25 改为贴合「当前可见数据的真实峰值」：①取真实峰值 `peak`（`floor` 只在全 0 时兜底，不再抬高小数）；②目标上限 `target = peak / 0.82`；③在细粒度阶梯（1 / 1.1 / 1.2 / 1.25 / … / 10）里挑一个刻度好看且 ≥ `target` 的上限；④若取整后峰值占比跌破 78%，退回精确 `target`。**任何数据下峰值都稳定落在绘图区 78%~82% 高度**（略留余量避免贴顶），折线与堆叠柱共用同一套逻辑；切换范围 / 方向 / 拖动窗口时都随当前显示范围实时重算。`drawBars()` 的 `_geom` 同时暴露 `max`，便于回归脚本核对柱高占比 |
| **TR 错误种子数对齐 TrguiNG，消除「总比 Web 端多 1 个」** | 用户 TR Web UI 使用 [TrguiNG](https://github.com/jayzcoder/TrguiNG)。逐行核对 `src/rpc/torrent.ts` 的 `getTorrentError()` 与 `src/components/filters.tsx` 的「错误」分组条件（`error !== 0 \|\| cachedError !== ""`）后定位根因：TrguiNG 只在 tracker **已宣告且失败**（`hasAnnounced && !lastAnnounceSucceeded`）时才把 `lastAnnounceResult` 当作错误串；**只要有任一 tracker 正常 / 成功 / 结果为 `Success`，或种子处于 stopped(0)，整颗种子就忽略全部 tracker 错误**；tracker 错误串与全局 `errorString` 相同时还会去重。v24 用「任一 tracker 命中致命关键词即判错」的宽松匹配，把「一个 tracker 失败、另一个正常」的种子也算成错误 —— 这正是多出来的那 1 个。v25 新增 `_tr_torrent_error(t, status)` 完整复刻 TrguiNG 的 `cachedError` 生成，`detail()` 的判定改为 `error !== 0 \|\| cachedError !== ""`；`torrent-get` 继续请求 `errorString / trackerStats`。mock 补齐 `hasAnnounced / errorString` 并新增「部分 tracker 失败」干扰种子，用于回归验证：旧逻辑会多算 1 个，v25 与 TrguiNG 一致。**qB 侧判定与错误数完全不变**，汇总详情仍为 3×4 + 2×3 = 18 |
| **手机端流量统计图例箭头前加回颜色图块** | v24 手机端为省空间把 `#trafficLegend .sq` 与字样、完整值一起隐藏，只留 `名称 ↑量 ↓量`。v25 保留颜色图块（缩到 9px、圆角 2px），仍隐藏「上传 / 下载」字样与完整值，模板变为 **`名称 ■↑量 ■↓量`**；「实时速率」图例本来就带色块，两张图手机端的视觉认知终于统一。桌面端图例完全不变 |
| **按参考图精确复制 5 台下载器的 10 条曲线颜色** | 从用户提供的截图逐点取色（核心区中位数 + 众数 + 中心 5×5 均值三种方法交叉校验，误差 ±3），得到 5 组色值。`db.py` 新增 `USER_PALETTE_V25` 作为前 5 组默认色（第 6~10 台沿用 v16 的 OKLab 寻优色，保证 10 组齐全），并新增 `palette_v25` **幂等迁移**：升级时按 `sort_order` 把「仍是 v16~v24 系统默认色」的下载器换成新配色，**手动改过任一颜色的视为自定义配色、原样保留**，历史流量数据完全不受影响。设置页颜色行新增可直接粘贴 `#RRGGBB` 的文本框，与取色器**双向同步**（非法值自动回写原值），便于把任意参考配色精确复制进来；`config.example.json` 同步新首色 |

**配色对照表**（顺序＝下载器 `sort_order`，即截图自上而下）：

| 顺序 | 下载器 | 上传色 | 下载色 |
|---|---|---|---|
| 1 | qb | `#F46C6A` 珊瑚红 | `#419DFF` 亮蓝 |
| 2 | tr | `#E7A33A` 琥珀橙 | `#65C337` 草绿 |
| 3 | tr1 | `#D78970` 赭棕 | `#892BE2` 亮紫 |
| 4 | qb1 | `#FAB6B7` 浅粉 | `#9FCFFF` 浅蓝 |
| 5 | tr2 | `#F7D0A8` 浅杏 | `#B1E19C` 浅绿 |

> 想换别的配色：设置 → 下载器 → 编辑某台 → 颜色行右侧文本框直接粘贴 `#RRGGBB`（取色器同步变化）→ 保存即可；点「自动分配」会按当前色板重新分配全部下载器。**只有从未手动改过颜色的下载器才会在版本升级时被系统迁移**，自定义配色永远保留。

> 验证：**1185 项断言全通过（748 项 API + 161 项浏览器 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 11 项 v25 浏览器专项 + 95 项离线容器往返）**，另用 node 直接执行 `niceMax()` 对 12 组峰值逐一验证，Y 轴占比全部落在 78%~82%；离线镜像 `docker load -i` 起容器往返正常，镜像内源码文件与图标哈希一致。SW 缓存升到 `ttm-shell-v25`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v25.tar` 的 SHA256：`426229e8334cda2d869abca85067865d8a74553a697b997d708d055a712c2ea3`

### v24


| 需求 | 实现 |
|---|---|
| **详情页「错误种子」与 qB / TR WebUI 对齐** | 旧版只把 qB 的 `state=error / missingFiles` 算作错误，`tracker 连不上`、`种子未在 tracker 注册` 这类种子仍然是 `stalledDL / queuedDL / downloading` 等状态，WebUI 却把它们归进「Errored」，于是本项目错误数偏少。v24 双管齐下：① `QB_STATE_KEYS` 把 qB 5.1+ / 增强版可能返回的 `tracker_down / tracker_error / unregistered / errored` 直接映射为 `error`；② 老版本 qB 的 `state` 不含 tracker 信息，`detail()` 按需**并发读取 `/api/v2/torrents/trackers`**（排除 `[DHT]/[PeX]/[LSD]` 伪 tracker），按关键词判定 —— 「未注册 / passkey 失效 / 被删」等致命错误任一命中即算错误，「连不上 / 超时 / 域名解析失败」需**所有真实 tracker 都失败**才算（避免单个 tracker 抖动误报）。TR 侧 `torrent-get` 补请求 `errorString / trackerStats`，`error=0` 但 tracker 明确报错的种子同样计入。命中种子从原互斥类别**挪到** `error`（不重复计数），暂停态不额外请求；单个请求失败静默降级，不影响其它统计 |
| **实时速率 / 流量统计范围下拉末尾新增「全部」** | 两张卡片的范围由 11 档扩到 **12 档**，最后一项「全部」用于展示**数据库中所有已采集的数据**。`chart.py` 新增 `_all_buckets()`：起点取 `samples` 与 `hourly` 的最早时刻、终点为当前时刻，按跨度自适应「小时整数倍」粒度（目标 120 点、下限 24、上限 180），两张卡片**共用同一套桶**；`rate` 用 `SUM(字节)/覆盖秒数` 算平均速率、`traffic` 用 `SUM(字节)` 算流量，与原有 `hourly` 口径一致。前期无数据的桶保持空（v21 语义），不画假的水平线。前端 `RANGE_ORDER / RANGE_LABELS / NATURAL_RANGES` 同步，旧 localStorage 状态里的 11 档值仍全部有效 |
| **逐一核对 12 档范围，修复图表数据遗漏** | 用户反馈「有些时间范围实际图表展示的单位不足」。逐范围核对后发现**三处真实遗漏**：① `_rate_natural_buckets()` 用 `n = span // step` 向下取整，`window.end` 也取 `start + n*step`，导致「不足一个完整桶」的尾部数据被整段丢弃 —— 实测 `上月` 漏 10 行 / 808 亿字节（2 小时）、`本年` 漏 5904 行 / 3517 亿字节（约 8 小时）；② 采样类窗口（实时 / 1 / 6 / 12 小时）把「最近不足一个 `step`」的采样整段排除，实测 `6h` 漏 20 行、`12h` 漏 84 行；③ 区间文字的终点取的是**最后一个桶的起点**，比实际覆盖少一整个桶（小时 / 天 / 月，本年流量图甚至少 30 天），这正是「单位不足」的直观来源。v24 修法：`n` 改 `ceil(span/step)` 让尾部也拥有时间点、`window.end` 直接取硬边界（当前时刻 / 完整过去周期右边界）并把 SQL 查到它；采样类把尾部 `b==n` 的采样**并入最后一个桶**（点数不变，不重演 v16 的尾部空白）；区间文字终点改为 `min(window.end, hard_end)`。**12 档 × 2 指标共 24 组全部核对通过：窗口尾部零遗漏、区间文字终点正确、数据点覆盖完整**（核对明细见下表） |
| **当前时间区间文字改为一直显示、放最右侧** | v23 的区间文字只在拖动后出现、且放在「⟲ 回到最新」按钮前面。v24 把两张卡片标题右侧的 DOM 顺序改为 `[回到最新 按钮] [区间文字]`：区间文字**始终显示**（最新时也显示当前最新窗口的完整区间，如 `11-09 00:00 ~ 11-09 17:12`）、位于标题行**最右侧**；「回到最新」按钮移到文字**左侧**，仍只在拖动后（`offset>0`）出现，**当前显示范围为最新时隐藏**。手机端文字允许换行、右对齐 |

**逐范围核对结果**（演示库 2026-03-01 起、当前 11-09，12 档 × 2 指标）：

| 范围 | 速率点数 | 流量点数 | 区间文字示例 | 修复前遗漏 |
|---|---|---|---|---|
| 实时 / 1 / 6 / 12 小时 | 30 / 180 / 180 / 180 | 12 / 12 / 12 / 12 | `11-09 17:06 ~ 11-09 17:11` | 6h 漏 20 行、12h 漏 84 行（尾部不足一个桶） |
| 今日 / 昨日 | 177 / 180 | 18 / 24 | `11-09 00:00 ~ 11-09 17:11` | 区间文字终点少 1 个桶 |
| 本周 / 上周 | 177 / 84 | 1 / 7 | `11-09 00:00 ~ 11-09 17:11` | 区间文字终点少 1 天 |
| 本月 / 上月 | 105 / 107 | 9 / 31 | `11-01 00:00 ~ 11-09 17:11` | 上月速率漏 10 行 / 2 小时 |
| 本年 | 120（头 22 桶留白） | 11（头 2 月为 0） | `01-01 00:00 ~ 11-09 17:11` | 速率漏 5904 行 / 约 8 小时 |
| **全部（新）** | 120 | 120 | `2026-03-01 ~ 2026-11-09` | 新增，覆盖全库 |

> 验证：**1142 项断言全通过（716 项 API + 161 项浏览器 v24 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 95 项离线容器）**；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v24`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v24.tar` 的 SHA256：`0f1bf42cca9b18c87df7c85293ca296077403aed367f71986366f0d8340ba702`

### v23


| 需求 | 实现 |
|---|---|
| **实时速率卡片横轴刻度不再挤成一团（只调刻度、不动采样点）** | 旧版 `axisX()` 用写死的 `estW`（52 / 58px）估算能放几个刻度，但「今日 / 昨日 / 本周 / 上周 / 本月 / 上月」等自然周期的横轴标签是 `%m-%d %H:%M` 这类 11 字符的日期时间串，实际文字宽度远大于 58px，于是相邻刻度文字贴在一起、难以阅读。v23 给 `axisX()` 增加 `measure` 参数，用 `ctx.measureText()` **实测最长标签的文字像素宽度**，取 `max(estW, 实测宽度 + 18px)` 作为刻度间距，再按画布绘图区宽度算出最多画几个刻度。关键约束：**只改变「画几个刻度文字」**，`labels / times / spans / series`、后端分桶、前端 `downsample()` / `targetPoints()` 全部零改动，11 档范围的采样点数量一个不少，折线密度与 v22 完全一致。速率折线 `drawLines()` 传 `measure=true`；**流量统计柱状图 `drawBars()` 仍走原来的 `estW=56/64` 逻辑**，短标签窗口（采样类 `%H:%M`）实测宽度小于 `estW` 时由 `estW` 兜底、刻度保持原样 |
| **汇总详情首行「汇总实时」字号对齐** | 汇总卡弹出的详情窗口第一行「汇总实时」标签原本是小号灰字，与同一行右侧的实时速率数字明显不协调。v23 把 `.dt-sum-rates .dt-k` 字号统一为 **16px**，与同行 `.dt-sum-rates b` 的实时速率完全一致（桌面 / 手机端同步生效） |
| **停用下载器后主界面「所有展示内容」全部取消** | 旧版「启用 / 停用」只让采集器跳过该下载器，主界面仍留着它的卡片、图例、曲线、堆叠柱与汇总详情。v23 把 `db.list_downloaders(enabled_only=True)` 从采集层扩展到**全部展示层**：`overview()`、`chart.build()`、`/api/downloaders/summary/detail` 逐台清单、`stats.py` 的 `period_series()` / `period_totals()` 顶部周期统计，SQL 统一加 `WHERE downloader_id IN (SELECT id FROM downloaders WHERE enabled=1)`。停用后该下载器从**下载器卡片、两张图的图例 / 折线 / 堆叠柱 / 汇总线、汇总详情逐台清单、顶部 4 张周期卡**中全部消失；重新启用后立即回归。**配置表 `/api/downloaders` 仍返回全部下载器**（含停用的），方便随时重新启用；历史流量数据不删除，只是不计入展示 |
| **点击「测试」弹出独立小窗口** | 旧版配置表「测试」按钮只把结果写在表单底部一行小字上，容易被忽略。v23 新增 `#testModal` 小窗口：标题为「连接测试 · 下载器名称」，正文按成功 / 失败分别展示**连接状态、实时上传 / 下载速率、版本号、下载器类型、完整地址**（或错误信息），并保留 `#formMsg` 兼容文案。点 `✕ 关闭`、Esc 关闭；点击遮罩空白**一律忽略**（与详情弹窗一致，不会误关） |
| **拖动图表后在「回到最新」按钮前显示当前时间区间** | 后端 `chart.py` 早已返回 `window{start,end,label}`，前端也存进了 `S[which].windowLabel`，但一直没显示。v23 在两张卡片标题右侧新增 `.pan-head-right` 容器：`#ratePanRange` / `#trafficPanRange` 放在「⟲ 回到最新」按钮前面，拖动到历史窗口（`offset>0`）时与按钮**同步出现**，显示后端生成的当前图表时间区间文字（如 `11-09 00:00 ~ 11-09 14:00`）；点「回到最新」后与按钮**一起隐藏**。手机端区间文字允许换行、右对齐，字号固定 10px 与刻度一致 |

> 验证：**995 项断言全通过（596 项 API + 138 项浏览器 v23 UI 专项 + 87 项深度专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 91 项离线容器）**；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v23`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v23.tar` 的 SHA256：`46b0c0c40511d85b8a623a94375737ae4dfa98ee9cb66c7845706309cc2623f2`

### v22


| 需求 | 实现 |
|---|---|
| **时间范围新增「昨日 / 上周 / 上月」** | 「范围」单选下拉由 8 档扩到 **11 档**，顺序与 [PT Nexus](https://github.com/sqing33/PTNexus) 的速率图一致：`实时 / 1小时 / 6小时 / 12小时 / 今日 / 昨日 / 本周 / 上周 / 本月 / 上月 / 本年` —— 三个新档分别紧跟今日 / 本周 / 本月。内部 key 为 `yesterday / lastweek / lastmonth`；下拉菜单 `max-height` 由 320px 放宽到 **380px**，桌面端 11 项一屏可见、窄屏滚动。两张图表卡片共用同一份范围列表，选择照旧写入 localStorage，升级后旧状态里的 8 档值仍全部有效 |
| **速率图按 ptnexus 取值逻辑重做：本周一不再只有 1 个点** | 旧版把分桶粒度**写死在周期名称上**（本周按天、本月按天、本年按月），于是**本周一只有 1 个点**、本月 1 号也只有 1 个点。ptnexus 的 `resolveTimeRange()` 里，速率图粒度**由窗口跨度决定**：今日 / 昨日按分钟、本周 / 上周按小时、本月 / 上月按天，`duration > 60 天` 强制按天、`> 365 天` 按月；`GetSpeedChartData()` 再用「最近 3 天细粒度原始表 + 更早粗粒度小时表」的 **near-fine / far-coarse** 混合查询。v22 把这套思想落到 `chart.py`：新增 `_rate_natural_buckets()`，先按自然周期算出窗口 `[周期首日 0 点, 当前时刻 / 周期右边界)`，再按跨度自适应选粒度 —— **跨度 ≤48 小时**且 `samples` 覆盖得到就直接取采样点（`AVG`，桶宽＝采样间隔整数倍、上限 180 点）；**跨度 >48 小时**改查 `hourly`，桶宽取「小时整数倍」，目标 **120 点**、任何窗口**下限 24 点**、**上限 180 点**（`RATE_TARGET_POINTS / RATE_MIN_POINTS / RATE_MAX_POINTS`）。实测今天正好是周一：`本周`由 1 点变成 **170 余点**（随当前时刻浮动），`昨日` 180 点、`上周` 84 点、`本月` 100 点、`上月` 106 点、`本年` 118 点，全部落在合理密度 |
| **细粒度数据过期也不画空图** | `samples` 表按 `sample_retention_days`（默认 7 天）清理。`build()` 先查 `MIN(ts)`，若细粒度数据覆盖不到窗口起点，短窗口自动**回退 `hourly` 小时桶**（按小时给满），绝不因为采样过期画出一张空图；长窗口本来就用 `hourly`，不受影响 |
| **窗口右端不越界、v21 留白语义保留** | 当前周期窗口右端只到**当前时刻**、再向下对齐到完整桶边界，最后一个时间点必然有数据，不会重演 v16 修过的尾部空白 / 断尾；`_fill_rate_gaps()` 仍只插值中间漏采，**头部（数据库没有更早数据）/ 尾部保持 `None`**，本年 1~2 月依旧留白、不画假的水平线。所有展示数值仍统一两位小数，`rate` 桶内 `AVG`、`traffic` 桶内 `SUM` 不变 |
| **流量统计口径零改动** | `metric=traffic` 完全沿用 v12~v14 的自然周期分桶（今日 / 昨日按小时、本周 / 上周 / 本月 / 上月按天、本年按月，`SUM` 字节），只是给三个新范围补齐对应的桶：昨日 24 个小时桶、上周 7 个日桶、上月按实际天数（28~31）的日桶。顶部 4 张汇总卡、`hourly` 聚合、`db.py` / `collector.py` 累计差值铁律本版零改动；`NATURAL_RANGES` 补上 `lastweek / lastmonth`，弹出菜单标题继续显示日期标签 |

> 验证：**907 项断言全通过**（549 项 API + 87 项浏览器深度回归 + 101 项 v22 UI 专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 87 项离线容器）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v22`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

> 本次 `torrent-traffic-monitor-image-amd64-v22.tar` 的 SHA256：`957c0434c8302e0231db60fb699dc14a40b8041436f1045463f67d0337a55eb7`

### v21


| 需求 | 实现 |
|---|---|
| **下载器卡片一行改成 2 个** | `.dl-row-items` 桌面与手机端的 `grid-template-columns` 都由 `repeat(3,...)` 改成 **`repeat(2,...)`**；汇总卡仍独占第一行，其余下载器一行 2 个、放不下自动换行。卡片内部两行布局、胶囊开关、名称完整不省略等规则不变 |
| **速率折线头部不该用最早数据补成水平线** | v20 的 `_fill_rate_gaps()` 把**首尾**空桶也用最近一个真实值补齐。项目刚部署几天时，「本周 / 本月 / 本年」窗口前面那些**数据库里本来就没有更早数据**的桶，会被最早时刻的值铺成一条假的水平线。v21 把填补范围严格限定为**「两个真实采样之间」的漏采空桶**（线性插值，保证折线中间不断开）；**首个真实采样之前**、**末个真实采样之后**的桶一律保持 `None`。前端 `drawLines()` 遇到 `null` 会 `flush()` 并跳过，折线自然从第一个真实采样开始，前期留白、**不画线**，而不是拿旧数据冒充。演示数据模拟「只跑 3 天」：本月头部 6 个点 / 本年头部 10 个点为空，尾部 3 天 / 11 月正常出线；中间人为挖掉的 4 段采样仍被插值补连续 |
| **两张图例排版统一：固定刻度字号 + 自适应换行** | 旧版图例强制一行 3 个、文字过长就靠 `fitLegend()` **缩小字号**（桌面 13px、手机 10px 且会逐项缩到 7px），手机端速率图例还被砍成无色块紧凑模板。v21 统一改为：① **字号固定＝坐标轴刻度字号**（`charts.js` 的 `prep()`：画布 <480px 为 10px、否则 11px），由新增的 `renderLegend()` 按画布宽度动态设置，**绝不缩字号**；② `renderLegend()` 先把各项平铺、量出固定字号下的自然宽度，按容器宽度算出**每行能放几个**（不再写死 3），宽度不够**直接换行**；③ 各项 `flex:0 0 auto`、无 `max-width`，**内容完整、绝不打省略号**；④ `legendRows()` 仍让**第一行放余数项并居中**（留空在第一行）、其余行填满、整体居中；⑤ 项间留白统一 8px，不过宽也不过窄。**手机端「实时速率」图例直接沿用桌面端样式**（名称 + 上传色块↑ + 下载色块↓），「流量统计」手机端保留紧凑模板但同样遵守新排版规则 |
| **详情弹窗 qB / TR 图标去掉圆角方形背景** | `.dt-badge` 去掉 `background` / `border-radius:12px` / `overflow:hidden`（以及 qB 蓝、TR 红两档淡底），改成 `background:transparent; border-radius:0; overflow:visible`，只留下 SVG 里的**圆形主体图标**。`.dt-badge` 仍承担「撑满三行高 + 居中放置图标」的布局职责，单台详情与汇总详情逐台明细统一生效 |
| **统计口径保持不变** | 只改展示层：图例排版、下载器卡片列数、图标底色、速率折线空桶填补范围。`rate` 桶内仍是 `AVG(dl_rate/up_rate)`、`traffic` 桶内仍是 `SUM(dl_inc/up_inc)`，`hourly` 聚合、`db.py` 色板 / 迁移、`collector._increment()` 累计差值铁律本版零改动；两个详情接口仍只读、不写库 |

> 验证：**796 项断言全通过**（446 项 API + 87 项浏览器深度回归 + 96 项 v21 UI 专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 84 项离线容器）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v21`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

### v20

| 需求 | 实现 |
|---|---|
| **详情弹窗「正在做种 / 正在上传」统计口径不对** | 旧版用 qB 的 `state` / TR 的 `status` 字符串做**互斥归类**：`stalledUP` 才算做种、`uploading`/`forcedUP` 才算上传，与真实含义不符。v20 改成**按真实数据判定两个独立维度**（允许与其它类别重叠）：**正在做种 = 完成度 100% 且状态不是暂停**（qB `progress>=1` 且 `state ∉ {pausedUP,pausedDL,stoppedUP,stoppedDL}`；TR `percentDone>=1` / `isFinished` 且 `status!=0`），**正在上传 = 当前有上传速度**（qB `upspeed>0`、TR `rateUpload>0`），**无论种子是否完成**（边下边传也算，故与「正在下载」可重叠）。其余 6 类（正在下载 / 等待 / 校验 / 暂停上传 / 暂停下载 / 错误）仍按状态互斥归类、数值不变；汇总详情第一块按 `TORRENT_KEYS` 逐项求和，同样采用新口径。模拟数据验证：qB **16 / 7 / 3**、TR **9 / 3 / 2**、汇总 **66 / 27 / 13**（总数 / 做种 / 上传） |
| **TR 版本号只展示数字** | TR 的 `session-get.version` 真值常是 `4.0.6 (2a1c9f3d4e)` 这种「数字版本号 + 括号内带字母的构建号」。v20 在 `TransmissionClient.detail()` 新增 `_short_version()` 提取数字版本号（`4.0.6` / `3.00`），去掉括号里那段很长的构建号；qB 的 `/app/version` 本就是纯数字，不受影响。单台详情与汇总详情逐台明细统一生效 |
| **所有展示数据统一两位小数** | 旧版 `fmtBytes()` 按数值大小混用 `toFixed(0)/toFixed(1)/toFixed(2)`（大数值被抹成整数、小数位数不统一），紧凑值还直接 `Math.round()` 取整，后端 `AVG` 速率也被 `int()` 截断。v20 **凡采集 / 换算后有小数位的展示数值一律四舍五入保留两位小数**：前端 `fmtBytes / fmtRate / fmtRateCompact / fmtBytesShort`、`downsample()` 的 avg 聚合；后端 `chart.py` 的 rate 桶 `AVG` 与 hourly 字节 / 秒、`stats.py` 均值、`clients.py` 的读缓存命中 / 写缓存过载百分比与 `_short_bytes()`。**整数计数（种子数、整数 B、排队 I/O 作业数等）仍按整数显示**，不加无意义的小数 |
| **速率折线「要么太密、要么断线」+ 参考 sqing33/PTNexus** | v19 把 1h / 6h / 12h 给到 360 / 1080 / 1080 个采样点，全糊在一张图上（太密）；且桶宽恰好等于采样间隔，采集时刻稍一抖动就出现**没有任何采样的空桶**，`drawLines()` 遇到 `null` 就断开一段（断线）。调研 [sqing33/PTNexus](https://github.com/sqing33/PTNexus)：`stats/speed.go` 用 `GROUP BY strftime('%Y-%m-%d %H:%M', ...)` **按固定时间粒度对速率做 AVG 聚合**（点数由时间粒度决定、与采集频率解耦），`InfoView.vue` 用 `dataZoom` 把手机端**可见点数限制到 12 个**，缺失时间点**填 0**、折线不断。v20 对应落地：① `RATE_MAX_POINTS` 由 `1200` 收紧到 **`180`**（桌面绘图区每点 3~5px），长窗口每个桶含 2 / 12 / 24 个采样点做 `AVG`，抖动不再制造空桶；② 前端 `targetPoints('rate')` 恢复**按画布宽度自适应**（每点 ≥4px，桌面约 180 点 / 手机约 75 点），对齐 ptnexus 的可见点数思路；③ 新增 `_fill_rate_gaps()` 对仍未采到数据的桶做**线性插值填补**（比 ptnexus 填 0 更贴合真实数据，不会画出突然掉到 0 的假谷），彻底消除断线；④ 折线仍用直线连接、流量柱状图仍 12 桶、X 轴刻度仍按宽度抽稀。演示数据故意挖掉 4 段连续采样，实测各范围 `rate` 系列 **0 个 `null` 断点** |
| **统计口径保持不变** | 只改详情弹窗的**状态计数展示口径**与全站数值格式化 / 速率图分桶展示层；`rate` 桶内仍是 `AVG(dl_rate/up_rate)`、`traffic` 桶内仍是 `SUM(dl_inc/up_inc)`，`hourly` 聚合、`db.py` 色板 / 迁移、`collector._increment()` 累计差值铁律本版零改动。两个详情接口仍只读、不写库 |

> 验证：**737 项断言全通过**（425 项 API + 88 项浏览器深度回归 + 64 项 v20 UI 专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 77 项离线容器）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v20`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

### v19

| 需求 | 实现 |
|---|---|
| **实时速率折线图数据点太少** | 旧版 `chart.py` 的 `live / 1h / 6h / 12h` 固定只给 **12 个等分桶**，明明采样间隔 10 秒、库里样本充足，折线却只有 12 个顶点。v19 让 `_buckets()` 感知 `metric`：`metric=rate` 时桶宽取**采样间隔的整数倍**，把窗口内的真实采样点尽量全部作为折线顶点给足 —— 实测（`poll_interval=10s`）「实时」**30 点** /「1 小时」**360 点** /「6 小时」**1080 点** /「12 小时」**1080 点**，比旧的 12 点多 2~90 倍。**流量柱状图（`metric=traffic`）仍是 12 个等分桶**，不受影响；自然周期范围（今日 / 本周 / 本月 / 本年）的 `rate` 与 `traffic` 桶数完全一致。`RATE_MAX_POINTS=1200` 是唯一上限：屏幕绘图区通常 < 1200px，点数再多每点不足 1px、视觉无差别，同时防止把采样间隔调到 1 秒时「12 小时」炸成 43200 个点；超过上限时按采样间隔的整数倍合并相邻采样，桶宽始终是 `poll_interval` 的整数倍。v16 的「只画完整桶」逻辑、offset 平移、`window / spans` 结构全部保留 |
| **采样点给足后折线不再需要曲线拟合** | 前端 `renderChart()` 对速率图**不再降采样**（`targetPoints('rate')` 返回极大上限，`downsample()` 算出 `k=1` 后原样返回），后端给多少点就画多少点；`charts.js` 的 `drawLines()` 生产路径**默认直线连接**，只有显式传 `cfg.smooth === true` 才启用拟合，把每一个真实采样点（含瞬时峰值）忠实还原，不再用平滑把细节抹平。**X 轴刻度完全不用改**：`axisX()` 本来就按画布可用宽度自动抽稀，采样点变多时刻度数量自动保持不变，不会挤爆横坐标。v18 的单调三次 Hermite 拟合能力与 `_strokeSegment` / `_FIT_MIN_GAP` 自检钩子仍保留（可显式启用），只是不再作为默认展示 |
| **详情弹窗第二行地址被挤换行** | 旧版头部是 `[图标] [中间三行] [右侧三行]` 三列 grid，右侧列宽度由第一行较长的「实时 ↑↓ 速度」决定，反过来把中间列压窄，导致第二行「下载地址」被迫换行 —— 明明同行右侧的「限速」很短。v19 把 `dtHeadHTML()` 改成 `[图标] + 三行`，**每行是一个独立 flex 行**（`.dt-row`），左栏 `.dt-l{flex:1 1 auto}` 吃掉该行全部剩余宽度，右栏 `.dt-r{flex:0 1 auto}` 只按自身内容定宽。于是每行可用宽度只受**同一行**右侧内容影响：第二行右侧限速短，地址就占满整行、不再换行；即使把第一行右侧速率撑到超长也不影响第二行。三行仍与三行高的图标对齐，单台详情与汇总弹窗逐台明细共用同一套头部 |
| **详情弹窗第一行（关闭按钮）要冻结** | 旧版 `.modal.modal-detail{overflow:auto}`，整个弹窗一起滚，下滑内容会把含 `✕ 关闭` 的标题行顶出可视区。v19 把两个详情弹窗都改成 `display:flex;flex-direction:column;overflow:hidden`，`.modal-head` 保持 `flex:none` 留在滚动容器外**天然冻结**，只有 `.detail-body{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain}` 内部滚动。实测汇总弹窗滚动 400px 后标题行与关闭按钮位置偏差 < 1px；内容不足时弹窗仍随内容收缩并保持屏幕正中间 |
| **统计口径保持不变** | 只改 `chart.py` 的「速率图分桶宽度」与展示层；`rate` 桶内仍是 `AVG(dl_rate/up_rate)`、`traffic` 桶内仍是 `SUM(dl_inc/up_inc)`，`hourly` 聚合、`db.py` 色板 / 迁移、`collector._increment()` 累计差值铁律本版零改动。两个详情接口仍只读、不写库 |

> 验证：**696 项断言全通过**（371 项 API + 88 项浏览器深度回归 + 82 项 v19 UI 专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 72 项离线容器）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v19`。**流量统计口径零改动**，沿用 v15，详见《流量统计口径深度解析-v15.md》。

### v18

| 需求 | 实现 |
|---|---|
| **详情弹窗放到屏幕正中间，上下空白点击被忽略** | 给两个详情弹窗的遮罩单独加 `.detail-mask{align-items:safe center;justify-content:center;overflow-y:auto}`，不受设置弹窗「顶部对齐」规则影响；水平 / 垂直中心偏差实测 < 2px，内容超高时遮罩自身可滚，不会截断。移除「点击遮罩就关闭」的监听：**点击弹窗外的上下空白一律忽略**，只有右上角 `✕ 关闭` 胶囊或 Esc 才关闭，避免误触回到主界面。汇总弹窗同样居中、同样忽略遮罩点击 |
| **下载器卡片布局重构：标识右下、速率靠左、开关更短、名称完整** | 卡片改为 `.dl-top`（状态点 + 名称 + 右上角胶囊开关）/ `.dl-bottom`（实时 ↑↓ 速率靠左 + qB / TR 标识贴右下角）两行；汇总卡的「N/M 在线」标签也移到右下角。胶囊开关由 30px 缩到 **24px**（手机 20px），给名称腾出空间。新增 `fitChipNames()`：渲染后逐卡实测名称 `scrollWidth`，单行放不下就**等比缩小字号**（下限 9px），仍放不下则**换行**，CSS 侧同步去掉 `text-overflow:ellipsis` —— **长名称 100% 完整可见、绝不省略** |
| **qB 的 IO 改成数字并按三级阈值着色** | 参照 qB WebUI 状态栏磁盘缓存图标里的 `server_state.queued_io_jobs`（排队 I/O 作业数）：胶囊显示 `IO 5` / `IO 45` / `IO 150` 这样的**整数，不再是读缓存命中率百分比**；按 libtorrent 默认 `aio_threads=10` 的经验阈值分级 **< 20 健康（绿）/ 20~99 繁忙（黄）/ ≥ 100 过载（红）**，阈值常量 `IO_WARN=20` / `IO_BAD=100` 集中在 `clients.py` 便于按磁盘性能调整。`io_full` 仍把读缓存命中 / 写缓存过载 / 排队作业 / 缓冲区 / 平均排队时长放进悬停提示；极老版本无该字段时退到「平均排队 ms」，完全没有磁盘字段时才退到本次会话 I/O 数据量。三级颜色互不相同，深浅主题都可读 |
| **汇总卡片点击弹出「全部下载器汇总详情」** | 新增 `GET /api/downloaders/summary/detail`：并发抓取全部下载器详情（复用采集器登录态、3 秒结果缓存、单台失败只标记该台不影响其他台），**按配置顺序**返回逐台明细，并给出**全部下载器求和**的种子状态统计与汇总实时速率。弹窗宽 940px：标题区展示汇总 ↑↓ 速度与「共 N 台 / M 在线」连接情况；第一块 = 汇总的 10 项状态统计（种子总数、种子总大小、做种 / 上传 / 下载 / 等待、校验 / 暂停上传 / 暂停下载 / 错误）；第二块 = 按 `sort_order` 逐台列出，每台头部三列 + 10 项统计**与单台详情完全同款**（qB 明细里同样带三级色 IO 胶囊） |
| **桌面端设置页拉宽、配置表不再省略** | 桌面（>560px）设置弹窗宽度由 1000px 提到 **`min(1280px, 96vw)`**；配置表改 `table-layout:auto`、列宽随内容自适应，移除单元格 `text-overflow:ellipsis` 与固定宽度，**所有已增加下载器的名称 / 地址 / 版本 / 颜色 / 操作按钮在一行完整显示**，无隐藏、无横向滚动条。手机端仍是原来的卡片式布局，不受影响 |
| **实时速率折线默认拟合，且贴合实际数据** | 图表引擎把原来的「点数 ≤16 才用 Catmull-Rom、点多退化直线」换成 **单调三次 Hermite 插值（Fritsch–Carlson）**：曲线**精确穿过每一个真实采样点**，控制点被夹在相邻两点之间，**段内严格单调、不会过冲画出负值或假峰值**；只有相邻点像素间距 < `FIT_MIN_GAP=5`（数据点真正过密）时才退化为直线。自检钩子 `_strokeSegment` / `_FIT_MIN_GAP` 供自动化验证「过点 + 不过冲」，`live / 1h / 6h / 12h / 24h / week` 全部实测走拟合曲线 |
| **统计口径保持不变** | 两个详情接口只读、不写库、不改 `fetch()` 的 rid 增量状态与 `collector._increment()`；`chart.py` / `db.py` / `stats.py` 流量统计逻辑本版零改动。新增弹窗、卡片布局、配色分级、拟合曲线均属展示层 |

> 验证：**631 项断言全通过**（331 项 API + 88 项浏览器深度回归 + 62 项 v18 UI 专项 + 83 项深浅主题 / 390·360·320px 手机端专项 + 67 项离线容器）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v18`。**本次未改动任何流量计算逻辑**，统计口径沿用 v15，详见《流量统计口径深度解析-v15.md》。

### v17

| 需求 | 实现 |
|---|---|
| **下载器卡片不再用高亮表示选中，右上角加胶囊开关** | 删除 `.dl-chip.sel` 整套高亮（渐变底 / accent 描边 / 顶部渐隐强调线 / 外发光），卡片外观恒定一致；**每张卡片右上角新增 iOS 风格胶囊开关**（999px 轨道 + 滑块，圆角与全站胶囊按钮一致），`on` = 该下载器（或汇总线）加入两张图表，`off` = 移出，点击即切换并记忆到 localStorage。汇总卡同样带开关；点击开关不会误触发详情弹窗 |
| **单击下载器卡片弹出详情窗口** | 新增按需只读接口 `GET /api/downloaders/<id>/detail`：只在点击时向下载器发请求、复用采集器已建立的登录态、3 秒结果缓存避免连点打爆 WebUI。弹窗头部三列：左侧 **qB / TR 品牌 SVG 图标，高度＝三行高**；中间三行＝**下载器名称 / 地址 / 版本**，qB 在版本后追加一枚 **IO 小胶囊**（读缓存命中率、写缓存过载、排队 I/O、缓冲区、平均排队时长，悬停看全文；无磁盘 I/O 字段的老版本退到本次会话 I/O 数据量），TR 只有版本胶囊；右侧三行＝**实时 ↑↓ 速度 / 上传下载限速（不限速显示 ∞ 无限图标）/ 剩余空间**。下半部分三行：第一行 **种子总数、种子总大小**，第二行 **正在做种 / 正在上传 / 正在下载 / 等待状态**，第三行 **校验状态 / 暂停上传 / 暂停下载 / 错误状态**。qB 按 `torrents/info` 的 `state`、TR 按 `torrent-get` 的 `status + error + percentDone + peersGettingFromUs` 映射到这 8 类；TR 限速单位 KiB/s 已换算为 B/s。弹窗可见时每 5 秒静默刷新实时速率，右上角按钮 / 点遮罩 / Esc 均可关闭 |
| **图例第一行不满 3 个时居中** | 不再用不可见占位把余项顶到第一行一侧。改为 `legendRows()` **按行分组**：第一行放 `n mod 3` 个余数项，由 `justify-content:center` **居中对齐**，其后每行恰好 3 个等宽。桌面端 `.lg-row{display:contents}`，子项仍直接参与 `.legend` 的自然换行居中 —— **展示内容一字不变**（名称 / 色块 / 双向箭头 / 上传下载字样 / 完整数值全在），只同步排版规则 |
| **图例内容必须完整，不能省略号，过长只缩字号** | 移除手机端 `.lg-nm/.lg-name` 的 `overflow:hidden;text-overflow:ellipsis`，项内文字一律改用 `em` 相对单位；新增 `fitLegend()` 在每次渲染后逐项实测 `scrollWidth / clientWidth`，**内容超出时等比缩小该整项字号**（下限 7px），极端长名称缩到下限仍放不下时**宁可换行也绝不裁剪**。桌面端给图例项加「最多占 1/3 行宽」上限，让同一套规则在桌面同样生效（正常内容宽度不受影响）。桌面、390 / 360 / 320px 手机逐一实测：无省略号、无溢出、文字 100% 完整 |
| **统计口径保持不变** | 详情接口只读、不写库、不改 `fetch()` 的 rid 增量状态与 `collector._increment()`；`chart.py` / `db.py` 流量统计逻辑本版零改动。新增弹窗、开关、图例排版均属展示层 |

> 验证：**302 项 API + 88 项浏览器 + 82 项 v17 专项 + 62 项离线容器 = 534 项断言全通过**（另有 26 项色板 / 迁移单元自检）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v17`。**本次未改动任何流量计算逻辑**，统计口径沿用 v15，详见《流量统计口径深度解析-v15.md》。

### v16

| 问题 | 修法 |
|---|---|
| **「实时」范围最后一个时间点偶尔空白**（实时速率折线断尾、流量统计末柱为空） | 根因是 `chart.py` 的 `live / 1h / 6h / 12h` 把窗口右端设成 `end + step`，等于把 **`[end, end+step)` 这个「当前正在进行、可能一次采样都还没有」的桶**也画进图表；刷新相位一跨过桶边界，最后一个点就是 `None`（折线断尾）/ `0`（空柱）。**v16 改成只画已走完的完整桶**：窗口右端收到 `end`，最后一个桶变为 `[end-step, end)`，窗口整体左移一个桶、桶数与柱宽都不变。由于 `step ≥ 采样间隔`，这个桶必然含采样点 —— 这也是 Prometheus 等时序图的标准做法。速率折线与流量柱状图都调同一个 `build('live', …)`，所以一起修好 |
| **图例最后一行不足 3 个，头重脚轻** | 新增 `legendPad(n)`：在真实图例项**前面**插入 `(3 − n mod 3) mod 3` 个不可见占位，把空白顶到**第一行开头**，**最后一行恒为 3 个下载器**。占位在桌面端 `display:none`（桌面图例本就是自然居中换行，不需要占位）；手机端 `visibility:hidden` 但仍照常占 1/3 宽。两张卡片图例同步处理，1~5 个下载器逐一实测 |
| **同为上传 / 同为下载的颜色仍太接近、容易混淆** | 旧板两个方向都是 `i×36°` 连续色相，用户实际的前 5 台只拿到 0/36/72/108/144°，全挤在半圈里。**v16 用 OKLab 感知色差 farthest-point 数值寻优**出上传色相序列 `HUE_SEQ=[174,294,240,60,354,120,216,273,45,324]`，下载色为同序列整体旋转 `DN_PHASE=30°`（相位同样由寻优确定，让两组在色环上完全错开、不互相撞色）。判据不是「同方向组内」而是更本质的 **「前 5 台 × 2 方向共 10 条线整体最小两两 ΔE 最大」**，深浅两套主题联合验证。相对旧板：同为上传 **+221%（深色）/ +218%（浅色）**、同为下载 **+39% / +39%**、10 线整体 **+73% / +69%**、全 20 线整体 **+60%**，且更远离汇总线色。**升级时对已部署库做一次性、幂等的旧默认色迁移**（`app_settings.palette_v16` 打标记）：只替换仍完整命中旧系统配对的下载器，**手动改过的颜色原样保留**，历史流量数据完全不动 |
| **下载器设置页「曲线颜色」顺序和新增表单不一致** | 表格行由 `色块 上传　色块 下载` 改成 **`上传 色块，下载 色块`**（文字在前、调色板在后），与下方「新增下载器」表单颜色行顺序完全一致；仍不显示 `#RRGGBB` 代码，完整色值放在 `title` 里悬停可查 |
| **手机横屏时不要自动转成横屏** | `manifest.webmanifest` 的 `orientation` 由 `any` 改为 **`portrait`**，PWA 以竖屏启动、不随设备旋转自动横屏；已安装的 standalone 模式里再静默调用 `screen.orientation.lock('portrait')` 兜底，普通浏览器标签页不支持锁方向时静默失败，不影响任何功能 |

> 验证：**247 项 API + 98 项浏览器 + 88 项 v16 专项 + 62 项离线容器 = 495 项断言全通过**（另有 26 项色板 / 迁移单元自检）；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v16`。**本次未改动任何流量计算逻辑**，统计口径沿用 v15，详见《流量统计口径深度解析-v15.md》。

### v15


| 问题 | 修法 |
|---|---|
| **「采集中 / 设置」按钮和设置页内按钮不一样高；下载器设置页颜色行太啰嗦** | 「采集中」与「设置」两枚胶囊高度改为 **`var(--btn-h)=34px`**，与设置页一级 / 二级 / 三级按钮**完全一致**（旧版靠 padding 撑出约 30px，矮 4px）；该变量提到 `:root`，手机端胶囊也锁 34px，只缩字号与水平内边距，全站改一处即同步。下载器设置页「曲线颜色」列与表单颜色行改成 **`色块 上传　色块 下载`**，**删掉 `#RRGGBB` 代码文本**（完整色值移到 `title`，悬停可查）；表格腾出的列宽重新分配（颜色 23%→17%、顺序 9%→13%、操作 26%→28%），**「顺序」列的 ↑↓ 与「操作」列的 编辑/停用/测试/删除 统一固定 40px 宽**，两列按钮同宽同高、整表仍一行排下不横向滚动 |
| **「实时速率」卡片图例要和「流量统计」一致** | 手机端速率图例从 **5 列网格**改成与流量图例**完全同款**：`display:flex + flex-wrap + justify-content:center`，**一行 3 个下载器、末行不足 3 个居中**；两张图例的容器字号（10px）、名称字号（9px / 600 字重）、箭头字号（11px）、间距、行高、≤360px 降档规则**逐项对齐**。桌面端两图例本就共用 `.legend`（13px），另外把速率图例的 `.lg-nm` 字重统一为 600，字号 / 字重 / 颜色完全一致 |
| **⚠️ 严重：统计的每个下载器数据量比 PT Nexus 偏多**（今日上传 23 GB vs 20.62 GB、下载 203 GB vs 190.31 GB，偏高 **+11.54% / +6.67%**） | 认真核对了 [sqing33/PTNexus](https://github.com/sqing33/PTNexus) `go` 分支源码：两个项目读的是**完全相同的数据源**（qB `sync/maindata → alltime_dl/ul`、TR `session-stats → cumulative-stats`），**前端都是 1024 进制**，所以既不是数据源差异也不是 GB/GiB 换算。差异出在**增量算法与异常处理**：PT Nexus 只存累计快照、查询时按桶取 `MAX(累计)−MIN(累计)`、异常直接跳过**不猜**；本项目旧版在累计计数器暂时取不到（qB `maindata` 增量响应会省略未变化的 `alltime_*` 键）、计数器回退、首次采集时，会退化成 **「瞬时速率 × 采样间隔」并把估算值累加进流量**，还会把 `last_*_total` 基线写成 `NULL` 造成连锁退化。**这就是系统性偏高的根因**：速率是瞬时派生量，用它反推一段区间的字节数等价于黎曼和近似，PT 上传是脉冲流、采样点常落在波峰，偏差尤大 —— 这正好解释「上传偏差(11.54%) 明显大于下载(6.67%)」；若是进制差异，两个方向必然是同一个固定 7.37%。**v15 彻底移除速率估算**：流量只能来自累计计数器单调差值，任何异常轮次一律记 0 并保留基线（计数器恢复后差值自愈补回）；客户端缓存累计值应对增量响应字段缺席；数据库用 `COALESCE` 保证基线永不被 NULL 冲掉；`extra.counter_source / counter_event` 便于审计。保留本项目原本更优的「连续差值分摊到小时桶」（比 PT Nexus 分桶 `MAX−MIN` 不丢边界）。**详见随包交付的《流量统计口径深度解析-v15.md》**（含源码引用、误差来源逐条分析、量化复现、7 条最优统计原则、自行核对清单） |

> **注意**：v15 只改变此后的采集，**不会回溯修正数据库里已写入的估算流量**。升级后新数据会变小、向累计计数器真实差值靠拢，这是变准了；若要从零开始干净统计，备份后删除 `data/traffic.db` 重采（会丢历史）。另外 PT Nexus 自身也会因分桶 `MAX−MIN` 丢桶边界、时间窗口依赖容器 `TZ` 而**略偏小**，它不是标准答案 —— 权威基准是「下载器累计计数器在两个时刻的差值」，核对方法见材料 §7。

> 验证：**209 项 API + 57 项浏览器 + 80 项 v15 专项 + 56 项离线容器 = 402 项断言全通过**；离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。SW 缓存升到 `ttm-shell-v15`。

### v14

> 下面保留的是 v14 当时的记录；其中「手机端速率图例 5 列」「顶栏胶囊 30px」等条目均已在 **v15 调整**，当前行为以 v34 章节为准。

| 问题 | 修法 |
|---|---|
| **PWA 桌面图标有点丑，要直接沿用 Web 左上角那个** | 不再用 PIL 重画箭头（旧版是 DejaVu Bold 的粗实心三角，和页面里细线弧形箭头不是一个字形）。改为**用 Chromium 真实渲染页面上的 `.logo` DOM**：同一份线上 CSS（`#38BDF8 → #6366F1` 135° 渐变、29% 圆角、700 字重、白色 `⇅`、同字体栈），等比放大到 **2048×2048 超采样**截图后 LANCZOS 缩到 192 / 512，边缘极清晰；`maskable` 用同款渐变铺满、符号收进 80% 安全区，`apple-touch-icon` 合成到不透明深色底，`favicon-32` 同源。实测导出的 512 图标与页面 logo 的白色符号 **IoU 0.985**、渐变平均色差 **0.62**，可认为是同一张图。SW 缓存升到 `ttm-shell-v14` |
| **设置页切换时上下居中、点外面会误关、关闭按钮丑、菜单高矮不齐、标题被上滑顶走** | 弹窗改为**固定高度（86vh / 760px）+ 遮罩顶部对齐**，切换分页时顶端与高度完全不动、右栏滚回顶部，内容短时下方留空；`head`（「设置」行）与 `settings-nav`（分页行）留在滚动容器外**天然冻结**，只有右侧 `settings-pages` 滚动（`overscroll-behavior:contain`），上滑手势顶不走标题。**点击弹窗范围外（遮罩）一律忽略**，不再误关回主界面，关闭只能用右上角按钮；该按钮改成 `✕ 关闭` 的标准胶囊（与全站 `.btn` 同款圆角 / 描边 / 淡底）。**一级导航 / 二级选项与操作 / 三级表格小按钮统一 34px 高**，宽度不再被 flex 拉伸成固定值、由按钮名称长度自适应；未选中的一级菜单也补上与其它按钮一致的淡彩描边 |
| **「本周」时间点数不对：应按当天是本周第几天给几个点** | `chart.py` 的 `week` 分支从「本周一~周日固定 7 个日桶」改为 **`n = weekday() + 1`（周一 1 … 周日 7），本周一 ~ 今天**，与「本月 1 号~今天」「本年 1 月~当月」完全同一套自然周期语义。窗口桶数在 offset 平移前后仍恒定，柱宽 / 刻度密度不跳变。顶部汇总卡的「本周」历史周期下拉（往前 26 周）不受影响 |
| **流量统计弹出菜单标题：非自然周期范围应是时间段** | 后端 `chart.build()` 新增每桶 `spans`（`[起始 Unix 秒, 结束 Unix 秒]`），前端 `downsample()` 合并桶时同步合并区间。`实时 / 1 / 6 / 12 小时 / 今日` 点击柱子弹出的菜单标题改成**该桶覆盖的时间段**（如 `11-07 04:00 ~ 05:00`、`11-07 22:35:00 ~ 22:35:25`，不足 1 分钟的桶带秒、跨天右端带日期）；`本周 / 本月 / 本年` 保持原来的日期 / 月份标签（它们一个点本身就是完整日 / 月）。「实时速率」卡片的弹出菜单保持原样不变 |
| **两张卡片图例留白太多、字太小** | **桌面端**下载器之间的横向留白 `16px → 5px`（约 1/3）、图例字号 `11px → 13px`，色块与箭头同步放大；**手机端**速率图例 `4px → 1px`、流量图例 `6px → 2px`（均为 1/3），数值 / 箭头字号 `8px → 10px`、名称 `8px → 9px`（≤360px 降一档）。手机端紧凑值去掉小数（`44.5 GB → 45G`）给名称腾空间，实测 390 / 360px 下 `MOCK-QB-01` 这类 10 字符名称**全部完整显示**，`一行 5 个 / 3 个`、末行居中、无横向滚动均不变；完整数值仍在桌面图例与 `title` 里 |

> 验证：188 项 API + 50 项浏览器 + 74 项 v14 专项断言全通过；v14 离线镜像 `docker load -i` 起容器往返正常，镜像内 17 个源码文件与 5 个图标哈希一致。

### v13

> 下面保留的是 v13 当时的记录；其中「本周 7 个完整自然日」「PWA 图标由脚本重画」「手机端图例 8px」等条目均已在 **v14 调整**，当前行为以 v34 章节为准。

| 问题 | 修法 |
|---|---|
| **「24 小时」改成「今日」，要自然周期语义** | 范围下拉里的 `24 小时` 改为 **`今日`**：不再是「最近 24 小时」这种会跨两天的滚动窗口，而是**今天 0 点 ~ 当前小时**，按小时分桶（点数 1~24 随当前时刻递增），数据取自 `hourly` 表，与顶部「今日」汇总卡完全同源、口径一致；`本周 / 本月 / 本年` 的自然周期语义不变。页面与下拉里原来的 **`本日` 统一改为 `今日`**（顶部第一张卡标题、下拉菜单标题、`/api/periods` 的周期名）。内部 key 仍保留 `24h`，已保存的浏览器状态与 API 调用都兼容 |
| **项目名与 PWA 图标统一** | 界面左上角、页面标题、PWA 桌面名称（`manifest` 与 iOS `apple-mobile-web-app-title`）统一改为 **`下载器流量统计`**。全套 PWA 图标（192 / 512 / maskable / apple-touch / favicon）重画成**与 Web 左上角 logo 完全一致**的图案：`#38BDF8 → #6366F1` 蓝紫渐变圆角 + 白色 `⇅`；maskable 版把图形收进安全区。目录名、镜像 tag、容器名不变 |
| **按钮样式要更整体** | 全站按钮（主要操作 / 下拉触发器 / 采集档位 chip / 设置导航 / 主题选择 / 菜单快捷项 / 回到最新）统一为**和右上角「设置」一样的胶囊圆角（999px）+ 淡彩色描边**；`.btn.primary` 等语义强调保留。右上角「设置」按钮**和左边「采集中」一样做彩色描边 + 同浓度淡彩底**（采集中＝状态绿，设置＝accent 蓝紫），两枚胶囊并排更成一对 |
| **手机端两张图的图例要更简洁**（仅移动端，**桌面端不变**） | 「流量统计」图例改成 **`下载器名称 ↑ 上传数据量 ↓ 下载数据量` 全部同一行**：删掉颜色图标和「上传 / 下载」字样，用**箭头的上下指向 + 线条色 + 数值色**表意，数值切紧凑格式（`847 GB → 847G`）省空间；**一行仍放 3 个下载器**，字体按屏宽调小，**第二行不足 3 个时居中**，不再右侧留白。「实时速率」图例同样**删掉颜色图标**，只留带色 `↑ / ↓`，**一行放 5 个下载器**。两张图图例统一压到 8px，名称由 flex 自动占满剩余宽度，390 / 360px 下 10 字符名称也能完整显示；320 / 360px 再收紧间距与字距，极窄屏才省略（完整名称与数值放在 `title` 里） |

> Service Worker 缓存版本同步升到 `ttm-shell-v13`；安装过旧版 PWA 的手机下次打开会自动换掉旧缓存，桌面图标也会一起更新。

### v12

> 其中「24 小时仍是 12 个等分桶」一条已在 **v13 改成「今日」自然日**，下面保留的是当时的记录，当前行为以 v34 章节为准。

| 问题 | 修法 |
|---|---|
| **还是想保留「本月 / 本年」的自然周期语义** | 撤销 v11 为满足「固定 12 个时间点」而引入的滚动窗口：**「本月」从「最近 12 天」改回「本月 1 号~今天」**（按天，点数随日期递增 1~31），**「本年」从「最近 12 个自然月（跨年）」改回「今年 1 月~当月」**（按月，点数随月份递增 1~12）。窗口不再跨月 / 跨年，与顶部汇总卡「本月 / 本年」的统计口径完全一致。「本周」仍是 7 个完整自然日（本周一~周日），`实时 / 1 / 6 / 12 / 24 小时` 仍是 12 个等分桶。横向拖动时窗口桶数恒定，柱宽与刻度密度不随日期跳变 |
| **镜像文件名要带版本号，方便保存各版本** | 镜像包改名 **`torrent-traffic-monitor-image-amd64-v12.tar`**，自包含源码包改名 **`torrent-traffic-monitor-v12.zip`**（内含同版本、同 SHA256 的 `.tar`）。版本号 `v12` 与「本次更新（v12）」章节号、SW 缓存 `ttm-shell-v12` 三者一致；以后每次更新 `v20 / v21 …` 递增，文件名都不同，历次镜像可并存归档、不会互相覆盖。**导入后的 Docker 镜像 tag 仍是固定的 `torrent-traffic-monitor:1.0.0`**，`docker-compose.offline.yml` 不用随版本改，升级时只用新版本 `.tar` 重新 `docker load -i` 即可 |

> Service Worker 缓存版本同步升到 `ttm-shell-v12`；安装过旧版 PWA 的手机下次打开会自动换掉旧缓存。

### v11

> 其中「图表时间点」一条已在 **v12 撤销**（恢复自然周期语义），下面保留的是当时的记录，当前行为以 v34 章节为准。

| 问题 | 修法 |
|---|---|
| **汇总卡下拉历史周期范围要加大** | 「本周」从往前 6 周扩到 **往前 26 周（共 27 项：本周 / 上周 / … / 26 周前）**，「本月」从往前 6 个月扩到 **往前 12 个月（共 13 项：本月 / 上月 / … / 12 个月前）**；今日 31 项、本年 6 项不变。后端 `stats.PERIOD_COUNTS` 一处控制、前端动态渲染；菜单 `max-height:340px` 可滚动，不会撑爆页面，选中后标题 / 日期 / 数值同步并照旧持久化 |
| **「流量统计」图例要带箭头** | 改成 `下载器名称 [上传色块] ↑ 上传 161 GB [下载色块] ↓ 下载 52.2 GB`（箭头与色块同色），删掉说明文字。**手机端图例改成一行 3 个下载器的 3 列网格**，每项内部纵向排「名称 / ↑上传量 / ↓下载量」，390 / 360 / 320px 都不横向溢出 |
| **图表时间点数量不固定、柱子太密** | 后端把时间点数固定下来：**「本周」7 个日桶**，从本周一排到**本周最后一天（周日）**，最后一个时间点就是周日；**其余范围一律 12 个桶**（实时 / 1 / 6 / 12 / 24 小时 / 本月 / 本年），都以最新时刻/周期为终点往前排。底层数据不足时前面的桶自动补零，不凭空造数据；前端不再二次抽稀，桌面 12 个时间点全部有刻度，手机端 X 轴标签自动抽稀避免重叠。窗口桶数恒定，拖动平移时柱宽与刻度密度不会随日期变化 |
| **「区间数据」小卡片要精简** | 删掉「时间点」一项，只保留 **区间上传 / 区间下载 / 合计** 三个数值；排版明确左对齐，桌面项间距 30px、手机 16px |


### v10

| 问题 | 修法 |
|---|---|
| **「设置」按钮又太小了**，和左边「采集中」不协调 | 让设置按钮**直接复用「采集中」的 `.pill` 盒子模型**：等宽 76px、等高 30px，同为 12px 字号 / 18px 行高 / 20px 圆角 / `5px 10px` 内边距 / 1px 边框，并补上**同浓度的淡色底**（v9 是透明底，视觉上显小）。顺带修掉 `font:inherit` 简写把按钮字号重置回 14px 的问题，改为只继承字体族。手机端同步缩到 66×26px，两枚胶囊仍完全一致 |
| **「实时速率」图例要按「名称 色块↑ 色块↓」展示** | 删掉说明文字，每个下载器一项：`名称 [上传色块]↑ [下载色块]↓`，色块与箭头都用对应线条色；只选一个方向时只显示对应一侧。悬停 / 点击弹出的菜单改成**一个下载器一行**：`名称:` 黑字 + `↑ 上传速率`（上传线色）+ `↓ 下载速率`（下载线色），例如 `MOCK-QB-01: ↑ 13.5 MB/s ↓ 2.22 MB/s` |
| **「流量统计」图例要带数值，菜单要列全** | 删掉说明文字，图例改成 `名称 [上传色块] 上传 136 GB [下载色块] 下载 41.2 GB`（数值＝该下载器在当前区间的累加总量）；悬停 / 点击菜单**按选中顺序完整列出所有下载器**，不再过滤 0 值，无流量也显示 `0 B`，末尾保留合计行 |

两张图的弹出菜单统一为**浅色卡片**（名称要求黑字，深色主题下也用白底），彩色数值用对应线条色并轻微压暗保证可读。图表**点击 / 手机点按也能唤出菜单**（拖动结束后浏览器合成的 click 会被忽略，不会误弹）。


### v9

| 问题 | 修法 |
|---|---|
| **右上角「设置」按钮太大**，和「采集中」图标放一起不协调 | 去掉实心主按钮样式，改成与「采集中」**同高（30px）、同字号（12px）、同 20px 圆角**的柔和描边胶囊：透明底 + 细边框，hover 才淡淡高亮；手机端同步缩到 11px / 26px，两个胶囊并排尺寸一致、不再一大一小 |
| **下载器设置页桌面端最后一列 4 个操作按钮竖排** | 操作列改 `flex-wrap:nowrap` + 按钮收紧，强制一行；表格改 `table-layout:fixed` 固定列宽，给操作列留足 206px，其余列过长用省略号（地址列带 `title` 可看完整 URL），**整表无横向滚动条**，颜色列两个色值仍完整显示。手机端仍是一设备一行的卡片式，4 个按钮同样一行 |
| **「实时速率」图例太复杂**（选 5 个下载器 + 汇总会有 12 条） | 与「流量统计」同款：**一个下载器只占一项**，前面小方块左半＝该下载器的上传线色、右半＝下载线色，配一条「左半 ↑ 上传 · 右半 ↓ 下载」说明。选满 6 项时从 **12 条降到 7 条**；只选上传 / 只选下载时说明自动变化、色块退化为单色 |


### v8

| 问题 | 修法 |
|---|---|
| 手机端**左侧两张汇总卡的下拉菜单伸出屏幕左边**，最左侧选项看不全 | 菜单按列决定展开方向：2 列布局下**左列从左向右展开、右列右对齐向左展开**；再加一层通用**视口边界夹取** —— 展开时实测 `getBoundingClientRect()`，越界就用 `translateX` 拉回。所有下拉、任意屏宽（320 / 360 / 390px 均已验证）、以及定时刷新重建菜单后都生效 |
| **下载器卡片的高亮太生硬** | 删掉实心左侧色条与双重描边，改为**柔和渐变底 + accent 半透明细描边 + 顶部 2px 渐隐高亮线 + 轻微外发光**，深浅主题都更克制；汇总卡选中态同款处理，仍不显示「已选中」文字 |
| **拖动图表时坐标轴跟着一起跑** | 画布拆成**固定坐标轴层**（Y 刻度带、水平网格、X 时间标签，`pointer-events:none`，不参与 transform）与**可平移数据层**（曲线 / 柱 / 悬停，仍用 `translate3d` GPU 跟手）。拖动时只有数据在固定视口内滑动，刻度与标签始终钉在原地；轴层左侧刻度带用面板底色铺底，挡住曲线平移时溢出的像素。顺带把绘图区右侧留白加大到容得下末尾时间标签，X 轴首尾标签不再被画布边缘裁掉 |




## 二、MoviePilot V3 插件版（v1.0.32）


> 由独立 Docker 版 v50 迁移而来；认证 / 边界安全交由 MoviePilot 宿主负责，下载器直接读取宿主已接入配置，设置统一落入 MoviePilot 原生配置面板。

### v1.0.32
修复「合计」在微信里仍比表头「下载器」偏左的问题：微信把表头居中、数据行左对齐，实测偏左约 2 个 NBSP 宽；合计行首列在居中基础上再右偏 2 格，视觉对齐表头。其余格式与功能不变。

### v1.0.31
修复 v1.0.30 的「合计」居中在微信里失效：居中填充改用不换行空格 NBSP（U+00A0），避免微信 Markdown 表格 trim 普通空格。

### v1.0.30
通知表格「合计」行首列的「合计」二字改为居中对齐，数值列与其他行不变。

### v1.0.29
删除标题正下方与标题等长的分隔横线，改为标题后直接是无表头明细表；段间 24 格横线保留。

### v1.0.28
通知正文调整：段间分隔横线由 12 格改为 24 格；删除表头行及其上方空行；上传由 🔴 改 🟢 并紧跟 ↑，下载由 🟢 改 🔴 并紧跟 ↓。

### v1.0.6
通知表格改用 ASCII 边框（+ - |）画线，不再依赖制表符；上传 / 下载数值前 emoji 换成主体色不同的 🔴 / 🟢。

### v1.0.5
首次安装默认开启定期通知（每天 22:40，默认通知今日 / 昨日 / 本周 / 本月四个范围）；通知正文改为「下载器 / 上传 / 下载」三列纯文本表格。

### v1.0.4
修复单台下载器卡片右上角开关失效（图表改按每台开关显隐）；桌面绘图区填满视口并下调下载器小卡高度；设置页重排为固定五行结构。

### v1.0.3
采集拆成两条节奏：流量统计按「采样间隔」（默认 1 分钟）记账，下载器实时速率 / 在线状态按固定 5 秒刷新内存态；汇总卡片右上角改为在线情况；手机端纵坐标固定 5 档刻度。

### v1.0.2
删除实时速率卡片、实时速率采样设置与相关代码，采集精简为单线程流量统计；下载器卡片恢复独立汇总卡片 + 自适应网格；设置页改为单页平铺无提示，曲线颜色由系统自动分配并提供一键重分配。

---

