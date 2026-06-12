# HireNet DESIGN.md — 像素风（8-bit Retro）

> 设计哲学：黑客松吸引力优先。复古游戏美学 + 现代产品功能。像用 Game Boy 打开的 SaaS。

## 色彩系统（NES 灵感，限制调色板）

```css
/* 背景 — 深色游戏机风格 */
--bg-page:        #0d1117;   /* 深蓝黑 · 主背景，像旧游戏机暗房 */
--bg-card:        #161b22;   /* 卡片/面板背景 */
--bg-elevated:    #1c2333;   /* 弹出层 */
--bg-input:       #0d1117;   /* 输入框背景 */
--bg-subtle:      #21262d;   /* 微妙区分 */

/* 主色 — 荧光绿（经典终端绿） */
--color-primary:       #3bfc7b;   /* 荧光绿 · 按钮/强调/品牌 */
--color-primary-hover: #5fffa0;
--color-primary-dim:   #1a4d2e;   /* 暗绿 · hover 背景 */

/* 辅助色 — 电光蓝 */
--color-secondary:       #58a6ff;
--color-secondary-dim:   #1a3350;

/* 暖调强调 — 像素金 */
--color-warm:        #ffd33d;   /* 金额/收益 */
--color-warm-dim:    #4d3a00;

/* 语义色 */
--color-success:       #3bfc7b;   /* 同主色 */
--color-warning:       #ffd33d;   /* 同暖金 */
--color-danger:        #ff6b6b;   /* 像素红 */
--color-danger-dim:    #4d1a1a;

/* 文字 */
--text-primary:    #e6edf3;   /* 浅灰白 */
--text-secondary:  #8b949e;   /* 次级灰 */
--text-muted:      #484f58;   /* 禁用灰 */
--text-on-primary: #0d1117;   /* 绿按钮上的黑字 */
--text-on-dark:    #e6edf3;

/* 边框与阴影（像素风硬边） */
--border:          #30363d;   /* 边框色 */
--border-thick:    #58a6ff;   /* 焦点边框 */
--shadow-card:     4px 4px 0 #000000;        /* 像素硬阴影 */
--shadow-button:   2px 2px 0 #000000;
--shadow-elevated: 6px 6px 0 #000000;
```

## 排版

```css
--font-pixel:   'Press Start 2P', monospace;   /* 标题、按钮、徽章 */
--font-ui:      'Departure Mono', 'Fira Code', monospace;  /* 正文、表格、数据 */
--font-mono:    'Departure Mono', monospace;    /* 代码/金额 */

/* 字号（像素风故意压缩了比例） */
--text-xs:   10px;
--text-sm:   11px;
--text-base: 12px;   /* Press Start 2P 12px = 正常 14-15px 的感知 */
--text-lg:   14px;
--text-xl:   18px;
--text-2xl:  24px;
```

**字体加载**：
```html
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
```

Press Start 2P 的 `line-height` 要设为 1.6-2.0 才能正常阅读，因为它本身很高。

## 间距与圆角

```css
/* 像素风用硬边，不用圆角 */
--radius-sm:  0;
--radius-md:  0;
--radius-lg:  0;
--radius-full: 0;  /* 也不用胶囊，用方角徽章 */

/* 间距用 4px 倍数 */
--space-xs:  4px;
--space-sm:  8px;
--space-md:  16px;
--space-lg:  24px;
--space-xl:  32px;
```

## 组件规范

### 卡片
- 背景 #161b22，边框 2px solid #30363d
- 阴影：4px 4px 0 #000
- 内边距：16px
- hover：边框变亮 + 阴影变大（6px 6px 0 #000）

### 按钮
- 主按钮：背景 #3bfc7b，文字 #0d1117（黑字），阴影 2px 2px 0 #000
- hover：阴影变 4px 4px 0 #000，轻微位移（transform: translate(-1px, -1px)）
- active：阴影消失 + 位移（像真的按下去了）
- 字体：Press Start 2P, 10px

### 输入框
- 背景 #0d1117，边框 2px solid #30363d
- 文字 #e6edf3，placeholder #484f58
- 聚焦：边框变 #58a6ff + 像素虚线外框

### 标签/徽章
- 背景 #1a3350 / #1a4d2e / #4d3a00 / #4d1a1a
- 文字对应辅助色
- 边框 1px solid 对应色
- 尖角，不要圆角

### 分割线
- 1px solid #21262d，不用渐变色

### 进度条
- 背景 #21262d，填充 #3bfc7b
- 尖角，高度 12px
- 可以加像素点动画

### 滚动条
- 细，暗色，尖角

## Do's and Don'ts

```
✅ Do:
  - 用硬阴影（4px 4px 0 #000），不放 blur
  - 按钮有「按下」的位移反馈
  - 保持黑色边框 2px+
  - 用 Press Start 2P 做标题和按钮，Departure Mono 做正文
  - 颜色限制在调色板内
  - 卡片之间用间距+阴影区分

❌ Don't:
  - 不用任何圆角
  - 不用渐变、不用模糊、不用半透明
  - 不用现代阴影（0 0 20px rgba）
  - 不要 emoji（用像素图标代替）
  - 不要纯白背景
  - 不要在同一个元素上用超过 3 种颜色
  - 不要大段正文用 Press Start 2P（眼睛会瞎）
```

## 与莫兰迪版本的共享

两套主题共享同一套 React 组件，通过 CSS 变量切换。

```css
/* pixel.css -- 像素风 Token */
@import './tokens-pixel.css';

/* morandi.css -- 莫兰迪 Token */  
@import './tokens-morandi.css';
```

组件代码不变——`TaskCard`、`ChatBubble`、`StatCard` 全用 `var(--bg-card)`、`var(--text-primary)` 等变量。换主题 = 换 CSS 文件。
