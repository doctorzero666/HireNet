/* ============================================================
   screen-report.jsx — Page 3 需求分析报告
   ============================================================ */
function AgentTrustCard({ agent }) {
  return (
    <div className="agent-card">
      <div className="match-reason">
        <Icon name="checkCircle" size={15} />
        <span><b>匹配理由：</b>{agent.reason}</span>
      </div>
      <div className="ac-top">
        <div className="avatar indigo lg">{agent.initial}</div>
        <div style={{ flex: 1 }}>
          <div className="ac-name">
            {agent.name}
            <span className="verified" title="平台认证"><Icon name="checkCircle" size={15} /></span>
          </div>
          <div className="ac-creator">由 <span className="mono">{agent.creator}</span> 创建 · {agent.tag}</div>
        </div>
        <div className="badge green"><span className="led" /> 可立即调用</div>
      </div>
      <div className="ac-metrics">
        <div className="m">
          <div className="mk">准确率</div>
          <div className="mv tnum">{agent.acc}%</div>
          <div className="acc-bar"><i style={{ width: agent.acc + "%" }} /></div>
        </div>
        <div className="m">
          <div className="mk">历史调用</div>
          <div className="mv tnum">{agent.calls}</div>
        </div>
        <div className="m">
          <div className="mk">企业评分</div>
          <div className="mv tnum">{agent.rating} <span style={{ fontSize: 12, color: "var(--faint)", fontWeight: 500 }}>/ 5.0</span></div>
        </div>
      </div>
    </div>
  );
}

function ReportScreen({ ctx, navigate }) {
  const [selected, setSelected] = useState({ t1: true, t2: false, t3: true });
  const selCount = Object.values(selected).filter(Boolean).length;
  const total = (selected.t1 ? 54 : 0) + (selected.t3 ? 120 : 0);

  function launch() {
    ctx.set({
      agent: { name: "客服话术大师 Pro", creator: "@linfeng.ai", initial: "客", rate: 30, hours: 2, limit: 60, addr: "0x7aB3...a1F2" },
      task: "客服话术库搭建",
    });
    navigate("pact");
  }

  const summary = [
    { k: "总任务", v: "3" },
    { k: "可执行 Agent", v: "1", accent: true },
    { k: "需招人", v: "1" },
    { k: "预估总耗时", v: "≈ 6h" },
    { k: "预估总费用", v: "$174", money: true },
  ];

  return (
    <div className="report screen">
      <div className="report-head">
        <div className="eyebrow">📊 分析报告</div>
        <h1>需求分析报告</h1>
        <p>已将「{ctx.need ? ctx.need.slice(0, 22) + (ctx.need.length > 22 ? "…" : "") : "智能客服系统"}」拆解为 3 个任务。其中 1 项可由 Agent 直接完成，1 项建议补充人力，1 项采用人机协同。</p>
      </div>

      {/* top summary strip */}
      <div className="report-summary">
        {summary.map(s => (
          <div className="rsum" key={s.k}>
            <div className="rsum-k">{s.k}</div>
            <div className={"rsum-v tnum" + (s.money ? " money" : "") + (s.accent ? " accent" : "")}>{s.v}</div>
          </div>
        ))}
      </div>

      {/* Task 1 — green, agent */}
      <div className="task green">
        <div className="bar" />
        <div className="task-main">
          <div className="task-top">
            <div>
              <div className="t-k">任务 01</div>
              <h3>客服话术库搭建</h3>
              <div className="ai-note"><Icon name="spark" size={12} /> AI 判断：常规话术生成任务，无需深度业务理解，可直接交付 Agent</div>
            </div>
            <div className="badge green"><span className="led" /> Agent 可完成</div>
          </div>
          <p className="task-desc">基于行业语料与你的品类特征，生成覆盖售前、售后、投诉三类场景的标准话术库，可直接接入现有客服系统。</p>
          <AgentTrustCard agent={{ name: "客服话术大师 Pro", creator: "@linfeng.ai", tag: "电商客服", acc: 96, calls: "1,284 次", rating: "4.9", initial: "客", reason: "你的需求核心是多场景客服话术生成，此 Agent 专精电商客服领域，历史准确率 96%、已被 1,284 次调用。" }} />
          <div className="task-foot">
            <div className="cost-inline">
              <div className="ci"><div className="ck">预估耗时</div><div className="cv tnum">≈ 2 小时</div></div>
              <div className="ci"><div className="ck">预估费用</div><div className="cv amber tnum">$54</div></div>
            </div>
            <button className="btn btn-primary" onClick={launch}><Icon name="rocket" size={15} /> 启动 Agent</button>
          </div>
        </div>
      </div>

      {/* Task 2 — amber, hire */}
      <div className="task amber">
        <div className="bar" />
        <div className="task-main">
          <div className="task-top">
            <div>
              <div className="t-k">任务 02</div>
              <h3>智能路由策略设计</h3>
              <div className="ai-note"><Icon name="spark" size={12} /> AI 判断：高度依赖内部规则与人际协调，超出当前 Agent 能力边界</div>
            </div>
            <div className="badge amber"><span className="led" /> 建议招人</div>
          </div>
          <p className="task-desc">该任务依赖对你内部团队结构、KPI 与历史工单的深度理解，目前没有匹配度足够高的 Agent，建议由专人主导。</p>
          <ul className="reason-list">
            <li><span className="rl-ic"><Icon name="warning" size={15} /></span>需结合内部排班与考核规则，规则高度定制化</li>
            <li><span className="rl-ic"><Icon name="warning" size={15} /></span>现有 Agent 在该场景准确率低于 80% 的可信门槛</li>
          </ul>
          <div className="task-foot">
            <div className="cost-inline">
              <div className="ci"><div className="ck">建议岗位</div><div className="cv">客服策略专家 ×1</div></div>
              <div className="ci"><div className="ck">周期</div><div className="cv tnum">2–3 周</div></div>
            </div>
            <button className="btn btn-ghost"><Icon name="doc" size={15} /> 生成 JD</button>
          </div>
        </div>
      </div>

      {/* Task 3 — violet, collaboration */}
      <div className="task violet">
        <div className="bar" />
        <div className="task-main">
          <div className="task-top">
            <div>
              <div className="t-k">任务 03</div>
              <h3>数据看板开发</h3>
              <div className="ai-note"><Icon name="spark" size={12} /> AI 判断：技术执行可自动化，但上线部署需工程师把关</div>
            </div>
            <div className="badge violet"><span className="led" /> 人机协同</div>
          </div>
          <p className="task-desc">Agent 负责数据接入与可视化生成，工程师负责权限、嵌入与线上部署，分工协作可显著压缩周期。</p>
          <div className="split-grid">
            <div className="split-col">
              <div className="sc-h"><Icon name="spark" size={14} style={{ color: "var(--violet-600)" }} /> Agent 负责</div>
              <ul>
                <li>数据源连接与清洗</li>
                <li>指标口径与图表生成</li>
                <li>看板原型搭建</li>
              </ul>
            </div>
            <div className="split-col">
              <div className="sc-h"><Icon name="user" size={14} style={{ color: "var(--indigo-600)" }} /> 工程师负责</div>
              <ul>
                <li>权限与账号体系</li>
                <li>系统嵌入与联调</li>
                <li>生产环境部署</li>
              </ul>
            </div>
          </div>
          <div className="task-foot">
            <div className="cost-inline">
              <div className="ci"><div className="ck">预估耗时</div><div className="cv tnum">≈ 4 小时 + 1 人日</div></div>
              <div className="ci"><div className="ck">预估费用</div><div className="cv amber tnum">$120</div></div>
            </div>
            <button className="btn btn-soft"><Icon name="grid" size={15} /> 查看协同方案</button>
          </div>
        </div>
      </div>

      <div style={{ height: 20 }} />

      {/* selected + launch bar */}
      <div className="summary-bar">
        <div className="sb-stats">
          <div><div className="sb-k">已选任务</div><div className="sb-v tnum">{selCount} / 3</div></div>
          <div><div className="sb-k">预估总费用</div><div className="sb-v amber tnum">${total}</div></div>
        </div>
        <button className="btn btn-amber btn-lg" onClick={launch}>
          启动已选任务 <Icon name="arrow" size={16} />
        </button>
      </div>
    </div>
  );
}
window.ReportScreen = ReportScreen;
