/* ============================================================
   screen-creator-performance.jsx — Page 9 Agent 性能详情
   ============================================================ */
function Stars({ value }) {
  return (
    <span className="stars">
      {[0, 1, 2, 3, 4].map(i => (
        <Icon key={i} name="star" size={14}
          style={{ fill: i < Math.round(value) ? "currentColor" : "none", opacity: i < Math.round(value) ? 1 : .3 }} />
      ))}
    </span>
  );
}

function CreatorPerformanceScreen({ ctx, navigate }) {
  const calls = [
    { firm: "某电商公司", type: "话术库搭建", dur: "1.8h", fb: "good", note: "—" },
    { firm: "潮玩工坊", type: "售后优化", dur: "1.2h", fb: "good", note: "—" },
    { firm: "鲜程生鲜", type: "投诉模板", dur: "0.9h", fb: "good", note: "—" },
    { firm: "某电商公司", type: "大促预案", dur: "2.4h", fb: "good", note: "—" },
    { firm: "悦动运动", type: "退换货话术", dur: "1.0h", fb: "bad", note: "未覆盖预售场景，已补充" },
    { firm: "知物文创", type: "售前咨询库", dur: "1.5h", fb: "good", note: "—" },
  ];
  const cols = "1.2fr 1fr 60px 92px 1.5fr";

  return (
    <div className="dash screen">
      <CreatorSidebar active="performance" navigate={navigate} />
      <main className="creator-main">
        <div className="creator-top">
          <div className="avatar indigo lg">客</div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1>客服话术大师 Pro</h1>
              <span className="status-pill on"><span className="status-led ok" style={{ position: "static" }} /> 在线</span>
            </div>
            <div className="ct-sub">上线于 2026-03-12 · 已稳定运行 88 天</div>
          </div>
          <div className="ct-actions">
            <button className="btn btn-ghost" onClick={() => navigate("register")}><Icon name="edit" size={15} /> 编辑配置</button>
            <button className="btn btn-ghost"><Icon name="pause" size={15} /> 暂停接单</button>
          </div>
        </div>

        {/* core metrics — each with a direction indicator */}
        <div className="perf-grid">
          <div className="perf-card">
            <div className="pk"><Icon name="pulse" size={13} /> 总调用次数</div>
            <div className="pv"><CountUp end={127} /> <span className="pv-sub">次</span></div>
            <div className="pd neutral">本月 12 次</div>
          </div>
          <div className="perf-card">
            <div className="pk"><Icon name="clock" size={13} /> 平均响应</div>
            <div className="pv"><CountUp end={3.2} decimals={1} /> <span className="pv-sub">分钟</span></div>
            <div className="pd up">↓ 0.4 分钟 · 更快</div>
          </div>
          <div className="perf-card">
            <div className="pk"><Icon name="target" size={13} /> 准确率</div>
            <div className="pv"><CountUp end={94} suffix="%" /></div>
            <div className="pd up">↑ 2% · 近 30 天</div>
          </div>
          <div className="perf-card">
            <div className="pk"><Icon name="star" size={13} /> 企业评分</div>
            <div className="pv"><CountUp end={4.8} decimals={1} /> <span className="pv-sub">/ 5</span></div>
            <div className="pd up" style={{ gap: 8 }}><Stars value={4.8} /> ↑ 0.2</div>
          </div>
        </div>

        {/* call records — feedback + failure reason */}
        <div className="section-h">
          <h2><Icon name="list" size={16} style={{ color: "var(--indigo-600)" }} /> 调用记录</h2>
          <span className="faint" style={{ fontSize: 12.5, fontFamily: "var(--mono)" }}>共 127 条</span>
        </div>
        <div className="card" style={{ overflow: "hidden" }}>
          <div className="ledger-head" style={{ gridTemplateColumns: cols }}>
            <div>企业</div><div>任务类型</div><div>耗时</div><div>企业反馈</div><div>备注 / 失败原因</div>
          </div>
          {calls.map((r, i) => (
            <div className="ledger-row" style={{ gridTemplateColumns: cols }} key={i}>
              <div className="lr-firm">{r.firm}</div>
              <div className="lr-task">{r.type}</div>
              <div className="tnum" style={{ color: "var(--muted)" }}>{r.dur}</div>
              <div>
                {r.fb === "good"
                  ? <span className="badge green"><Icon name="check" size={11} /> 满意</span>
                  : <span className="badge amber"><span className="led" /> 待改进</span>}
              </div>
              <div style={{ color: r.note === "—" ? "var(--faint)" : "var(--ink-2)", fontSize: 12.5 }}>{r.note}</div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
window.CreatorPerformanceScreen = CreatorPerformanceScreen;
