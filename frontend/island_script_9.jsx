/* ============================================================
   screen-creator-earnings.jsx — Page 8 创作者收益面板
   ============================================================ */
function CreatorEarningsScreen({ ctx, navigate }) {
  const metrics = [
    { k: "累计收益", ic: "coins", cu: { end: 840, prefix: "$" }, foot: "自 3 月上线以来", amber: true, big: true, spark: [120, 240, 360, 510, 620, 730, 840], sc: "var(--amber-500)" },
    { k: "本月调用", ic: "pulse", cu: { end: 12 }, foot: "次 · 较上月 +3", spark: [6, 8, 7, 9, 10, 11, 12] },
    { k: "准确率", ic: "target", cu: { end: 94, suffix: "%" }, d: "↑ 2%", cls: "up", spark: [90, 91, 92, 92, 93, 94, 94], sc: "var(--emerald-500)" },
    { k: "待结算", ic: "clock", cu: { end: 280, prefix: "$" }, foot: "accrued · 预计 T+1 到账", amber: true, spark: [40, 90, 120, 160, 210, 250, 280], sc: "var(--amber-500)" },
  ];

  const ledger = [
    { date: "06-08", firm: "某电商公司", task: "客服话术库搭建", dur: "1.8h", inc: "$54", st: "accrued" },
    { date: "06-05", firm: "潮玩工坊", task: "售后话术优化", dur: "1.2h", inc: "$36", st: "settled" },
    { date: "06-01", firm: "鲜程生鲜", task: "投诉应答模板", dur: "0.9h", inc: "$27", st: "settled" },
    { date: "05-27", firm: "某电商公司", task: "大促客服预案", dur: "2.4h", inc: "$72", st: "settled" },
    { date: "05-22", firm: "悦动运动", task: "退换货话术", dur: "1.0h", inc: "$30", st: "settled" },
  ];

  const recent = [
    { firm: "某电商公司", task: "客服话术库搭建 · 130 条", time: "2 小时前" },
    { firm: "潮玩工坊", task: "售后话术优化 · 复用既有模板", time: "3 天前" },
    { firm: "鲜程生鲜", task: "投诉应答模板 · 生鲜场景", time: "7 天前" },
  ];

  const cols = "84px 1.3fr 1.6fr 64px 72px 84px";

  const [stFilter, setStFilter] = useState("all");
  const [range, setRange] = useState("all");
  const shownLedger = ledger.filter(r =>
    (stFilter === "all" || r.st === stFilter) &&
    (range === "all" || r.date.startsWith("06"))
  );

  return (
    <div className="dash screen">
      <CreatorSidebar active="earnings" navigate={navigate} />
      <main className="creator-main">
        <div className="creator-top">
          <div className="avatar indigo lg">客</div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1>客服话术大师 Pro</h1>
              <span className="status-pill on"><span className="status-led ok" style={{ position: "static" }} /> 在线</span>
            </div>
            <div className="ct-sub">@linfeng.ai · 电商客服 · 本地 MCP 接入</div>
          </div>
          <div className="ct-actions">
            <button className="btn btn-ghost" onClick={() => navigate("performance")}><Icon name="pulse" size={15} /> 性能</button>
            <button className="btn btn-ghost" onClick={() => navigate("register")}><Icon name="edit" size={15} /> 编辑</button>
          </div>
        </div>

        {/* metrics */}
        <div className="metric-grid">
          {metrics.map(m => (
            <div className={"metric" + (m.big ? " big" : "")} key={m.k}>
              <div className="mk"><Icon name={m.ic} size={13} /> {m.k}</div>
              <div className={"mv" + (m.amber ? " amber" : "")}>
                <CountUp {...m.cu} />
              </div>
              {m.d
                ? <div className={"md " + m.cls}>{m.d}</div>
                : <div className="mfoot">{m.foot}</div>}
            </div>
          ))}
        </div>

        {/* settlement rule — near the metrics */}
        <div className="royalty-note" style={{ marginTop: 16 }}>
          <span className="rn-ic"><Icon name="coins" size={17} /></span>
          <p>每次被调用，收入的 <b>70% 归你</b> · 15% 归平台 · 15% 归税费，通过 <b style={{ color: "var(--indigo-700)" }}>Cobo Agentic Wallet</b> 实时上链结算。</p>
        </div>

        {/* ledger + recent */}
        <div className="panel-grid" style={{ marginTop: 26 }}>
          <div>
            <div className="section-h" style={{ marginTop: 0 }}>
              <h2><Icon name="coins" size={16} style={{ color: "var(--indigo-600)" }} /> 收益明细</h2>
              <div className="ledger-filters">
                <button className={"fchip" + (range === "all" ? " on" : "")} onClick={() => setRange("all")}>全部</button>
                <button className={"fchip" + (range === "month" ? " on" : "")} onClick={() => setRange("month")}>本月</button>
                <span className="fsep" />
                <button className={"fchip" + (stFilter === "all" ? " on" : "")} onClick={() => setStFilter("all")}>全部</button>
                <button className={"fchip" + (stFilter === "settled" ? " on" : "")} onClick={() => setStFilter("settled")}>已结算</button>
                <button className={"fchip" + (stFilter === "accrued" ? " on" : "")} onClick={() => setStFilter("accrued")}>待结算</button>
              </div>
            </div>
            <div className="card" style={{ overflow: "hidden" }}>
              <div className="ledger-head" style={{ gridTemplateColumns: cols }}>
                <div>日期</div><div>企业</div><div>任务</div><div>耗时</div><div>收入</div><div>状态</div>
              </div>
              {shownLedger.map((r, i) => (
                <div className="ledger-row" style={{ gridTemplateColumns: cols }} key={i}>
                  <div className="lr-date tnum">{r.date}</div>
                  <div className="lr-firm">{r.firm}</div>
                  <div className="lr-task">{r.task}</div>
                  <div className="tnum" style={{ color: "var(--muted)" }}>{r.dur}</div>
                  <div className="lr-inc tnum">{r.inc}</div>
                  <div>
                    {r.st === "settled"
                      ? <span className="badge green"><Icon name="check" size={11} /> 已结算</span>
                      : <span className="badge amber"><span className="led" /> 待结算</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="section-h" style={{ marginTop: 0 }}>
              <h2><Icon name="clock" size={16} style={{ color: "var(--indigo-600)" }} /> 最近调用</h2>
            </div>
            <div className="card card-pad">
              <div className="recent-list">
                {recent.map((r, i) => (
                  <div className="recent-row" key={i}>
                    <div className="avatar amber sm">{r.firm[0]}</div>
                    <div style={{ flex: 1 }}>
                      <div className="rr-firm">{r.firm}</div>
                      <div className="rr-task">{r.task}</div>
                    </div>
                    <div className="rr-time">{r.time}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
window.CreatorEarningsScreen = CreatorEarningsScreen;
