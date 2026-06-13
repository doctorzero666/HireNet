import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './styles/tokens-pixel.css'
import './styles/global.css'
import './styles/scene.css'
import './styles/board.css'
import './styles/nav.css'
import './styles/island-pages.css'
import RoleSelect from './pages/RoleSelect'
import Login from './pages/Login'
import EmployerHome from './pages/EmployerHome'
import EmployerHub from './pages/EmployerHub'
import EmployerDashboard from './pages/EmployerDashboard'
import AnalysisChat from './pages/AnalysisChat'
import AnalysisReport from './pages/AnalysisReport'
import ExecutionPage from './pages/ExecutionPage'
import CreatorHome from './pages/CreatorHome'
import AgentWorld from './pages/AgentWorld'
import AgentRegister from './pages/AgentRegister'
import AgentPerformance from './pages/AgentPerformance'
import CreatorLedger from './pages/CreatorLedger'
import JobSeekerHome from './pages/JobSeekerHome'
import JobDetail from './pages/JobDetail'
import CandidateProfile from './pages/CandidateProfile'
import ApplicationResult from './pages/ApplicationResult'
import IdentitySwitcher from './components/IdentitySwitcher'

function App() {
  return (
    <BrowserRouter>
      <IdentitySwitcher />
      <Routes>
        <Route path="/" element={<RoleSelect />} />
        <Route path="/login" element={<Login />} />
        <Route path="/employer" element={<EmployerHome />} />
        <Route path="/employer/hub" element={<EmployerHub />} />
        <Route path="/employer/dashboard" element={<EmployerDashboard />} />
        <Route path="/employer/analysis/:sessionId" element={<AnalysisChat />} />
        <Route path="/employer/report/:sessionId" element={<AnalysisReport />} />
        <Route path="/employer/execution/:taskId" element={<ExecutionPage />} />
        <Route path="/creator" element={<CreatorHome />} />
        <Route path="/agents" element={<AgentWorld />} />
        <Route path="/creator/register" element={<AgentRegister />} />
        <Route path="/creator/agent/:agentId" element={<AgentPerformance />} />
        <Route path="/creator/ledger" element={<CreatorLedger />} />
        <Route path="/jobseeker" element={<JobSeekerHome />} />
        <Route path="/jobseeker/job/:jobId" element={<JobDetail />} />
        <Route path="/jobseeker/profile" element={<CandidateProfile />} />
        <Route path="/jobseeker/result" element={<ApplicationResult />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
