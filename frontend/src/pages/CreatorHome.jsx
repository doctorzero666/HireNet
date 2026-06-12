import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import { fetchCreatorEarnings } from '../services/api'

const AGENTS = [
  { id: 'agent-1', name: '客服话术生成器', online: true },
  { id: 'agent-2', name: '数据分析助手', online: true },
]

function formatAmount(amountCents, currency) {
  if (amountCents == null) return '$0.00'
  const value = amountCents / 100
  if (currency === 'USD') return `$${value.toFixed(2)}`
  return `${value.toFixed(2)} ${currency || ''}`.trim()
}

export default function CreatorHome() {
  const navigate = useNavigate()
  const [earnings, setEarnings] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchCreatorEarnings()
      .then((data) => { if (!cancelled) setEarnings(data) })
      .catch(() => { /* silent: CreatorHome still renders without earnings */ })
    return () => { cancelled = true }
  }, [])

  // Real ledger data is keyed by (currency, chain), not per agent. Until a
  // per-asset breakdown exists, every card shows the same global totals — the
  // creator's actual accrued, not made-up numbers.
  const headline = earnings?.totals_by_currency?.[0]
  const earnedDisplay = headline ? formatAmount(headline.amount, headline.currency) : '$0.00'
  const callCount = earnings?.call_count ?? 0

  return (
    <Scene>
      <Board maxWidth={800}>
        <NavBar role="creator" />

        <div style={{ marginTop: 8 }}>
          <SectionLabel>⚒️ 创作者工坊</SectionLabel>
        </div>

        <p style={{
          textAlign: 'center',
          fontSize: 14,
          color: 'var(--text-muted)',
          fontWeight: 600,
          lineHeight: 1.65,
          marginTop: 12,
          marginBottom: 20,
        }}>
          管理你的 Agent，追踪每次调用与收益
        </p>

        {/* Agent 列表 */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          marginBottom: 28,
        }}>
          {AGENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => navigate(`/creator/agent/${a.id}`)}
              style={{
                textAlign: 'left',
                background: 'rgba(255, 255, 255, 0.6)',
                border: '1.5px solid var(--border-soft)',
                borderRadius: 20,
                padding: '18px 22px',
                cursor: 'pointer',
                boxShadow: 'var(--elev-sm)',
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'translateY(-2px)'
                e.currentTarget.style.boxShadow = 'var(--elev-base)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translateY(0)'
                e.currentTarget.style.boxShadow = 'var(--elev-sm)'
              }}
            >
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 12,
              }}>
                <div>
                  <div style={{
                    fontWeight: 800,
                    fontSize: 15,
                    color: 'var(--text)',
                  }}>
                    🤖 {a.name}
                  </div>
                  <div style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: 'var(--text-body)',
                    marginTop: 8,
                    display: 'flex',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: 4,
                  }}>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 7,
                      padding: '3px 12px',
                      borderRadius: 'var(--pill)',
                      fontSize: 11.5,
                      fontWeight: 800,
                      color: a.online ? 'var(--success-active)' : 'var(--text-secondary)',
                      background: a.online ? '#e9f4dd' : 'var(--bg-secondary)',
                      marginRight: 8,
                    }}>
                      {a.online ? '● 在线' : '○ 离线'}
                    </span>
                    📞 {callCount} 次调用 · <span style={{ color: 'var(--money)', fontWeight: 800 }}>💰 {earnedDisplay} 累计</span>
                  </div>
                </div>
                <span style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: 'var(--primary)',
                }}>
                  ▸
                </span>
              </div>
            </button>
          ))}
        </div>

        {/* 注册入口 */}
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          gap: 14,
          flexWrap: 'wrap',
          marginTop: 10,
        }}>
          <PixelButton variant="gold" onClick={() => navigate('/creator/register')}>
            ⚒️ 注册新 Agent
          </PixelButton>
          <PixelButton variant="wood" onClick={() => navigate('/')}>
            ◂ 返回角色选择
          </PixelButton>
        </div>
      </Board>
    </Scene>
  )
}
