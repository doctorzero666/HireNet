/* ============================================================
   screen-home.jsx — Page 1 首页
   ============================================================ */
function HomeScreen({ ctx, navigate }) {
  const [value, setValue] = useState(ctx.need || "");
  const [focus, setFocus] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [file, setFile] = useState(ctx.file || null);
  const taRef = useRef(null);

  const examples = [
    { label: "搭建智能客服", icon: "bot", text: "我想为电商平台搭建一套智能客服系统，覆盖售前咨询、售后处理和投诉响应。" },
    { label: "分析销售数据", icon: "chart", text: "帮我分析最近三个季度的销售数据，找出增长机会和异常波动。" },
    { label: "开发数据看板", icon: "grid", text: "我需要一个实时业务数据看板，汇总销售额、客诉率和各渠道转化。" },
  ];

  function pickExample(ex) {
    setValue(ex.text);
    taRef.current && taRef.current.focus();
  }
  function fakeUpload() {
    setFile({ name: "sales_2026Q1.csv", size: "2.4 MB", rows: "18,402 行" });
  }
  function go() {
    if (!value.trim()) { taRef.current && taRef.current.focus(); return; }
    ctx.set({ need: value.trim(), file, hasData: !!file });
    navigate("interview");
  }

  return (
    <div className="center-wrap screen">
      <div className="home">
        <div className="eyebrow" style={{ justifyContent: "center", display: "inline-flex" }}>
          📋 新任务
        </div>
        <h1>今天想完成什么？</h1>
        <p className="sub">把目标交给平台。我们会拆解任务、匹配可信 Agent，并在你的授权范围内安全执行。</p>

        <div className="composer-label">描述你的需求</div>
        <div className={"composer" + (focus ? " focus" : "")}>
          <textarea
            ref={taRef}
            value={value}
            placeholder="例如：我需要为电商平台搭建智能客服系统..."
            onChange={e => setValue(e.target.value)}
            onFocus={() => setFocus(true)}
            onBlur={() => setFocus(false)}
            onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go(); }}
          />
          <div className="composer-bar">
            <button className={"attach-toggle" + (attachOpen ? " on" : "")} onClick={() => setAttachOpen(o => !o)}>
              <Icon name="paperclip" size={15} /> 附加数据 {file && <span className="badge green" style={{ marginLeft: 2 }}>已添加 1</span>}
            </button>
            <button className="btn btn-primary" onClick={go}>
              开始分析 <Icon name="arrow" size={16} />
            </button>
          </div>
          {attachOpen && (
            <div className="attach-panel">
              {!file ? (
                <React.Fragment>
                  <div className="dropzone" onClick={fakeUpload}>
                    <div className="dz-ic"><Icon name="upload" size={22} /></div>
                    <div className="dz-t">拖拽文件到此处，或点击上传</div>
                    <div className="dz-s">支持 CSV、Excel、JSON · 单文件 ≤ 50 MB</div>
                  </div>
                  <div className="secure-note"><Icon name="shield" size={14} /> 数据在浏览器本地处理，不上传服务器</div>
                </React.Fragment>
              ) : (
                <React.Fragment>
                  <div className="file-pill">
                    <div className="fp-ic"><Icon name="file" size={16} /></div>
                    <div style={{ flex: 1 }}>
                      <div className="fp-name">{file.name}</div>
                      <div className="fp-meta">{file.size} · {file.rows}</div>
                    </div>
                    <button className="attach-toggle" onClick={() => setFile(null)}>移除</button>
                  </div>
                  <div className="secure-note"><Icon name="shield" size={14} /> 数据在浏览器本地处理，不上传服务器</div>
                </React.Fragment>
              )}
            </div>
          )}
        </div>
        <p className="composer-hint"><Icon name="paperclip" size={13} /> 支持 CSV / Excel，最大 50MB · 数据在浏览器本地处理，不上传服务器</p>

        <div className="examples">
          {examples.map(ex => (
            <button key={ex.label} className="chip" onClick={() => pickExample(ex)}>
              <Icon name={ex.icon} size={15} /> {ex.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
window.HomeScreen = HomeScreen;
