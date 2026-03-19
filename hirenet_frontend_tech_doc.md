# HireNet 前端界面技术实现文档

**Human-Agent Labor Network**
版本 v1.0 · 2026-03-18
技术栈：HTML5 · CSS3 · Vanilla JS · Flask

---

## 1. 文档概述

本文档详细描述 HireNet 前端界面的完整技术实现方案，包括设计系统、页面结构、组件规范、交互逻辑及与后端 API 的对接方式。本文档面向需要进一步调整和定制前端界面的开发者。

### 1.1 技术栈

| 技术 | 用途 | 说明 |
|------|------|------|
| HTML5 | 页面结构 | 单文件模板，Flask render_template 渲染 |
| CSS3 | 样式与动画 | CSS 变量 + Flexbox + Grid + keyframes |
| Vanilla JS | 交互逻辑 | 无框架，原生 DOM 操作 + fetch API |
| Press Start 2P | 像素风字体 | Google Fonts，用于标题和标签 |
| DM Sans | 正文字体 | Google Fonts，用于正文和描述 |
| Flask Jinja2 | 服务端渲染 | templates/ 目录，render_template() |

### 1.2 文件结构

```
hirenet/
├── app.py                    # Flask 主应用
├── templates/
│   ├── index.html            # 角色选择页
│   ├── employer.html         # 雇主端控制台
│   └── jobseeker.html        # 求职者端页面
└── static/                   # （可选）静态资源目录
```

---

## 2. 设计系统

### 2.1 视觉风格

设计灵感来自星露谷物语（Stardew Valley）的明媚像素风，结合现代 SaaS Dashboard 的信息密度。核心视觉特征：

- 蓝天白云动态背景（CSS animation + 分层渐变）
- 像素方形阴影代替圆角投影（`box-shadow: Npx Npx 0`）
- Press Start 2P 字体只用于标签/标题，正文用 DM Sans 保证可读性
- 明亮蓝色系主色调，绿色/琥珀/珊瑚作语义色
- 像素云朵、小鸟、草地花朵作为氛围装饰元素

### 2.2 CSS 变量系统

所有颜色通过 CSS 变量定义在 `:root`，统一管理。修改颜色只需改变量值：

| 变量名 | 默认值 | 用途 |
|--------|--------|------|
| `--pixel` | `#2b7fc1` | 主色：按钮、边框高亮、标题 |
| `--pixel2` | `#4a9fd4` | 主色浅：hover 状态 |
| `--green` | `#3da35d` | 成功/完成/推荐状态 |
| `--amber` | `#d4860a` | 警告/混合方案/Hybrid 状态 |
| `--coral` | `#d44f3e` | 需要人工/错误状态 |
| `--teal` | `#1a8c8c` | Agent 标签、技能标签 |
| `--text` | `#1a3a4a` | 主要文字颜色 |
| `--muted` | `#5a7a8a` | 次要文字、占位文字 |
| `--surface` | `rgba(255,255,255,.92)` | 面板背景（半透明） |
| `--surf2` | `#e8f4fd` | 次级背景、输入框背景 |
| `--border` | `#a8d4e8` | 边框颜色（深） |
| `--bord2` | `#c5e4f0` | 边框颜色（浅） |
| `--accent` | `#f5a623` | 强调色（暂未大量使用） |
| `--sh` | `3px 3px 0 rgba(0,80,120,.15)` | 标准像素阴影 |
| `--sh2` | `4px 4px 0 rgba(0,80,120,.2)` | 悬停像素阴影 |
| `--font-px` | `'Press Start 2P', monospace` | 像素字体 |
| `--font-ui` | `'DM Sans', sans-serif` | 正文字体 |

### 2.3 字体规范

| 场景 | 字体 | 字号 | 颜色 |
|------|------|------|------|
| 页面大标题（HIRE NET） | Press Start 2P | 11–12px | `var(--pixel)` |
| 面板标题（TASK INPUT） | Press Start 2P | 8px | `var(--pixel)` |
| Agent 标签 | Press Start 2P | 8–9px | `var(--teal)` |
| 决策徽章（AGENT/HUMAN） | Press Start 2P | 8px | 语义色 |
| 按钮文字 | Press Start 2P | 8–9px | white / 语义色 |
| 数字（匹配度、评分） | Press Start 2P | 13–16px | 语义色 |
| 卡片标题、姓名 | DM Sans 600 | 12–13px | `var(--text)` |
| 正文描述 | DM Sans 400 | 11–13px | `var(--muted)` |
| 技能标签、小标注 | DM Sans 400 | 9–10px | 语义色 |

### 2.4 像素阴影规范

HireNet 的像素质感核心来自硬阴影（无模糊半径）：

- 标准卡片：`box-shadow: 3px 3px 0 rgba(0,80,120,.15)`
- 悬停卡片：`box-shadow: 4-5px 4-5px 0 rgba(0,80,120,.2)`
- 按钮按下：`box-shadow: 1px 1px 0`（同时 `transform: translate(2px,2px)`）
- 按钮悬停：`box-shadow: 5px 5px 0`，同时 `transform: translate(-1px,-1px)`

> **关键**：阴影第三个参数（模糊半径）必须为 `0`，否则失去像素感。

---

## 3. 背景动效实现

### 3.1 天空渐变

天空背景通过 `body::before` 伪元素实现多层渐变：

```css
body::before {
  content: '';
  position: fixed; inset: 0;
  background: linear-gradient(180deg,
    #5bb8d4 0%,   /* 深蓝天顶 */
    #7ec8e3 30%,  /* 中蓝 */
    #a8dcef 60%,  /* 浅蓝 */
    #c8ecf8 100%  /* 接近白色的天边 */
  );
  z-index: 0;
}
```

### 3.2 像素网格

`body::after` 叠加半透明网格，增强像素感：

```css
body::after {
  background-image:
    linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
  background-size: 16px 16px;
}
```

### 3.3 像素云朵

云朵使用纯 CSS 实现，每朵云由主体 + `::before` + `::after` 三个矩形叠加：

```css
.cloud {
  position: absolute;
  background: rgba(255,255,255,.92);
  border: 2px solid rgba(255,255,255,.85);
  animation: drift linear infinite;
}
.cloud::before, .cloud::after {
  content: '';
  position: absolute;
  background: rgba(255,255,255,.92);
  border: 2px solid rgba(255,255,255,.85);
}
@keyframes drift {
  from { transform: translateX(-200px); }
  to   { transform: translateX(calc(100vw + 200px)); }
}
```

三种云朵尺寸（`.c1`/`.c2`/`.c3`），通过不同 `animation-duration` 和 `animation-delay` 错开，避免同步感：

| 类名 | 主体尺寸 | 飘移速度 | 初始延迟 |
|------|---------|---------|---------|
| `.c1` | 64×20px | 55–65s | 0s |
| `.c2` | 80–96×22px | 78–90s | -22 ~ -28s |
| `.c3` | 52–56×16px | 48–55s | -34 ~ -42s |

### 3.4 小鸟飞翔

用 emoji 🐦 实现从左到右飞过的小鸟效果：

```css
.bird {
  position: fixed;
  font-size: 12–14px;
  animation: fly linear infinite;
}
@keyframes fly {
  from { transform: translateX(-60px); }
  to   { transform: translateX(calc(100vw + 60px)); }
}
```

> 修改方式：调整 `font-size` 改变鸟的大小，`top` 值改变飞行高度，`animation-duration` 改变速度。

---

## 4. 页面详细实现

### 4.1 index.html — 角色选择页

#### 4.1.1 布局结构

全屏居中 Flexbox 布局，内容层 `z-index: 10` 叠在背景之上：

```
body  → display: flex; flex-direction: column
nav   → position: relative; z-index: 20（固定在顶部）
.hero → position: relative; z-index: 10; flex: 1（占满剩余空间）
.ground → position: fixed; bottom: 0（固定草地）
```

#### 4.1.2 草地与花朵

草地为固定定位的绿色矩形，顶部有 `repeating-linear-gradient` 条纹模拟草地纹理：

```css
.ground {
  position: fixed; bottom: 0; height: 80px;
  background: linear-gradient(#7abf5a, #4a8a2a);
  border-top: 4px solid #4a8a2a;
}
```

花朵用一行 emoji 排列在草地顶部（`.flowers` 容器）。

#### 4.1.3 角色卡片

两张卡片使用 `display: flex + gap` 横向排列，每张宽 280px。悬停时触发像素偏移动画：

```css
.role-card:hover {
  transform: translate(-3px, -3px);
  box-shadow: 7px 7px 0 rgba(0,80,120,.25);
}
.role-card:active {
  transform: translate(2px, 2px);
  box-shadow: 2px 2px 0 rgba(0,80,120,.2);
}
```

---

### 4.2 employer.html — 雇主端控制台

#### 4.2.1 三栏 Grid 布局

```css
main {
  display: grid;
  grid-template-columns: 285px 1fr 305px;
  height: calc(100vh - 48px);  /* 减去导航栏高度 */
}
```

| 栏 | 宽度 | 内容 |
|----|------|------|
| 左栏 | 285px（固定） | 任务输入区：文本框 + 快捷按钮 + 开始分析 + Agent 状态 |
| 中栏 | 1fr（弹性） | AI 分析过程：四步 Agent 卡片依次展开 |
| 右栏 | 305px（固定） | 执行结果：Agents Tab + Humans Tab 切换 |

#### 4.2.2 四步分析卡片动画流程

每张步骤卡片（`.sc`）默认 `opacity: 0.3`，激活时变为 `1.0`，完成时边框变绿：

| 状态 | CSS class | 边框颜色 | 透明度 |
|------|-----------|---------|--------|
| 默认（未激活） | `sc` | `var(--bord2)` | 0.3 |
| 进行中 | `sc active` | `var(--pixel)` 蓝色 | 1.0 |
| 已完成 | `sc done` | `var(--green)` 绿色 | 1.0 |

JS 动画流程（伪代码）：

```js
showLoading(agentName, text, progress%)  // 显示全屏加载
await sleep(1600ms)                       // 模拟 API 调用
hideLoading()                             // 隐藏加载
card.style.display = ''                   // 显示卡片
card.classList.add('active')              // 激活状态
// 填入数据...
await sleep(400ms)
card.classList.remove('active')
card.classList.add('done')               // 完成状态
```

#### 4.2.3 置信度进度条

每个决策项下方有动态加载的置信度条。核心技巧：先设 `width:0`，异步后设目标宽度，CSS `transition` 完成动画：

```html
<!-- HTML -->
<div class="cbf" style="width:0%" data-t="85%"></div>
```

```js
// JS（在卡片显示后 100ms 触发）
document.querySelectorAll('.cbf').forEach(el => {
  el.style.width = el.dataset.t;  // CSS transition: width 1s ease
});
```

#### 4.2.4 Loading 覆盖层

全屏半透明遮罩显示当前执行的 Agent 名称和进度条：

```css
#lo {
  position: fixed; inset: 0;
  background: rgba(100,185,215,.72);
  backdrop-filter: blur(3px);
  z-index: 100;
  display: none;  /* 通过 .show class 切换为 flex */
}
```

#### 4.2.5 快捷场景数据结构

四个演示场景的数据存储在 JS 常量 `D` 中，每个场景包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `req` | object | 结构化需求：项目名、描述、持续时间、团队背景、预算 |
| `tasks` | array | 任务列表：名称、类型、工时、图标 |
| `dec` | array | 决策列表：任务名、决策类型(agent/hybrid/human)、置信度 |
| `costs` | object | 成本对比：全Agent/协同/全人工，`rec` 指定推荐项 |
| `water` | number\|null | JD水分评分（null 表示不显示） |
| `cands` | array | 候选人列表（仅需要人工时展示） |

---

### 4.3 jobseeker.html — 求职者端

#### 4.3.1 两列 Grid 布局

```css
/* 上半区：机会推荐 + 个人画像 */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
/* 响应式：小屏单列 */
@media(max-width: 700px) {
  .two-col { grid-template-columns: 1fr; }
}
```

#### 4.3.2 技能进度条动画

页面加载完成后 300ms 触发技能条动画（避免与渲染竞争）：

```js
window.addEventListener('load', () => {
  setTimeout(() => {
    document.querySelectorAll('.p-bar-fill').forEach(el => {
      el.style.width = el.dataset.w;  // data-w 存储目标百分比
    });
  }, 300);
});
```

#### 4.3.3 时间轴样式

时间轴用 Flexbox 实现，左侧为连接线列（dot + line），右侧为内容：

```css
.tl-item { display: flex; gap: 14px; }
.tl-dot-col { display: flex; flex-direction: column; align-items: center; width: 20px; }
.tl-dot { width: 12px; height: 12px; border-radius: 0; border: 2px solid; }
.tl-line { flex: 1; width: 2px; background: var(--bord2); }
```

> **注意**：`border-radius: 0` 是关键，保证像素方形风格，不要改成圆形。

---

## 5. 通用组件规范

### 5.1 按钮系统

| 类名 | 外观 | 用途 |
|------|------|------|
| `.btnp` | 实心蓝色，像素阴影，全宽 | 主操作按钮（开始分析） |
| `.bsm.bo` | 描边灰色，无背景 | 次要操作（查看详情） |
| `.bsm.bf` | 描边蓝色，浅蓝背景 | 主要操作（一键参与/发起联系） |
| `.bsm.bf`（green） | 描边绿色，浅绿背景 | 确认/完成类操作 |
| `.rc-btn` | 全宽，像素阴影 | 角色选择卡片内的 CTA 按钮 |

所有按钮的按下状态（`:active`）统一为 `transform: translate(2px, 2px)` + 减小阴影，模拟按键按下感。

### 5.2 徽章/状态标签

| 类名 | 颜色 | 用途 |
|------|------|------|
| `.db.agent` | 青色 teal | 任务由 Agent 完成 |
| `.db.hybrid` | 琥珀色 amber | 人机协同完成 |
| `.db.human` | 珊瑚色 coral | 需要人工完成 |
| `.ars`（ready） | 绿色 | Agent 就绪状态 |
| `.ars.run` | 琥珀色 + 闪烁动画 | Agent 执行中 |
| `.tl-badge.done` | 绿色 | 时间轴：已完成 |
| `.tl-badge.pending` | 琥珀色 | 时间轴：等待中 |
| `.tl-badge.new` | 蓝色 | 时间轴：新消息 |

### 5.3 卡片系统

所有卡片遵循统一的像素卡片规范：

- 背景：`rgba(255,255,255,.88-.92)`（半透明白，可透出蓝天背景）
- 边框：`2px solid var(--bord2)`，悬停时变为 `var(--pixel2)`
- 阴影：`var(--sh)`（标准）→ `var(--sh2)`（悬停）
- 悬停动画：`transform: translate(-2px, -2px)`（向左上偏移，强化像素感）
- `border-radius: 0`（无圆角，保持像素风格）

### 5.4 导航栏

三个页面共用相同导航栏结构，高度固定 48px：

```css
nav {
  height: 48px;
  background: rgba(255,255,255,.9);
  border-bottom: 3px solid var(--border);
  box-shadow: 0 3px 0 rgba(0,80,120,.1);
  z-index: 20;
}
```

---

## 6. 前后端对接

### 6.1 Flask 路由配置

在 `app.py` 中添加页面路由：

```python
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/employer')
def employer():
    return render_template('employer.html')

@app.route('/jobseeker')
def jobseeker():
    return render_template('jobseeker.html')
```

### 6.2 API 端点总览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/auth/login` | GET | 发起 OAuth2 登录 |
| `/api/auth/callback` | GET | OAuth2 回调，换取 token |
| `/api/auth/me` | GET | 获取当前用户信息 |
| `/api/analyze/start` | POST | 开始需求分析（多轮对话第一轮） |
| `/api/analyze/reply` | POST | 继续需求分析对话 |
| `/api/analyze/decide` | POST | 触发完整决策流程 |
| `/api/candidates` | GET | 获取演示候选人列表 |
| `/api/match` | POST | 候选人匹配 |
| `/api/health` | GET | 健康检查 |

### 6.3 employer.html 对接后端

目前 `employer.html` 使用硬编码演示数据，替换为真实 API 需修改 `run()` 函数：

```js
async function run() {
  const input = document.getElementById('ti').value.trim();

  // Step 1: 调用后端开始分析
  const res1 = await fetch('/api/analyze/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: input })
  });
  const data1 = await res1.json();
  // data1.session_id 保存备用
  // data1.response 是 Agent 的追问文本

  // Step 2: 多轮对话（如需要）
  // ...

  // Step 3: 触发完整决策
  const res2 = await fetch('/api/analyze/decide', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: data1.session_id })
  });
  const result = await res2.json();
  // result.tasks, result.decisions, result.jd_report
}
```

### 6.4 /api/analyze/decide 返回格式

后端返回 JSON，前端需按此结构渲染：

```json
{
  "requirement": { "project_name": "...", "core_description": "..." },
  "tasks": [
    { "id": "t1", "name": "文案撰写", "type": "creative", "estimated_hours": 8 }
  ],
  "decisions": {
    "decisions": [
      {
        "task_id": "t1",
        "task_name": "文案撰写",
        "recommendation": {
          "decision": "agent",
          "resource": { "name": "文案撰写 Agent", "confidence": 0.91 }
        }
      }
    ]
  },
  "jd_report": {
    "needs_hiring": false,
    "average_water_score": 68,
    "job_designs": [...]
  }
}
```

---

## 7. 常见修改指南

### 7.1 修改主色调

只需修改 `:root` 中的 `--pixel` 变量，所有蓝色元素自动更新：

```css
/* 改为绿色主题 */
:root { --pixel: #2d8c4e; --pixel2: #4aad6a; }
```

### 7.2 修改天空颜色

修改 `body::before` 中的渐变颜色：

```css
body::before {
  background: linear-gradient(180deg,
    #你的颜色1 0%,
    #你的颜色2 35%,
    #你的颜色3 70%,
    #你的颜色4 100%
  );
}
```

### 7.3 调整三栏宽度

修改 `employer.html` 中 `main` 的 `grid-template-columns`：

```css
main {
  grid-template-columns: 300px 1fr 340px;  /* 调整左右栏宽度 */
}
```

### 7.4 添加新演示场景

在 `employer.html` 的 JS 常量 `D` 中添加新键值对：

```js
const D = {
  "你的场景名称": {
    req: { pn: '项目名', cd: '描述', dur: 'one-time', tc: '团队', bh: 'medium' },
    tasks: [{ n: '任务名', t: 'technical', h: 10, i: '💻' }],
    dec: [{ t: '任务名', d: 'agent', c: 0.90, a: '代码生成 Agent' }],
    costs: { a: '$0.10', h: '不适用', p: '¥5,000', r: 'a' },
    water: null, cands: []
  }
};
```

然后在快捷按钮区域添加对应按钮：

```html
<button class="qbtn" onclick="si(this)">
  <span class="ic">🔧</span>你的场景名称
</button>
```

### 7.5 修改候选人数据

`employer.html` 中 `cands` 数组的格式：

```js
cands: [
  {
    n: '候选人姓名',
    t: '职位头衔',
    sk: ['技能1', '技能2', '技能3'],
    m: 87,          // 匹配度百分比
    r: '推荐理由描述',
    av: '👨‍💻'       // 头像 emoji
  }
]
```

### 7.6 关闭云朵/小鸟动效

如果需要更简洁的背景，注释或删除以下元素：

```html
<!-- 删除或注释这些 -->
<div class="clouds">...</div>
<div class="bird b1">🐦</div>
<div class="bird b2">🐦</div>
```

---

## 8. 开发注意事项

### 8.1 字体加载

所有页面依赖 Google Fonts，需要网络连接加载。如需离线使用，下载字体文件后修改 `@font-face`：

```html
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
```

### 8.2 z-index 层级

| 层级 | z-index | 元素 |
|------|---------|------|
| 天空背景 | 0 | `body::before`, `body::after` |
| 云朵层 | 1 | `.clouds` |
| 小鸟层 | 2–5 | `.bird` |
| 草地层 | 3 | `.ground`（index.html） |
| 内容层 | 10 | `.page`, `.hero`, `main` |
| 导航栏 | 20 | `nav` |
| 加载遮罩 | 100 | `#lo`（loading overlay） |

### 8.3 浏览器兼容性

本前端使用了以下现代 CSS 特性，需要 Chrome 88+、Firefox 78+、Safari 14+ 支持：

- `backdrop-filter: blur()`（面板半透明模糊效果）
- CSS Grid（三栏布局）
- CSS 自定义属性（变量）
- `calc()`（云朵飘移动画结束位置）

> 如需支持更旧的浏览器，可移除 `backdrop-filter`，将 `surface` 背景改为不透明 `#ffffff`。

### 8.4 性能优化建议

- 云朵动画使用 `transform` 属性，GPU 加速，不影响布局性能
- 字体使用 `display=swap`，避免 FOIT（字体加载期间不可见）
- Demo 数据内联在 JS 中，无额外网络请求
- 如需进一步优化，可将三个页面的公共 CSS 抽取到 `static/style.css`

---

*— 文档结束 —*
