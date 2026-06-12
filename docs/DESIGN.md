# HireNet DESIGN.md — 莫兰迪色系

> 设计哲学：低压力、长时间可用、去 AI 味。用户带着焦虑来，不应该被界面再施加一层压力。

## 莫兰迪色系（Morandi Palette）

莫兰迪色系的核心是「每个颜色里都有灰度」——不刺眼、不兴奋、不催促。适合需要冷静决策的场景。

```
灰调：不是纯灰，是带暖意的灰（像陶土、像旧纸张）
绿调：不是荧光绿，是带灰的鼠尾草绿（沉稳、生长感）
蓝调：不是科技蓝，是带灰的雾蓝（安静、信任）
粉调：不是少女粉，是带灰的烟粉（暖意、人性化）
```

## 颜色 Token

### 基础色

```css
/* 背景 — 米灰调 */
--bg-page:        #f5f3ef;   /* 暖米白，不是冷白 */
--bg-card:        #faf9f7;   /* 卡片白，微微暖 */
--bg-elevated:    #ffffff;   /* 最高层 */
--bg-subtle:      #f0eeea;   /* 微妙灰底 */

/* 主色 — 鼠尾草绿系（Sage） */
--color-primary:       #7d8a76;   /* 鼠尾草绿 · 按钮/强调/品牌 */
--color-primary-hover: #6b7864;
--color-primary-light: #e8ebe4;   /* 极淡绿 · 标签背景 */

/* 辅助色 — 雾霾蓝系（Dusty Blue） */
--color-secondary:       #8a9aad;  /* 雾蓝 · 次要按钮/信息 */
--color-secondary-light: #eef1f4;

/* 暖调强调 — 烟粉系（Dusty Rose） */
--color-warm:        #b8a09c;   /* 烟粉 · 财务/收益/金额 */
--color-warm-light:  #f5f1ef;

/* 语义色 */
--color-success:       #8a9e81;  /* 灰绿 · 成功 */
--color-success-light: #eef1ea;
--color-warning:       #c4aa82;  /* 灰金 · 警告 */
--color-warning-light: #faf5ed;
--color-danger:        #b38383;  /* 灰红 · 危险/错误 */
--color-danger-light:  #f7efef;

/* 文字 */
--text-primary:    #3d3a37;   /* 深褐灰 · 正文 */
--text-secondary:  #78746e;   /* 中灰 · 辅助文字 */
--text-muted:      #a09b94;   /* 浅灰 · 占位/禁用 */
--text-on-primary: #ffffff;   /* 绿色按钮上的白字 */

/* 边框与阴影 */
--border:          #e5e2dc;   /* 暖灰边框 */
--border-subtle:   #edeae5;
--shadow-card:     0 0 0 1px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.04);
--shadow-elevated: 0 0 0 1px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06);
```

### 颜色使用规则

```
主操作按钮 → --color-primary（鼠尾草绿）
次要按钮   → 白底 + --border 描边
财务数字   → --color-warm（烟粉，金额/收益/费用）
链接/信息  → --color-secondary（雾蓝）
成功状态   → --color-success（灰绿）
警告       → --color-warning（灰金）
危险/删除  → --color-danger（灰红）

绝不用：纯黑 #000、纯白 #fff（只用 off-white）、任何饱和度 > 30% 的颜色
```

## 排版

```css
--font-primary: 'Inter', system-ui, -apple-system, sans-serif;
--font-mono:   'JetBrains Mono', ui-monospace, monospace;

/* 字号 */
--text-xs:   12px;
--text-sm:   14px;
--text-base: 16px;
--text-lg:   20px;
--text-xl:   24px;
--text-2xl:  32px;

/* 字重 */
--weight-normal: 400;
--weight-medium: 500;
--weight-semibold: 600;
```

## 间距

```css
--space-xs:  4px;
--space-sm:  8px;
--space-md:  16px;
--space-lg:  24px;
--space-xl:  32px;
--space-2xl: 48px;
```

## 圆角

```css
--radius-sm:  4px;     /* 标签、小徽章 */
--radius-md:  8px;     /* 按钮、输入框、卡片 */
--radius-lg:  12px;    /* 大卡片 */
--radius-full: 9999px; /* 胶囊标签 */
```

## Do's and Don'ts

```
✅ Do:
  - 背景用暖米白 #f5f3ef，不要纯白
  - 按钮用鼠尾草绿，低调但有辨识度
  - 金额/收益用烟粉，让人注意到但不刺眼
  - 字色用深褐灰 #3d3a37，比纯黑柔和
  - 用阴影和间距创造层级，不用色块堆
  - 留白大方，信息不要挤

❌ Don't:
  - 不要任何饱和度 > 30% 的颜色
  - 不要纯黑文字、不要纯白背景
  - 不要靛蓝/紫色系（那是 AI 产品模板色）
  - 不要荧光绿/亮橙（破坏低压力氛围）
  - 不要渐变色按钮
  - 不要玻璃拟态、不要大阴影
  - 不要装饰性图表、不要假 KPI 卡片
```
