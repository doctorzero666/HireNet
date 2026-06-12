/* ============================================================
   screen-creator-register.jsx — Page 7 创作者注册 / 接入 Agent
   ============================================================ */
function CreatorRegisterScreen({ ctx, navigate }) {
  const [conn, setConn] = useState("mcp");
  const conns = [
    { key: "mcp", ic: "server", t: "本地 MCP Server", rec: true, d: "Agent 在你的电脑上运行，数据不出设备，平台仅转发调用请求 —— 推荐。" },
    { key: "api", ic: "globe", t: "API Endpoint", d: "提供一个 HTTPS 端点，平台按约定协议调用并回收结果。" },
    { key: "manual", ic: "clipboard", t: "手动上传结果", d: "每次任务完成后，由你手动提交交付物，适合非实时场景。" },
  ];
  const benefits = [
    { ic: "list", t: "调用记录", d: "每一次被企业调用的明细，实时可查" },
    { ic: "coins", t: "收益面板", d: "累计 / 待结算收益，Cobo 自动结算" },
    { ic: "pulse", t: "性能分析", d: "准确率、响应时间与企业评分趋势" },
  ];

  function Section({ n, title, children }) {
    return (
      <div className="form-section">
        <div className="form-section-h"><span className="fs-n">{n}</span>{title}</div>
        {children}
      </div>
    );
  }

  return (
    <div className="register screen">
      <div className="register-head">
        <div className="eyebrow" style={{ justifyContent: "center", display: "inline-flex" }}>
          🔧 注册 Agent
        </div>
        <h1>让你的知识和技能<br />被调用、被付费</h1>
        <p>把你的能力封装成一个 Agent。企业按需调用，你按次获得收益 —— 全程由 Cobo 钱包安全结算。</p>
      </div>

      <div className="register-grid">
        {/* form */}
        <div className="card card-pad">
          <Section n="01" title="基本信息">
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Agent 名称 <span className="req">*</span></label>
              <input className="input-text" placeholder="例如：客服话术生成器" defaultValue="" />
            </div>
          </Section>

          <Section n="02" title="能力说明">
            <div className="field">
              <label>能力描述 <span className="req">*</span></label>
              <textarea className="input-text" placeholder="根据企业提供的产品信息和客服场景，自动生成售前咨询、售后服务、退换货处理话术"></textarea>
            </div>
            <div className="field-row" style={{ marginBottom: 0 }}>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>输入格式说明</label>
                <textarea className="input-text" style={{ minHeight: 70 }} placeholder="企业提供：产品信息 + 客服场景 + 品牌调性"></textarea>
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>输出格式说明</label>
                <textarea className="input-text" style={{ minHeight: 70 }} placeholder="返回：结构化话术表，含场景标签和优先级排序"></textarea>
              </div>
            </div>
          </Section>

          <Section n="03" title="接入方式">
            <div className="conn-grid">
              {conns.map(c => (
                <div key={c.key} className={"conn-card" + (conn === c.key ? " sel" : "")} onClick={() => setConn(c.key)}>
                  <div className="cc-ic"><Icon name={c.ic} size={18} /></div>
                  <div style={{ flex: 1 }}>
                    <div className="cc-t">{c.t}{c.rec && <span className="badge indigo">推荐</span>}</div>
                    <div className="cc-d">{c.d}</div>
                  </div>
                  <div className="conn-radio" />
                </div>
              ))}
            </div>
          </Section>

          <Section n="04" title="定价与上线">
            <div className="field" style={{ marginBottom: 0 }}>
              <label>单价 <span className="req">*</span></label>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <div className="price-field">
                  <span className="pf-unit">$</span>
                  <input type="number" defaultValue="30" />
                  <span className="pf-suffix">/ 小时</span>
                </div>
                <span className="hint" style={{ marginTop: 0 }}>同类「电商客服」Agent 建议价 <b style={{ color: "var(--amber-600)" }}>$25–$40 / 小时</b></span>
              </div>
            </div>
          </Section>

          <div className="register-foot">
            <div className="secure-note" style={{ marginTop: 0 }}><Icon name="shield" size={14} /> 你的私钥与本地数据始终由你掌控</div>
            <button className="btn btn-primary btn-lg" onClick={() => navigate("earnings")}>
              <Icon name="rocket" size={15} /> 注册并上线
            </button>
          </div>
        </div>

        {/* benefits aside */}
        <div className="benefits">
          <div className="card card-pad">
            <div className="bn-title">注册后你会得到</div>
            {benefits.map(b => (
              <div className="benefit-row" key={b.t}>
                <div className="br-ic"><Icon name={b.ic} size={17} /></div>
                <div>
                  <div className="br-t">{b.t}</div>
                  <div className="br-d">{b.d}</div>
                </div>
              </div>
            ))}
            <button className="btn btn-ghost btn-block" style={{ marginTop: 16 }} onClick={() => navigate("performance")}>
              <Icon name="eye" size={15} /> 预览企业端看到的效果
            </button>
          </div>
          <div className="royalty-note" style={{ marginTop: 14 }}>
            <span className="rn-ic"><Icon name="coins" size={17} /></span>
            <p>每次调用收入的 <b>70%</b> 归你，结算实时上链，<b>2 分钟</b>即可完成接入。</p>
          </div>
        </div>
      </div>
    </div>
  );
}
window.CreatorRegisterScreen = CreatorRegisterScreen;
