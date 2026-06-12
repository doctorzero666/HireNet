import { useState } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Icon from '../components/Icon'
import AgentTaskCard from '../components/AgentTaskCard'
import HiringTaskCard from '../components/HiringTaskCard'
import HybridTaskCard from '../components/HybridTaskCard'
import PactConfirmationModal from '../components/PactConfirmationModal'
import JdModal from '../components/JdModal'

export default function AnalysisReport() {
  const { sessionId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const result = location.state
  const [pactTask, setPactTask] = useState(null)
  const [jdTask, setJdTask] = useState(null)

  if (!result) {
    return (
      <Scene>
        <Board maxWidth={720}>
          <NavBar role="employer" />
          <div className="report">
            <div className="report-head">
              <div className="eyebrow"><Icon name="warning" size={14} /> 报告丢失</div>
              <h1>报告丢失</h1>
              <p>
                没有找到 session <code>{sessionId}</code> 的执行方案。
                <br />刷新会丢失状态，请重新发起分析。
              </p>
            </div>
            <div style={{ textAlign: 'center', marginTop: 18 }}>
              <button
                type="button"
                className="btn btn-soft"
                onClick={() => navigate('/employer')}
              >
                重新开始 <Icon name="arrow" size={16} />
              </button>
            </div>
          </div>
        </Board>
      </Scene>
    )
  }

  const tasks = result.tasks ?? []
  const decisionsRaw = result.decisions ?? {}
  const decisions = Array.isArray(decisionsRaw) ? decisionsRaw : (decisionsRaw.decisions ?? [])
  const decisionByTaskId = Object.fromEntries(decisions.map((d) => [d.task_id, d]))

  const counts = decisions.reduce(
    (acc, d) => {
      const k = d?.recommendation?.decision
      if (k === 'agent') acc.agent += 1
      else if (k === 'human') acc.human += 1
      else if (k === 'hybrid') acc.hybrid += 1
      return acc
    },
    { agent: 0, human: 0, hybrid: 0 },
  )

  const summaryText =
    typeof result.summary === 'string'
      ? result.summary
      : (result.summary?.verdict ?? null)

  return (
    <Scene>
      <Board maxWidth={820}>
        <NavBar role="employer" />

        <div className="report">
          <div className="report-head">
            <div className="eyebrow"><Icon name="chart" size={14} /> 分析报告</div>
            <h1>执行方案</h1>
            {summaryText && <p>{summaryText}</p>}
          </div>

          <div className="metric-grid">
            <Metric label="任务数" value={tasks.length} />
            <Metric label="Agent 可执行" value={counts.agent} color="var(--success-active)" />
            <Metric label="需招人" value={counts.human} color="var(--warning-active)" />
            <Metric label="人机协同" value={counts.hybrid} color="#5068d8" />
          </div>

          <div className="section-h">
            <span className="sh-title">拆解任务</span>
            <span className="sh-meta">共 {tasks.length} 项</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {tasks.length === 0 && (
              <div style={{
                textAlign: 'center',
                padding: 30,
                fontSize: 13,
                color: 'var(--text-secondary)',
                fontWeight: 600,
              }}>
                暂无拆解任务
              </div>
            )}
            {tasks.map((task) => {
              const d = decisionByTaskId[task.id]
              const kind = d?.recommendation?.decision
              if (kind === 'agent') {
                return (
                  <AgentTaskCard
                    key={task.id}
                    task={task}
                    decision={d}
                    onLaunch={() => setPactTask({ task, decision: d })}
                  />
                )
              }
              if (kind === 'human') {
                return (
                  <HiringTaskCard
                    key={task.id}
                    task={task}
                    decision={d}
                    onGenerateJD={() => setJdTask({ task, decision: d })}
                  />
                )
              }
              return <HybridTaskCard key={task.id} task={task} decision={d} />
            })}
          </div>

          <div style={{ textAlign: 'center', marginTop: 30 }}>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => navigate('/employer')}
            >
              <Icon name="refresh" size={15} /> 再来一单
            </button>
          </div>
        </div>
      </Board>

      {pactTask && (
        <PactConfirmationModal
          agent={{
            name: pactTask.decision?.recommendation?.resource?.resource_name ?? '客服话术生成器',
            creator: '@李四',
            wallet: '0x1234567890abcdef1234567890abcdef0000abcd',
            pricePerHour: 30,
          }}
          task={{
            id: pactTask.task.id,
            name: pactTask.task.name,
            description: pactTask.task.description,
            estimatedHours: pactTask.task.estimated_hours ?? 2,
          }}
          onConfirm={(settlement) => {
            const tid = pactTask.task.id || 'task-001'
            const taskName = pactTask.task.name
            setPactTask(null)
            navigate(`/employer/execution/${tid}`, {
              state: settlement
                ? { settlement: { ...settlement, task_name: taskName } }
                : undefined,
            })
          }}
          onReject={() => setPactTask(null)}
          onClose={() => setPactTask(null)}
        />
      )}

      {jdTask && (
        <JdModal
          task={jdTask.task}
          decision={jdTask.decision}
          jdReport={result.jd_report}
          onClose={() => setJdTask(null)}
        />
      )}
    </Scene>
  )
}

function Metric({ label, value, color = 'var(--text)' }) {
  return (
    <div className="metric">
      <div className="mv" style={{ color }}>{value}</div>
      <div className="mk">{label}</div>
    </div>
  )
}
