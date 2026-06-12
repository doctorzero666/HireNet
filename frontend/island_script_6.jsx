/* ============================================================
   screen-execution.jsx — Page 5 执行与结果
   ============================================================ */
function ExecutionScreen({ ctx, navigate }) {
  const stages = [
    "连接知识库与品类语料…",
    "生成售前咨询话术…",
    "生成售后 / 退换货话术…",
    "生成投诉处理话术…",
    "去重、合规校验与质量评分…",
    "打包结果并写入版税记录…",
  ];
  const [progress, setProgress] = useState(0);
  const [stageIdx, setStageIdx] = useState(0);
  const [done, setDone] = useState(false);
  const logs = useRef([]);

  useEffect(() => {
    let p = 0;
    const id = setInterval(() => {
      p += Math.random() * 7 + 3;
      if (p >= 100) { p = 100; clearInterval(id); setProgress(100); setStageIdx(stages.length); setTimeout(() => setDone(true), 500); return; }
      setProgress(p);
      setStageIdx(Math.min(stages.length - 1, Math.floor(p / (100 / stages.length))));
    }, 380);
    return () => clearInterval(id);
  }, []);

  const generated = Math.round((progress / 100) * 120);

  return (
    <div className="exec screen">
      <div className="eyebrow">⚡ 执行中</div>
      <h1 style={{ fontSize: 24, letterSpacing: "-.025em", margin: "12px 0 22px", color: "var(--indigo-950)" }}>
        {ctx.task || "客服话术库搭建"}
      </h1>

      {/* progress */}
      <div className="card exec-progress">
        <div className="exec-agent">
          <div className="avatar indigo lg">客</div>
          <div style={{ flex: 1 }}>
            <div className="ea-name">{ctx.agent ? ctx.agent.name : "客服话术大师 Pro"}</div>
            <div className="ea-status">
              {!done ? <React.Fragment><span className="pulse-dot" /> {stages[Math.min(stageIdx, stages.length - 1)]}</React.Fragment>
                     : <React.Fragment><Icon name="checkCircle" size={14} style={{ color: "var(--emerald-600)" }} /> 执行完成，已交付</React.Fragment>}
            </div>
          </div>
          <div className="badge indigo tnum">{Math.round(progress)}%</div>
        </div>
        <div className="progress-track"><div className="progress-fill" style={{ width: progress + "%" }} /></div>
        <div className="exec-meta">
          <span>已生成 <b className="tnum">{generated}</b> / 预估 120 条话术</span>
          <span>已消费 <b className="tnum">${(progress / 100 * 54).toFixed(1)}</b> / 限额 ${ctx.pactLimit || 60}</span>
        </div>

        {!done && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--line-2)", paddingTop: 12 }}>
            {stages.slice(0, stageIdx + 1).map((s, i) => (
              <div className="log-line" key={i}>
                {i < stageIdx
                  ? <span className="ll-ic"><Icon name="check" size={13} /></span>
                  : <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />}
                {s}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* deliverables */}
      {done && (
        <div className="card deliver">
          <div className="deliver-head">
            <h3>结果交付</h3>
            <div className="badge green"><Icon name="checkCircle" size={13} /> 已通过质量校验</div>
          </div>

          <div className="result-tags">
            <div className="result-tag"><div><div className="rt-n tnum">40</div><div className="rt-l">售前话术</div></div></div>
            <div className="result-tag"><div><div className="rt-n tnum">50</div><div className="rt-l">售后话术</div></div></div>
            <div className="result-tag"><div><div className="rt-n tnum">30</div><div className="rt-l">投诉处理</div></div></div>
            <div className="result-tag"><div><div className="rt-n tnum" style={{ color: "var(--ink)" }}>1.8h</div><div className="rt-l">总耗时</div></div></div>
            <div className="result-tag"><div><div className="rt-n tnum" style={{ color: "var(--amber-600)" }}>$54</div><div className="rt-l">总费用</div></div></div>
          </div>

          <div className="cost-break">
            <div className="cb-row"><span className="cb-k"><Icon name="user" size={14} /> 创作者收益（70%）</span><span className="cb-v tnum">$37.80</span></div>
            <div className="cb-row"><span className="cb-k"><Icon name="grid" size={14} /> 平台服务费（20%）</span><span className="cb-v tnum">$10.80</span></div>
            <div className="cb-row"><span className="cb-k"><Icon name="doc" size={14} /> 税费（10%）</span><span className="cb-v tnum">$5.40</span></div>
            <div className="cb-row total"><span className="cb-k">合计已结算</span><span className="cb-v tnum">$54.00</span></div>
          </div>
          <div className="royalty mono">版税记录编号：RY-2026-0608-7AB3 · 已上链存证</div>

          <div className="deliver-actions">
            <button className="btn btn-primary"><Icon name="download" size={15} /> 下载话术库</button>
            <button className="btn btn-ghost"><Icon name="eye" size={15} /> 预览</button>
            <button className="btn btn-ghost" onClick={() => navigate("dashboard")}><Icon name="check" size={15} /> 验收确认</button>
          </div>
        </div>
      )}
    </div>
  );
}
window.ExecutionScreen = ExecutionScreen;
