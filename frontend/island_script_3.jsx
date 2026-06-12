/* ============================================================
   screen-interview.jsx — Page 2 AI 追问分析
   ============================================================ */
function DataInsight() {
  const stats = [
    { k: "近 90 天销售额", v: "¥4.82M", d: "环比 +18%", cls: "green" },
    { k: "月均增长率", v: "12.4%", d: "高于行业 +5pt", cls: "green" },
    { k: "客诉占比", v: "2.1%", d: "退换货为主", cls: "amber" },
  ];
  return (
    <div className="insight">
      <div className="insight-head">
        <div className="avatar indigo sm"><Icon name="chart" size={13} /></div>
        <div className="ttl">数据洞察 · sales_2026Q1.csv</div>
        <span className="badge gray" style={{ marginLeft: "auto" }}>18,402 行已解析</span>
      </div>
      <div className="insight-stats">
        {stats.map(s => (
          <div className="st" key={s.k}>
            <div className="k">{s.k}</div>
            <div className="v tnum">{s.v}</div>
            <div className={"d " + (s.cls === "green" ? "" : "")} style={{ color: s.cls === "amber" ? "var(--amber-600)" : "var(--emerald-600)" }}>{s.d}</div>
          </div>
        ))}
      </div>
      <div className="insight-find">
        <b>关键发现：</b>运动户外品类连续 3 个月增长 60%+；退换货客诉集中在直播渠道（占比 41%），且多发生在下单后 48 小时内。
      </div>
      <div className="local-note"><Icon name="shield" size={13} /> 以上分析在你的设备本地完成，原始数据未上传</div>
    </div>
  );
}

function InterviewScreen({ ctx, navigate }) {
  const hasData = ctx.hasData;
  const need = ctx.need || "我需要为电商平台搭建智能客服系统。";

  // build the script
  const turns = [
    {
      text: hasData
        ? "收到。我已在本地快速扫描了你上传的销售数据，先同步一份洞察 —— 看起来增长很健康，但售后客诉值得关注。先确认一下：这套客服系统首先要覆盖哪些场景？"
        : "明白。要把这套智能客服系统拆解到位，我先确认几件事。当前最希望它优先覆盖哪些场景？",
      insight: hasData,
      options: ["售前咨询", "售后 / 退换货", "投诉处理", "三者都要"],
    },
    {
      text: "好的。你们的客服主要分布在哪些渠道？这决定了路由与接入方式的复杂度。",
      options: ["网店 + APP", "加上直播间", "全渠道（含私域）"],
    },
    {
      text: "最后一个问题 —— 期望的上线节奏和预算区间大概是？我会据此匹配合适的 Agent 与协作方式。",
      options: ["两周内 · 控制成本", "一个月 · 平衡", "质量优先 · 预算充足"],
    },
  ];

  const [history, setHistory] = useState([]); // {role, text, insight}
  const [turnIdx, setTurnIdx] = useState(0);
  const [aiTyping, setAiTyping] = useState(true);
  const [showOpts, setShowOpts] = useState(false);
  const [generating, setGenerating] = useState(false);
  const scrollRef = useRef(null);

  // start first AI turn
  useEffect(() => {
    setHistory([{ role: "ai", ...turns[0] }]);
  }, []);

  useEffect(() => {
    if (scrollRef.current) window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }, [history, showOpts, generating]);

  function onAiDone() { setAiTyping(false); setTimeout(() => setShowOpts(true), 150); }

  function pick(opt) {
    setShowOpts(false);
    const next = turnIdx + 1;
    setHistory(h => [...h, { role: "user", text: opt }]);
    if (next < turns.length) {
      setTimeout(() => {
        setHistory(h => [...h, { role: "ai", ...turns[next] }]);
        setTurnIdx(next);
        setAiTyping(true);
      }, 450);
    } else {
      // done — generating
      setTimeout(() => {
        setGenerating(true);
        setTimeout(() => navigate("report"), 2600);
      }, 500);
    }
  }

  return (
    <div className="interview screen" ref={scrollRef}>
      <div className="iv-head">
        <div className="avatar indigo lg" style={{ margin: "0 auto" }}><Icon name="bot" size={20} /></div>
        <h2>AI 需求分析</h2>
        <p className="muted" style={{ maxWidth: 460, margin: "0 auto" }}>{need}</p>
      </div>

      {history.map((m, i) => {
        const isLastAi = m.role === "ai" && i === history.length - 1;
        return (
          <div className={"msg " + m.role} key={i}>
            <div className={"avatar " + (m.role === "ai" ? "indigo" : "amber")}>
              {m.role === "ai" ? <Icon name="bot" size={16} /> : <Icon name="user" size={15} />}
            </div>
            <div className="msg-body">
              <div className="who">{m.role === "ai" ? "HireNet Agent" : "你"}</div>
              <div className="bubble">
                {m.role === "ai" && isLastAi
                  ? <StreamText text={m.text} onDone={onAiDone} />
                  : m.text}
              </div>
              {m.role === "ai" && isLastAi && m.insight && !aiTyping && <DataInsight />}
              {m.role === "ai" && isLastAi && showOpts && (
                <div className="quick-opts">
                  {m.options.map(o => (
                    <button key={o} className="quick-opt" onClick={() => pick(o)}>{o}</button>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {generating && (
        <div className="generating">
          <div className="spinner" />
          <div style={{ textAlign: "center" }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>正在生成需求分析报告…</div>
            <div className="muted" style={{ fontSize: 13, marginTop: 5 }}>拆解任务 · 匹配 Agent · 估算成本</div>
          </div>
        </div>
      )}
    </div>
  );
}
window.InterviewScreen = InterviewScreen;
