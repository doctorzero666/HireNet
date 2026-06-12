/* ============================================================
   screen-pact.jsx — Page 4 Pact 确认授权（模态弹窗）
   ============================================================ */
function PactModal({ ctx, navigate }) {
  const a = ctx.agent || { name: "客服话术大师 Pro", creator: "@linfeng.ai", rate: 30, hours: 2, limit: 60, addr: "0x7aB3...a1F2" };
  const [limit, setLimit] = useState(a.limit);
  const [editing, setEditing] = useState(false);

  function confirm() {
    ctx.set({ pactLimit: limit });
    navigate("execution");
  }

  return (
    <div className="overlay" onClick={e => { if (e.target.classList.contains("overlay")) navigate("report"); }}>
      <div className="modal">
        <div className="modal-grid">
          {/* main */}
          <div className="modal-main">
            <div className="modal-head">
              <div className="mh-ic"><Icon name="lock" size={19} /></div>
              <h2>确认 Agent 执行授权</h2>
            </div>
            <p className="modal-sub">授权后，Agent 将在你设定的额度内自动执行并结算。</p>

            <div className="kv">
              <div className="kv-row">
                <span className="kk">执行 Agent</span>
                <span className="vv" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="avatar indigo sm">客</span>{a.name}
                </span>
              </div>
              <div className="kv-row">
                <span className="kk">创作者</span>
                <span className="vv mono">{a.creator}</span>
              </div>
              <div className="kv-row">
                <span className="kk">任务描述</span>
                <span className="vv">{ctx.task || "客服话术库搭建"}</span>
              </div>
              <div className="kv-row">
                <span className="kk">收款方地址</span>
                <span className="vv mono">{a.addr}</span>
              </div>
            </div>

            <div className="kv" style={{ marginTop: 14 }}>
              <div className="kv-row" style={{ alignItems: "center" }}>
                <span className="kk">消费限额（Pact）</span>
                <div className="limit-box">
                  <span className="lb-amt tnum">${limit}</span>
                  <span className="lb-calc">= ${a.rate}/h × {(limit / a.rate).toFixed(limit % a.rate === 0 ? 0 : 1)}h</span>
                </div>
              </div>
              {editing && (
                <div className="kv-row" style={{ background: "var(--surface-2)" }}>
                  <span className="kk">调整额度</span>
                  <input type="range" min={a.rate} max={a.rate * 5} step={a.rate} value={limit}
                    onChange={e => setLimit(Number(e.target.value))}
                    style={{ width: 180, accentColor: "var(--indigo-600)" }} />
                </div>
              )}
            </div>

            <div className="shield-note">
              <span className="sn-ic"><Icon name="shield" size={18} /></span>
              <p>Agent 只能在 Pact 授权范围内消费，超额请求将被 <b>Cobo 策略引擎</b>自动拒绝。你的私钥<b>不会</b>交给 Agent，全程由你掌控。</p>
            </div>

            <div className="modal-actions">
              <button className="btn btn-primary btn-lg" onClick={confirm}><Icon name="check" size={16} /> 确认授权</button>
              <button className="btn btn-ghost btn-lg" onClick={() => setEditing(e => !e)}>调整限额</button>
              <button className="btn btn-danger-ghost btn-lg" onClick={() => navigate("report")}>拒绝</button>
            </div>
          </div>

          {/* aside — Cobo phone mock */}
          <div className="modal-aside">
            <div className="aside-title"><Icon name="shield" size={14} /> Cobo App 二次确认</div>
            <div className="phone">
              <div className="phone-scr">
                <div className="phone-nub" />
                <div className="phone-body">
                  <div style={{ fontSize: 12, color: "rgba(255,255,255,.6)", fontWeight: 600, marginBottom: 4 }}>策略审批请求</div>
                  <div className="cobo-row">
                    <div className="cr-ic" style={{ background: "rgba(99,102,241,.2)", color: "#a5b4fc" }}><Icon name="bot" size={14} /></div>
                    <div><div className="cr-k">申请方</div><div className="cr-v">{a.name}</div></div>
                  </div>
                  <div className="cobo-row">
                    <div className="cr-ic" style={{ background: "rgba(245,158,11,.2)", color: "#fbbf24" }}><Icon name="coins" size={14} /></div>
                    <div><div className="cr-k">额度</div><div className="cr-v tnum">${limit} USDC</div></div>
                  </div>
                  <div className="cobo-row" style={{ borderBottom: "none" }}>
                    <div className="cr-ic" style={{ background: "rgba(16,185,129,.2)", color: "#34d399" }}><Icon name="check" size={14} /></div>
                    <div><div className="cr-k">策略校验</div><div className="cr-v">额度内 · 通过</div></div>
                  </div>
                  <div className="cobo-approve">滑动确认授权 →</div>
                </div>
              </div>
            </div>
            <div className="aside-cap">授权将同步到你的 Cobo 钱包，<br />可随时在 App 中查看与撤销。</div>
          </div>
        </div>
      </div>
    </div>
  );
}
window.PactModal = PactModal;
