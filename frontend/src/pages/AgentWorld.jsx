import { useEffect, useState } from 'react'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import { fetchSkillsList } from '../services/api'

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
  const mcpOn = !!skill.mcp_endpoint
  return (
    <div className="agent-card">
      <div className="agent-card__head">
        <div>
          <div className="agent-card__name">🤖 {skill.name}</div>
          <div className="agent-card__creator">
            创作者 · {skill.creator_name || skill.creator_id}
          </div>
        </div>
        <span className={`agent-badge ${mcpOn ? 'agent-badge--mcp-on' : 'agent-badge--mcp-off'}`}>
          {mcpOn ? '🔗 MCP已连接' : '📋 待接入MCP'}
        </span>
      </div>
      <div className="agent-card__desc" title={skill.description}>
        {skill.description}
      </div>
      <div className="agent-card__meta">
        <span>📞 {skill.call_count ?? 0} 次调用</span>
        <span className="agent-card__price">
          💰 {formatHourlyRate(skill.price_amount, skill.price_currency)}
        </span>
      </div>
    </div>
  )
}

export default function AgentWorld() {
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
          <Ribbon color="app-teal" size={22}>🤖 Agent 世界</Ribbon>
        </div>

        <p className="agent-world-intro">
          创作者注册的 AI Agent。每个 Agent 都可以被企业调用，自动完成工作并获得版税收益。
        </p>

        {loading && <div className="agent-loading">⌛ 正在召集岛民…</div>}

        {!loading && error && (
          <div className="agent-empty">
            <span className="agent-empty__icon">🪨</span>
            加载失败：{error}
          </div>
        )}

        {!loading && !error && skills.length === 0 && (
          <div className="agent-empty">
            <span className="agent-empty__icon">🏝️</span>
            还没有 Agent，去创作者端注册第一个吧
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
