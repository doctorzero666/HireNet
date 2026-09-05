import { useEffect, useState } from 'react'
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
import { fetchDemoAgent } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

/**
 * WP-I18N-2 / D-D — `summary.verdict` is rendered verbatim.
 *
 * It used to be recomposed here from `verdict_type` / `agent_tasks` /
 * `human_tasks` whenever `lang === 'en'`, because the backend only ever sent
 * Chinese for this one field. The backend emits it in the request's language
 * now (`app/app.py: VERDICT_*`), so that third translation mechanism is gone.
 * The string branch stays for a legacy summary that was a plain string.
 */
function summaryVerdictText(summary) {
  if (!summary) return null
  if (typeof summary === 'string') return summary
  return summary.verdict ?? null
}

export default function AnalysisReport() {
  const { sessionId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { t, lang } = useLang()
  const result = location.state
  const [pactTask, setPactTask] = useState(null)
  const [jdTask, setJdTask] = useState(null)
  /* Demo agent metadata for the Pact modal. Null until server responds;
     fetchDemoAgent returns null on 404 (TESTING / bootstrap off), in which
     case we fall back to the existing hardcoded values below so the demo
     flow degrades cleanly instead of blocking on a missing endpoint.
     Unlike `result` (the analyze session's own LLM output, whose language is
     fixed at generation time by design), this is bootstrap metadata fetched
     independently of the session — so it re-fetches on a language switch. */
  const [demoAgent, setDemoAgent] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchDemoAgent()
      .then((agent) => { if (!cancelled) setDemoAgent(agent) })
      .catch(() => { /* swallow — modal falls back to hardcoded demo data */ })
    return () => { cancelled = true }
  }, [lang])

  if (!result) {
    return (
      <Scene>
        <Board maxWidth={720}>
          <NavBar role="employer" />
          <div className="report">
            <div className="report-head">
              <div className="eyebrow"><Icon name="warning" size={14} /> {t('analysisReport.lost.eyebrow')}</div>
              <h1>{t('analysisReport.lost.title')}</h1>
              <p>
                {t('analysisReport.lost.bodyPrefix')} <code>{sessionId}</code> {t('analysisReport.lost.bodySuffix')}
                <br />{t('analysisReport.lost.hint')}
              </p>
            </div>
            <div style={{ textAlign: 'center', marginTop: 18 }}>
              <button
                type="button"
                className="btn btn-soft"
                onClick={() => navigate('/employer')}
              >
                {t('analysisReport.lost.restart')} <Icon name="arrow" size={16} />
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

  const summaryText = summaryVerdictText(result.summary)

  return (
    <Scene>
      <Board maxWidth={820}>
        <NavBar role="employer" />

        <div className="report">
          <div className="report-head">
            <div className="eyebrow"><Icon name="chart" size={14} /> {t('analysisReport.eyebrow')}</div>
            <h1>{t('analysisReport.title')}</h1>
            {summaryText && <p>{summaryText}</p>}
          </div>

          <div className="metric-grid">
            <Metric label={t('analysisReport.metrics.taskCount')} value={tasks.length} />
            <Metric label={t('analysisReport.metrics.agentReady')} value={counts.agent} color="var(--success-active)" />
            <Metric label={t('analysisReport.metrics.needsHiring')} value={counts.human} color="var(--warning-active)" />
            <Metric label={t('analysisReport.metrics.hybrid')} value={counts.hybrid} color="#5068d8" />
          </div>

          <div className="section-h">
            <span className="sh-title">{t('analysisReport.tasksHeading')}</span>
            <span className="sh-meta">{t('analysisReport.tasksCount', { count: tasks.length })}</span>
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
                {t('analysisReport.noTasks')}
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
              <Icon name="refresh" size={15} /> {t('analysisReport.startAnother')}
            </button>
          </div>
        </div>
      </Board>

      {pactTask && (
        <PactConfirmationModal
          agent={{
            /* Prefer demoAgent (server-bootstrapped, real asset_id / creator);
               fall back to legacy hardcoded values when /api/demo/agent 404s
               (TESTING path or older deploys without the bootstrap). */
            name: demoAgent?.name
              ?? pactTask.decision?.recommendation?.resource?.resource_name
              ?? t('analysisReport.demoAgent.name'),
            creator: demoAgent?.creator_name
              ? `@${demoAgent.creator_name}`
              : t('analysisReport.demoAgent.creator'),
            wallet: demoAgent?.wallet ?? '0x1234567890abcdef1234567890abcdef0000abcd',
            pricePerHour: demoAgent?.price_per_hour ?? 30,
            asset_id: demoAgent?.asset_id,
            creator_id: demoAgent?.creator_id,
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
