/* ============================================================
   screen-dashboard.jsx — Page 6 企业控制台
   ============================================================ */
function Sidebar() {
  const items = [
    { ic: "grid", label: "概览", active: true },
    { ic: "bot", label: "活跃 Agent", count: "4" },
    { ic: "list", label: "任务", count: "3" },
    { ic: "pulse", label: "数据洞察" },
    { ic: "settings", label: "设置" },
  ];
  return (
    <aside className="sidebar">
      <div className="side-org">
        <div className="avatar amber lg">电</div>
        <div>
          <div className="so-name">某电商公司</div>
          <div className="so-plan">企业版 · 4 席</div>
        </div>
      </div>
      <div className="side-section">工作区</div>
      {items.map(it => (
        <a key={it.label} className={"side-item" + (it.active ? " active" : "")}>
          <span className="si-ic"><Icon name={it.ic} size={17} /></span>{it.label}
          {it.count && <span className="si-count">{it.count}</span>}
        </a>
      ))}
    </aside>
  );
}

function DashboardScreen({ ctx, navigate }) {
  const metrics = [
    { k: "月销售额", ic: "coins", cu: { end: 312, prefix: "$", suffix: "K" }, d: "+12%", cls: "up", amber: true, di: "trend", spark: [240, 252, 248, 268, 280, 296, 312], sc: "var(--amber-500)" },
    { k: "活跃 Agent", ic: "bot", cu: { end: 4 }, d: "全部在线", cls: "neutral", spark: [2, 2, 3, 3, 3, 4, 4] },
    { k: "客诉率", ic: "warning", cu: { end: 2.1, suffix: "%", decimals: 1 }, d: "环比下降", cls: "down-good", di: "trend", spark: [3.4, 3.1, 2.9, 2.7, 2.5, 2.3, 2.1], sc: "var(--emerald-500)" },
    { k: "进行中任务", ic: "list", cu: { end: 3 }, d: "2 项今日交付", cls: "neutral", spark: [1, 2, 2, 4, 3, 2, 3] },
  ];

  const agents = [
    { led: "ok", name: "客服话术大师 Pro", creator: "@linfeng.ai", acc: "96%", calls: "1,284", warn: false },
    { led: "ok", name: "销售数据分析师", creator: "@dataguild", acc: "94%", calls: "672", warn: false },
    { led: "warn", name: "退换货处理 Agent", creator: "@servicelab", acc: "76%", calls: "913", warn: true },
  ];

  return (
    <div className="dash screen">
      <Sidebar />
      <main className="dash-main">
        <div className="dash-top">
          <div>
            <h1>欢迎回来，某电商公司</h1>
            <p>截至 6 月 8 日 · 本月运营概览</p>
          </div>
          <button className="btn btn-primary btn-lg" onClick={() => navigate("home")}>
            <Icon name="plus" size={16} /> 发起新业务需求
          </button>
        </div>

        {/* metrics */}
        <div className="metric-grid">
          {metrics.map(m => (
            <div className="metric" key={m.k}>
              <div className="mk"><Icon name={m.ic} size={13} /> {m.k}</div>
              <div className={"mv" + (m.amber ? " amber" : "")}>
                <CountUp {...m.cu} />
              </div>
              <div className={"md " + m.cls}>
                {m.di && <Icon name={m.di} size={12} />}{m.d}
              </div>
            </div>
          ))}
        </div>

        {/* active agents */}
        <div className="section-h">
          <h2><Icon name="bot" size={16} style={{ color: "var(--indigo-600)" }} /> 活跃 Agent</h2>
          <a className="sh-link">查看全部</a>
        </div>
        <div className="card" style={{ overflow: "hidden" }}>
          {agents.map(a => (
            <div className={"agent-row" + (a.warn ? " is-warn" : "")} key={a.name}>
              <span className={"status-led " + a.led} />
              <div className="avatar indigo">{a.name[0]}</div>
              <div>
                <div className="ar-name">{a.name}</div>
                <div className="ar-creator">{a.creator}</div>
              </div>
              <div className="ar-metrics">
                <div className="ar-m">
                  <div className="am-k">准确率</div>
                  <div className={"am-v tnum" + (a.warn ? " warn" : "")}>
                    {a.acc}{a.warn && <span style={{ fontSize: 11, fontWeight: 500 }}> ↓ 91→76</span>}
                  </div>
                </div>
                <div className="ar-m">
                  <div className="am-k">本月调用</div>
                  <div className="am-v tnum">{a.calls}</div>
                </div>
                {a.warn
                  ? <button className="btn btn-warn btn-sm"><Icon name="refresh" size={14} /> 重新训练</button>
                  : <button className="btn btn-ghost btn-sm">详情</button>}
              </div>
            </div>
          ))}
        </div>

        {/* needs attention */}
        <div className="section-h">
          <h2><Icon name="warning" size={16} style={{ color: "var(--amber-500)" }} /> 需要关注</h2>
        </div>
        <div className="alert-grid">
          <div className="alert red">
            <div className="al-h"><span className="al-ic red"><Icon name="warning" size={16} /></span> 退换货 Agent 准确率下降</div>
            <p>近 7 天准确率从 91% 降至 76%，已低于 80% 可信门槛。疑似新增「预售商品」工单类型未覆盖。</p>
            <div className="al-foot">
              <button className="btn btn-warn btn-sm"><Icon name="refresh" size={14} /> 重新训练</button>
              <a className="sh-link" style={{ fontSize: 12.5 }}>查看工单样本</a>
            </div>
          </div>
          <div className="alert amber">
            <div className="al-h"><span className="al-ic amber"><Icon name="warning" size={16} /></span> 直播渠道退货率偏高</div>
            <p>直播渠道退货率达 14.2%，是全站均值的 2.6 倍，集中在运动户外与服饰品类。建议复核话术与尺码引导。</p>
            <div className="al-foot">
              <a className="sh-link" style={{ fontSize: 12.5 }}>查看渠道分析 →</a>
            </div>
          </div>
        </div>

        {/* growth suggestion */}
        <div className="section-h">
          <h2><Icon name="rocket" size={16} style={{ color: "var(--indigo-600)" }} /> 增长建议</h2>
        </div>
        <div className="growth">
          <div className="g-ic"><Icon name="trend" size={20} /></div>
          <div style={{ flex: 1 }}>
            <div className="g-t">新增「运动装备推荐 Agent」</div>
            <div className="g-d">运动户外品类连续 <b>3 个月增长 60%+</b>，但目前缺少专属导购能力。新增推荐 Agent 预计可再提升该品类转化 8–12%。</div>
          </div>
          <button className="btn btn-primary" onClick={() => navigate("home")}>
            <Icon name="plus" size={15} /> 一键创建需求
          </button>
        </div>
      </main>
    </div>
  );
}
window.DashboardScreen = DashboardScreen;
