/* ============================================================
   screen-roleselect.jsx — Page 0 ROLE SELECT (Guild)
   ============================================================ */
function RoleSelectScreen({ enter }) {
  const employer = {
    role: "ent", icon: "🏢", title: "我是雇主",
    sub: "描述需求 · 智能匹配 · 找到资源。",
    steps: ["描述你的业务需求", "AI 智能拆解与匹配", "启动 Agent 或招募人才"],
    cta: "进入", to: ["enterprise", "home"],
  };
  const seeker = {
    role: "cre", icon: "👤", title: "我是求职者",
    sub: "探索机会 · 参与任务 · 成长路径。",
    steps: ["探索机会，发现合适的任务", "参与任务，让技能被调用", "建立成长路径与版税收益"],
    cta: "进入", to: ["creator", "register"],
  };

  function Card({ d }) {
    return (
      <div className={"role-card " + d.role}>
        <div className={"role-ic " + d.role}>{d.icon}</div>
        <h2>{d.title}</h2>
        <p className="rc-sub">{d.sub}</p>
        <div className="role-steps">
          {d.steps.map((s, i) => (
            <div className="role-step" key={i}>
              <span className="rs-n">{"\u25B8"}</span>
              <span className="rs-t">{s}</span>
            </div>
          ))}
        </div>
        <button className="btn btn-primary btn-lg btn-block rc-btn" onClick={() => enter(d.to[0], d.to[1])}>
          {d.cta} <Icon name="arrow" size={16} />
        </button>
      </div>
    );
  }

  return (
    <div className="center-wrap screen">
      <div className="guild-brand">
        <h1 className="guild-logo"><span className="leaf">🍃</span> HireNet</h1>
        <p className="guild-sub">AI 劳动力网络 · 岛民版</p>
        <div className="guild-pill">🏝️ 让工作像岛上生活一样自然</div>
      </div>
      <div className="roleselect">
        <div className="rs-board-title">
          <Ribbon color="app-teal" size={22}>选择你的身份</Ribbon>
        </div>
        <div className="role-grid">
          <Card d={employer} />
          <Card d={seeker} />
        </div>
        <div className="rs-foot">
          <a>看看谁正在让这个世界运转 · 进入 Agent 世界 <Icon name="arrow" size={14} /></a>
        </div>
      </div>
    </div>
  );
}
window.RoleSelectScreen = RoleSelectScreen;
