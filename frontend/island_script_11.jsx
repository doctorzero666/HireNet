/* ============================================================
   app.jsx — STARDEW EDITION router + scene mood
   ============================================================ */
function App() {
  const [screen, setScreen] = useState("roleselect");
  const [role, setRole] = useState(null);
  const [ctx, setCtx] = useState({ need: "", file: null, hasData: false });

  const set = useCallback((patch) => setCtx(c => ({ ...c, ...patch })), []);
  const navigate = useCallback((s) => { setScreen(s); if (s !== "pact") window.scrollTo({ top: 0 }); }, []);
  const enter = useCallback((r, s) => { setRole(r); setScreen(s); window.scrollTo({ top: 0 }); }, []);
  const switchRole = useCallback(() => { setRole(null); setScreen("roleselect"); window.scrollTo({ top: 0 }); }, []);

  const ctxApi = { ...ctx, set };
  const isPact = screen === "pact";
  const base = isPact ? "report" : screen;

  // scene mood per screen
  const mood = ["register", "earnings", "performance"].includes(base) ? "indoor"
    : base === "interview" ? "evening" : "day";
  useEffect(() => { document.documentElement.setAttribute("data-mood", mood); }, [mood]);

  function renderScreen(s) {
    switch (s) {
      case "roleselect":  return <RoleSelectScreen enter={enter} />;
      case "home":        return <HomeScreen ctx={ctxApi} navigate={navigate} />;
      case "interview":   return <InterviewScreen ctx={ctxApi} navigate={navigate} />;
      case "report":      return <ReportScreen ctx={ctxApi} navigate={navigate} />;
      case "execution":   return <ExecutionScreen ctx={ctxApi} navigate={navigate} />;
      case "dashboard":   return <DashboardScreen ctx={ctxApi} navigate={navigate} />;
      case "register":    return <CreatorRegisterScreen ctx={ctxApi} navigate={navigate} />;
      case "earnings":    return <CreatorEarningsScreen ctx={ctxApi} navigate={navigate} />;
      case "performance": return <CreatorPerformanceScreen ctx={ctxApi} navigate={navigate} />;
      default:            return <RoleSelectScreen enter={enter} />;
    }
  }

  return (
    <React.Fragment>
      <SceneBackground />
      <div className="app">
        <TopNav screen={base} role={role} navigate={navigate} switchRole={switchRole} />
        <div className="flow" key={base}>
          {renderScreen(base)}
        </div>
        {isPact && <PactModal ctx={ctxApi} navigate={navigate} />}
      </div>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
