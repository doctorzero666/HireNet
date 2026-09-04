import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import MetricCard from '../components/MetricCard'
import { useLang } from '../i18n/LanguageProvider'

function useAgents(t) {
  return [
    { name: t('employerDashboard.agents.csScript.name'), creator: t('employerDashboard.agents.csScript.creator'), calls: 12, accuracy: '92%', online: true },
    { name: t('employerDashboard.agents.dataAnalyst.name'), creator: t('employerDashboard.agents.dataAnalyst.creator'), calls: 8, accuracy: '88%', online: true },
    { name: t('employerDashboard.agents.codeReview.name'), creator: t('employerDashboard.agents.codeReview.creator'), calls: 5, accuracy: '95%', online: false },
  ]
}

function useWarnings(t) {
  return [
    t('employerDashboard.warnings.csScriptDrop'),
    t('employerDashboard.warnings.dataAnalystAccuracy'),
  ]
}

export default function EmployerDashboard() {
  const navigate = useNavigate()
  const { t } = useLang()
  const AGENTS = useAgents(t)
  const WARNINGS = useWarnings(t)

  return (
    <Scene>
      <Board maxWidth={920}>
        <NavBar role="employer" />

        <div style={{ marginTop: 8 }}>
          <SectionLabel>🏰 {t('employerDashboard.title')}</SectionLabel>
        </div>

        {/* 4 metric cards */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 14,
          marginTop: 14,
          marginBottom: 28,
        }}>
          <MetricCard icon="💰" label={t('employerDashboard.metrics.spend')} value="$1,240" color="var(--money)" />
          <MetricCard icon="🤖" label={t('employerDashboard.metrics.activeAgents')} value="3" color="var(--text)" />
          <MetricCard icon="✅" label={t('employerDashboard.metrics.completionRate')} value="85%" color="var(--text)" />
          <MetricCard icon="⏱️" label={t('employerDashboard.metrics.hoursSaved')} value="120h" color="var(--text)" />
        </div>

        {/* Agent list */}
        <SectionLabel>🤖 {t('employerDashboard.agentsTitle')}</SectionLabel>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          marginTop: 12,
          marginBottom: 28,
        }}>
          {AGENTS.map((a) => (
            <div
              key={a.name}
              style={{
                background: 'rgba(255, 255, 255, 0.6)',
                border: '1.5px solid var(--border-soft)',
                borderRadius: 20,
                padding: '14px 18px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 12,
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'translateY(-2px)'
                e.currentTarget.style.boxShadow = 'var(--elev-base)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translateY(0)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              <div>
                <div style={{
                  fontWeight: 800,
                  fontSize: 14,
                  color: 'var(--text)',
                  whiteSpace: 'nowrap',
                }}>
                  🤖 {a.name}
                </div>
                <div style={{
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  marginTop: 1,
                }}>
                  {a.creator}
                </div>
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontSize: 13,
                color: 'var(--text-body)',
                fontWeight: 600,
              }}>
                <span>📞 {t('employerDashboard.callsCount', { count: a.calls })}</span>
                <span style={{ color: 'var(--text-disabled)' }}>·</span>
                <span>🎯 {a.accuracy}</span>
                <span style={{ color: 'var(--text-disabled)' }}>·</span>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 7,
                    padding: '3px 12px',
                    borderRadius: 'var(--pill)',
                    fontSize: 11.5,
                    fontWeight: 800,
                    color: a.online ? 'var(--success-active)' : 'var(--text-secondary)',
                    background: a.online ? '#e9f4dd' : 'var(--bg-secondary)',
                  }}
                >
                  {a.online ? `● ${t('employerDashboard.online')}` : `○ ${t('employerDashboard.offline')}`}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Warnings */}
        <SectionLabel>⚠️ {t('employerDashboard.warningsTitle')}</SectionLabel>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          marginTop: 12,
          marginBottom: 28,
        }}>
          {WARNINGS.map((w, i) => (
            <div
              key={i}
              style={{
                background: 'rgba(255, 255, 255, 0.6)',
                border: '1.5px solid var(--border-soft)',
                borderLeft: '6px solid var(--warning)',
                borderRadius: 20,
                padding: '14px 18px',
                fontSize: 13.5,
                fontWeight: 800,
                color: 'var(--text)',
              }}
            >
              ⚠️ {w}
            </div>
          ))}
        </div>

        {/* Back button */}
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <PixelButton variant="wood" onClick={() => navigate('/employer/hub')}>
            ◂ {t('employerDashboard.backToHub')}
          </PixelButton>
        </div>
      </Board>
    </Scene>
  )
}
