# HireNet RPG 风格 UI 技术实现文档

**Stardew Valley 像素 RPG 风格前端**
版本 v1.1 · 2026-03-18
文件：`jobseeker_rpg.html`（单文件，无框架依赖）

---

## 1. 设计语言概述

### 1.1 风格定位

本页面以星露谷物语（Stardew Valley）为视觉灵感，实现一套**像素 RPG 游戏 UI 风格**的 Web 界面。核心视觉语言：

- **木质边框**：深棕色渐变 + 木纹条纹模拟真实木板质感
- **羊皮纸背景**：米黄色渐变 + 光晕叠加，模拟旧纸张
- **3D 按压按钮**：底部加厚 border 模拟游戏风凸起按钮，点击时下沉
- **游戏化元素**：等级条、EXP 徽章、解锁奖励、状态徽章
- **自然场景**：蓝天白云 + 草地 + 像素树木 + 摇曳花朵
- **emoji 角色**：用系统 emoji 替代像素插画，保持亲切感

### 1.2 字体组合

| 字体 | 用途 | 引入方式 |
|------|------|---------|
| `Press Start 2P` | 标题 LOGO、等级数字、金币价格 | Google Fonts |
| `Nunito` | 正文、按钮、描述文字 | Google Fonts |

```html
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Nunito:wght@400;600;700;800&display=swap" rel="stylesheet">
```

`Press Start 2P` 只用在少数关键元素上（LOGO、数字），大量文字仍用 `Nunito`，避免全页像素字体导致难以阅读。

---

## 2. CSS 变量系统

当前版本未使用 `:root` 变量，颜色内联在各组件中。如需统一管理，建议迁移为以下变量：

```css
:root {
  /* 木质色系 */
  --wood-dark:    #5a3010;
  --wood-mid:     #8b5e2e;
  --wood-light:   #c8903c;
  --wood-border:  #7a4a18;

  /* 羊皮纸色系 */
  --parch-light:  #f5e8c8;
  --parch-mid:    #ede0b0;
  --parch-dark:   #c8a060;
  --parch-border: #8b6030;

  /* 语义色 */
  --green-btn:    #3ab03a;
  --green-dark:   #1a5a1a;
  --blue-btn:     #4070c0;
  --blue-dark:    #1a3a80;
  --red-badge:    #e84040;
  --gold:         #f0c020;

  /* 文字 */
  --text-dark:    #2a1000;
  --text-mid:     #5a3810;
  --text-light:   #7a5030;

  /* 字体 */
  --font-pixel:   'Press Start 2P', monospace;
  --font-ui:      'Nunito', sans-serif;
}
```

---

## 3. 场景背景实现

### 3.1 层级结构

```
z-index: 0   .scene-bg        天空渐变
z-index: 0   .cloud           飘动的云朵
z-index: 0   .tree            树木 emoji
z-index: 0   .flowers         摇曳花朵
z-index: 0   .path            泥土小路
z-index: 10  .ui-frame        主界面
z-index: 50  .chat-area       底部对话气泡
```

### 3.2 天空与草地渐变

用单个 `div.scene-bg` 实现天空到草地的连续渐变，72% 位置是天空/草地的分界线：

```css
.scene-bg {
  position: fixed; inset: 0;
  background: linear-gradient(180deg,
    #5ba3d9  0%,   /* 深天蓝 */
    #7ec1f0 30%,   /* 中蓝 */
    #a8d8f0 55%,   /* 浅蓝 */
    #c6e8f7 72%,   /* 天边白 */
    #7fc46a 72%,   /* 草地绿（同位置切换，硬边界） */
    #5ea84f 80%,   /* 中草绿 */
    #4a8f3c 100%   /* 深草绿 */
  );
  z-index: 0;
}
```

> **关键技巧**：72% 处两个色标颜色不同但位置相同，形成硬切换边界，模拟像素风格的天地分界。

### 3.3 像素云朵

每朵云由 `.cloud` 主体 + `::before` + `::after` 三个白色矩形叠加，`border-radius: 0` 保持像素方形：

```css
.cloud {
  position: absolute;
  background: #fff;
  border-radius: 0;          /* 像素感：无圆角 */
  animation: drift linear infinite;
  box-shadow: 2px 2px 0 #e8e8e8;  /* 像素阴影 */
}
.cloud::before, .cloud::after {
  content: '';
  position: absolute;
  background: #fff;
}

/* 飘移动画 */
@keyframes drift {
  from { transform: translateX(0); }
  to   { transform: translateX(calc(100vw + 200px)); }
}
```

三朵云的参数差异（错开避免同步感）：

| 类名 | 主体尺寸 | 速度 | 延迟 |
|------|---------|------|------|
| `.cl1` | 80×24px | 55s | 0s |
| `.cl2` | 112×28px | 80s | -30s |
| `.cl3` | 64×20px | 42s | -18s |

每朵云的 `::before` 和 `::after` 形成上方的凸起，模拟积云轮廓：

```css
/* 以 cl1 为例 */
.cl1::before { width:48px; height:20px; top:-18px; left:10px; }
.cl1::after  { width:28px; height:14px; top:-14px; left:36px; }
```

### 3.4 花朵摇曳动画

```css
.flower {
  font-size: 20px;
  animation: sway 3s ease-in-out infinite;
}
/* 用 nth-child 错开相位，避免同步摇摆 */
.flower:nth-child(2n) { animation-delay: -.8s; }
.flower:nth-child(3n) { animation-delay: -1.5s; }

@keyframes sway {
  0%,100% { transform: rotate(-5deg); }
  50%      { transform: rotate(5deg); }
}
```

### 3.5 泥土小路

用 `radial-gradient` + `border-radius: 50%` 模拟地面上的椭圆形泥土路：

```css
.path {
  position: absolute;
  bottom: 24%;
  left: 50%; transform: translateX(-50%);
  width: 120px; height: 120px;
  background: radial-gradient(ellipse,
    #c8a46e 0%, #b8904a 60%, transparent 100%);
  border-radius: 50%;
  opacity: .6;
}
```

---

## 4. 主界面结构

### 4.1 整体布局

```
.ui-frame（居中容器，max-width: 960px）
  ├── .title-area（标题区）
  ├── .tabs（标签页导航）
  └── .board（木质外框）
        └── .columns（三列 Grid）
              ├── .panel（左：Task Explorer）
              ├── .panel（中：My Journey）
              └── .panel（右：Opportunities）
```

### 4.2 三列 Grid

```css
.columns {
  display: grid;
  grid-template-columns: 260px 1fr 280px;
  gap: 12px;
  max-height: calc(100vh - 220px);
}
```

- 左列固定 260px：任务探索（内容少）
- 中列弹性 `1fr`：成长旅程（核心内容）
- 右列固定 280px：机会列表（卡片固定宽度）

---

## 5. 木质边框（Board）实现

这是整个 UI 最关键的视觉元素。

```css
.board {
  /* 木纹渐变：深棕 → 中棕 → 深棕 */
  background: linear-gradient(135deg,
    #8b5e2e 0%, #7a4a1c 40%, #8b5e2e 100%);

  border: 4px solid #5a3010;
  border-radius: 0 12px 12px 12px;  /* 左上直角（与 tab 对齐），其余圆角 */

  /* 三层阴影：外部像素阴影 + 内部高光 + 内部暗边 */
  box-shadow:
    6px 6px 0 #3a1a00,                        /* 外部硬阴影，强化 3D 感 */
    inset 0  2px 0 rgba(255,220,140,.3),      /* 顶部高光 */
    inset 0 -2px 0 rgba(0,0,0,.3);            /* 底部暗边 */
}

/* 木纹竖条纹 */
.board::before {
  content: '';
  position: absolute; inset: 6px;
  background: repeating-linear-gradient(
    90deg,
    transparent 0px, transparent 40px,
    rgba(0,0,0,.04) 40px, rgba(0,0,0,.04) 41px
  );
  pointer-events: none;
}
```

> **关键技巧**：`repeating-linear-gradient` 每 40px 画一条 1px 宽的半透明竖线，模拟木材纹理，透明度仅 0.04 所以非常细腻。

---

## 6. 羊皮纸面板（Panel）实现

### 6.1 面板主体

```css
.panel {
  background: linear-gradient(145deg,
    #f5e8c8 0%,   /* 米黄亮 */
    #ede0b0 50%,  /* 米黄中 */
    #f0e0b8 100%  /* 米黄暗 */
  );
  border: 3px solid #8b6030;
  border-radius: 8px;
  overflow: hidden;

  box-shadow:
    inset 0  2px 4px rgba(255,255,255,.4),   /* 顶部高光 */
    inset 0 -2px 4px rgba(100,60,0,.2),      /* 底部阴影 */
    3px 3px 0 rgba(0,0,0,.2);                /* 外部硬阴影 */
}

/* 羊皮纸光晕感（两个椭圆渐变叠加） */
.panel::before {
  content: '';
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse at 20% 20%,
      rgba(255,240,200,.4) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%,
      rgba(200,160,80,.1) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}
```

### 6.2 面板标题栏

```css
.panel-header {
  background: linear-gradient(180deg, #c8903c 0%, #b07828 100%);
  border-bottom: 3px solid #8b6030;
  padding: 9px 14px;

  /* 底部金色高光线 */
  position: relative;
}
.panel-header::after {
  content: '';
  position: absolute;
  bottom: -1px; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg,
    transparent, rgba(255,220,100,.3), transparent);
}
.panel-title {
  font-weight: 800;
  font-size: 14px;
  color: #fff8e8;
  text-shadow: 1px 1px 0 #5a2800;  /* 文字压印感 */
}
```

---

## 7. 游戏化按钮系统

所有按钮的 3D 按压效果通过 `border-bottom` 加厚实现，点击时缩减：

### 7.1 绿色主按钮（Find Tasks / View Tasks）

```css
.find-tasks-btn {
  background: linear-gradient(180deg, #5cd45c 0%, #3ab03a 100%);
  border: 2px solid #2a7a2a;
  border-bottom: 5px solid #1a5a1a;   /* 加厚底边 = 3D 凸起 */
  border-radius: 8px;
  color: #fff;
  text-shadow: 1px 1px 0 #1a4a1a;
  box-shadow: 0 3px 0 rgba(0,0,0,.2);
}
/* 悬停：轻微上移 */
.find-tasks-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.05);
}
/* 点击：下压，缩减 border-bottom */
.find-tasks-btn:active {
  transform: translateY(3px);
  border-bottom-width: 2px;
  box-shadow: none;
}
```

### 7.2 任务列表按钮（Task Btn）

```css
.task-btn {
  background: linear-gradient(180deg, #e8f0c8 0%, #d4e0a8 100%);
  border: 2px solid #6a8830;
  border-bottom: 4px solid #4a6818;
  border-radius: 6px;
  color: #2a4010;
  position: relative;
}
/* 右侧装饰符 */
.task-btn::after {
  content: '✦';
  position: absolute;
  right: 10px; top: 50%;
  transform: translateY(-50%);
  color: #6a8830;
  font-size: 10px;
}
```

### 7.3 蓝色书签按钮

```css
.opp-btn.secondary {
  background: linear-gradient(180deg, #6090e0 0%, #4070c0 100%);
  border: 2px solid #2850a0;
  border-bottom: 4px solid #1a3a80;
  color: #fff;
  text-shadow: 1px 1px 0 #1a3060;
}
```

---

## 8. 游戏化 UI 组件

### 8.1 经验等级条

```css
/* 外框：深棕色模拟游戏血条背景 */
.level-bar-bg {
  height: 14px;
  background: #8b6030;
  border: 2px solid #5a3010;
  border-radius: 0;           /* 像素感：无圆角 */
  overflow: hidden;
  box-shadow: inset 0 2px 0 rgba(0,0,0,.2);
}

/* 填充：绿色渐变 + 高光条 */
.level-bar-fill {
  height: 100%;
  background: linear-gradient(180deg,
    #60e060 0%, #30b030 60%, #20a020 100%);
  width: 60%;                 /* 进度百分比 */
  position: relative;
  box-shadow: inset 0 2px 0 rgba(255,255,255,.3);
}
/* 顶部高光细线 */
.level-bar-fill::after {
  content: '';
  position: absolute;
  top: 2px; left: 4px; right: 4px;
  height: 3px;
  background: rgba(255,255,255,.4);
}
```

### 8.2 等级徽章

```css
.level-badge {
  width: 40px; height: 40px;
  background: linear-gradient(135deg, #f0c840 0%, #d4a020 100%);
  border: 3px solid #8b6010;
  border-radius: 0;           /* 像素方形 */
  box-shadow: 2px 2px 0 #5a3000;
  font-family: 'Press Start 2P', monospace;
  font-size: 14px;
  color: #3a1800;
}
```

### 8.3 EXP 徽章

```css
.exp-badge {
  background: linear-gradient(180deg, #ffe040 0%, #f0c020 100%);
  border: 2px solid #c09010;
  border-radius: 4px;
  padding: 3px 10px;
  font-weight: 800;
  font-size: 12px;
  color: #5a3000;
  box-shadow: 0 2px 0 #a07010;
}
```

### 8.4 状态徽章

```css
/* 完成状态 */
.status-done {
  color: #1a5a1a;
  background: #c8f0c8;
  border: 2px solid #3a8a3a;
  border-radius: 4px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 800;
}

/* 进行中状态 */
.status-progress {
  color: #7a4a00;
  background: #ffe8a0;
  border: 2px solid #c08820;
}
```

### 8.5 "New!" 红色提示徽章

```css
.new-badge {
  background: #e84040;
  color: white;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid #a82020;
}

/* 右上角新消息数量（带呼吸闪烁） */
.opp-badge {
  background: #e84040;
  animation: pulse-red 2s ease-in-out infinite;
}
@keyframes pulse-red {
  0%,100% { opacity: 1; }
  50%      { opacity: .7; }
}
```

### 8.6 机会卡片匹配度条

```css
.match-bar-bg {
  height: 7px;
  background: #c8a060;         /* 棕色底 */
  border: 1px solid #8b6030;
  border-radius: 0;            /* 像素风 */
  overflow: hidden;
  margin: 6px 0;
}
/* 绿色（高匹配） */
.fill-green { background: linear-gradient(90deg, #3ab030, #60d050); }
/* 琥珀色（中等匹配） */
.fill-amber { background: linear-gradient(90deg, #d09020, #f0b840); }
```

### 8.7 解锁奖励区域

```css
.unlocked-box {
  background: linear-gradient(135deg,
    rgba(255,220,100,.25) 0%,
    rgba(255,200,60,.15) 100%);
  border: 2px solid #d4a030;
  border-radius: 6px;
  padding: 10px 12px;
}
```

---

## 9. 标签页（Tabs）实现

标签页与木质面板顶部无缝连接，激活标签使用浅色渐变：

```css
.tab {
  background: linear-gradient(180deg, #d4a96a 0%, #b8853c 100%);
  border: 3px solid #7a4a18;
  border-bottom: none;         /* 底部无边框，与面板融合 */
  border-radius: 8px 8px 0 0;
  margin-right: 4px;
  font-weight: 800;
  color: #3a1a00;
}
.tab.active {
  background: linear-gradient(180deg, #f0d090 0%, #e0b860 100%);
  color: #2a0e00;
  position: relative;
  z-index: 3;                  /* 遮住 board 的顶部边框 */
}
```

> **连接技巧**：`.board` 的 `border-radius` 设为 `0 12px 12px 12px`（左上直角），配合激活 tab 的 `z-index: 3`，使激活 tab 与面板视觉上融为一体。

---

## 10. 标题 LOGO 实现

```css
.title-logo {
  font-family: 'Press Start 2P', monospace;
  font-size: 32px;
  color: #5a3010;               /* 深棕色主体 */

  /* 多层 text-shadow 模拟像素描边 + 立体感 */
  text-shadow:
     3px  0   0 #f5c842,        /* 右 */
    -3px  0   0 #f5c842,        /* 左 */
     0    3px 0 #f5c842,        /* 下 */
     0   -3px 0 #f5c842,        /* 上 */
     3px  3px 0 #c8860a,        /* 右下阴影 */
    -3px  3px 0 #c8860a;        /* 左下阴影 */
}
```

这个 `text-shadow` 组合在文字四周形成金色描边，再叠加右下方深金色阴影，模拟 RPG 游戏标题字体的立体效果。

---

## 11. 底部对话气泡

```css
.chat-bubble {
  background: linear-gradient(145deg, #fffbf0 0%, #f5e8c0 100%);
  border: 3px solid #8b6030;
  border-radius: 12px 12px 12px 0;   /* 左下直角 = 气泡尾巴方向 */
  box-shadow: 3px 3px 0 rgba(0,0,0,.15);
}
```

气泡方向通过 `border-radius` 控制：左下角为 `0`（直角），其余三角为圆角，形成"向左说话"的视觉效果。

### 机器人吉祥物动画

```css
.chat-mascot {
  font-size: 48px;
  animation: bounce 2s ease-in-out infinite;
}
@keyframes bounce {
  0%,100% { transform: translateY(0); }
  50%      { transform: translateY(-4px); }
}
```

---

## 12. 常见修改指南

### 12.1 修改配色主题

**整体木质色**：修改 `.board` 和 `.panel-header` 的背景渐变颜色。

**整体羊皮纸色**：修改 `.panel` 的背景渐变，`#f5e8c8` → `#e8f5e8`（绿色羊皮纸）。

**按钮颜色**：修改 `.find-tasks-btn` 的渐变色和 `border-color`。

### 12.2 替换 emoji 为像素图片

把 emoji 字符替换为 `<img>` 标签，并加上像素渲染属性：

```html
<!-- 原来 -->
<div class="opp-avatar">🦉</div>

<!-- 替换为像素图 -->
<div class="opp-avatar">
  <img src="owl_pixel.png" width="44" height="44"
       style="image-rendering: pixelated;">
</div>
```

**推荐素材来源**：
- [itch.io](https://itch.io/game-assets/free/tag-pixel-art) 搜索 `pixel RPG UI` 或 `pixel characters`
- AI 生图：Midjourney 提示词 `pixel art character, stardew valley style, 32x32, white background`

### 12.3 调整三列宽度

```css
.columns {
  /* 默认 */
  grid-template-columns: 260px 1fr 280px;

  /* 更宽的中列 */
  grid-template-columns: 240px 1fr 260px;

  /* 两列布局（去掉右列） */
  grid-template-columns: 280px 1fr;
}
```

### 12.4 添加新任务按钮

在左侧面板的 `.panel-body` 中追加：

```html
<button class="task-btn">你的新任务名称</button>
```

### 12.5 修改等级进度条

```html
<!-- 修改 width 百分比控制进度 -->
<div class="level-bar-fill" style="width: 75%"></div>

<!-- 修改文字显示当前/最大经验 -->
<span class="level-fraction">375/500</span>
```

### 12.6 新增机会卡片

复制 `.opp-card` 块，修改以下字段：

```html
<div class="opp-card">
  <div class="opp-card-top">
    <span class="new-badge">New!</span>
    <span class="opp-title-text">任务标题</span>
  </div>
  <div class="opp-details">
    <div class="opp-avatar">🐱</div>           <!-- emoji 或图片 -->
    <div class="opp-tags-col">
      <!-- tag 类型：tag-hybrid / tag-frontend / tag-agent -->
      <span class="opp-type-tag tag-agent">Agent Only</span>
      <span class="opp-price"> $200</span>
      <div class="opp-desc">任务描述文字。</div>
      <!-- fill-green（高匹配）或 fill-amber（中等匹配） -->
      <div class="match-bar-bg">
        <div class="match-bar-fill fill-green" style="width:80%"></div>
      </div>
    </div>
  </div>
  <div class="opp-btns">
    <button class="opp-btn primary">View Task</button>
    <button class="opp-btn secondary">🔖 Bookmark</button>
  </div>
</div>
```

### 12.7 修改对话气泡内容

```html
<div class="chat-bubble">
  你的对话内容文字...
  <div class="chat-btn-row">
    <button class="chat-btn">💬 Chat</button>
    <button class="chat-btn">→ 自定义操作</button>
  </div>
</div>
```

### 12.8 关闭背景动效

如需静态背景，注释或删除以下元素和对应 CSS：

```html
<!-- 删除这些元素 -->
<div class="cloud cl1"></div>
<div class="cloud cl2"></div>
<div class="cloud cl3"></div>
<div class="flowers">...</div>
```

```css
/* 删除对应动画 */
@keyframes drift { ... }
@keyframes sway { ... }
@keyframes bounce { ... }
```

---

## 13. z-index 层级总览

| 层级 | z-index | 元素 | 说明 |
|------|---------|------|------|
| 场景背景 | 0 | `.scene-bg` | 天空渐变 |
| 云朵/树木/花朵 | 0 | `.cloud`, `.tree`, `.flowers` | 场景装饰 |
| 主界面 | 10 | `.ui-frame` | 整体 UI 容器 |
| 标签页激活 | 3 | `.tab.active` | 覆盖木框顶部边框 |
| 木框内容 | 1 | `.columns` | 三列面板 |
| 面板内容 | 1 | `.panel-body` | 相对于 panel::before 提升 |
| 对话气泡 | 50 | `.chat-area` | 浮于一切内容之上 |

---

## 14. 浏览器兼容性

| 特性 | 最低支持 | 说明 |
|------|---------|------|
| CSS Grid | Chrome 57+ | 三列布局 |
| CSS 自定义属性 | Chrome 49+ | 变量系统 |
| `inset` 简写 | Chrome 87+ | 等同 `top:0;right:0;bottom:0;left:0` |
| `calc()` | Chrome 26+ | 面板高度计算 |
| `backdrop-filter` | Chrome 76+ | 本页未使用 |
| `animation` | Chrome 43+ | 所有动效 |

> 所有目标特性在 Chrome 87+、Firefox 78+、Safari 14+ 均可正常工作。

---

*— 文档结束 —*
