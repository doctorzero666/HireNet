import { useEffect, useState } from 'react'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import { fetchSkillsList } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

function formatHourlyRate(amountBasisPoints, currency) {
  /* price_amount is USD basis points (1 USD = 100 bp). Frontend only supports
     USD display today — non-USD just renders the raw value with the code so
     it's still legible if the backend grows other currencies. */
  if (typeof amountBasisPoints !== 'number') return '—'
  const value = amountBasisPoints / 100
  if (currency === 'USD') return `$${value.toFixed(0)}/h`
  return `${value.toFixed(2)} ${currency || ''}/h`.trim()
}

function AgentCard({ skill }) {
  const { t } = useLang()
  const mcpOn = !!skill.mcp_endpoint
  return (
    <div className="agent-card">
      <div className="agent-card__head">
        <div>
          <div className="agent-card__name">🤖 {skill.name}</div>
          <div className="agent-card__creator">
            {t('agentWorld.creatorPrefix')} · {skill.creator_name || skill.creator_id}
          </div>
        </div>
        <span className={`agent-badge ${mcpOn ? 'agent-badge--mcp-on' : 'agent-badge--mcp-off'}`}>
          {mcpOn ? `🔗 ${t('agentWorld.mcpConnected')}` : `📋 ${t('agentWorld.mcpPending')}`}
        </span>
      </div>
      <div className="agent-card__desc" title={skill.description}>
        {skill.description}
      </div>
      <div className="agent-card__meta">
        <span>📞 {t('agentWorld.callCount', { count: skill.call_count ?? 0 })}</span>
        <span className="agent-card__price">
          💰 {formatHourlyRate(skill.price_amount, skill.price_currency)}
        </span>
      </div>
    </div>
  )
}

export default function AgentWorld() {
  const { t } = useLang()
  const [skills, setSkills] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchSkillsList()
      .then((data) => {
        if (cancelled) return
        setSkills(Array.isArray(data?.skills) ? data.skills : [])
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'load failed')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  return (
    <Scene>
      <Board maxWidth={960}>
        <NavBar role="agent-world" />

        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Ribbon color="app-teal" size={22}>🤖 {t('agentWorld.title')}</Ribbon>
        </div>

        <p className="agent-world-intro">
          {t('agentWorld.intro')}
        </p>

        {loading && <div className="agent-loading">⌛ {t('agentWorld.loading')}</div>}

        {!loading && error && (
          <div className="agent-empty">
            <span className="agent-empty__icon">🪨</span>
            {t('agentWorld.loadFailedPrefix')}{error}
          </div>
        )}

        {!loading && !error && skills.length === 0 && (
          <div className="agent-empty">
            <span className="agent-empty__icon">🏝️</span>
            {t('agentWorld.empty')}
          </div>
        )}

        {!loading && !error && skills.length > 0 && (
          <div className="agent-grid">
            {skills.map((s) => <AgentCard key={s.id} skill={s} />)}
          </div>
        )}
      </Board>
    </Scene>
  )
}
