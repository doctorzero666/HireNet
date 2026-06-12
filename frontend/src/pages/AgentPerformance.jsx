import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import MetricCard from '../components/MetricCard'
import { fetchCreatorEarnings } from '../services/api'

const CALLS = [
  { id: 'call-1', task: '生成客服话术', employer: '电商平台', ago: '2h 前', amount: '$60' },
  { id: 'call-2', task: '分析销售数据', employer: '零售公司', ago: '1d 前', amount: '$45' },
]

/* Backend stores ledger amounts as integer basis points (USD cents).
   formatAmount turns 1234 → "$12.34" so the panel never claims $1234 by accident. */
function formatAmount(amountCents, currency) {
  if (amountCents == null) return '—'
  const value = amountCents / 100
  if (currency === 'USD') return `$${value.toFixed(2)}`
  return `${value.toFixed(2)} ${currency || ''}`.trim()
}

export default function AgentPerformance() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const [earnings, setEarnings] = useState(null)
  const [earnError, setEarnError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchCreatorEarnings()
      .then((data) => { if (!cancelled) setEarnings(data) })
      .catch((e) => { if (!cancelled) setEarnError(e.message || '收益加载失败') })
    return () => { cancelled = true }
  }, [])

  // Pick the top accrued bucket as the headline. The full breakdown is rendered
  // below it so multi-currency creators see all their buckets.
  const accruedRows = earnings?.totals_by_currency ?? []
  const headline = accruedRows[0]
  const accruedLabel = headline ? formatAmount(headline.amount, headline.currency) : '$0.00'
  const callCount = earnings?.call_count ?? 0

  return (
    <Scene>
      <Board maxWidth={800}>
        <NavBar role="creator" />

        <div style={{ marginTop: 8 }}>
          <SectionLabel>🤖 Agent 性能面板</SectionLabel>
        </div>

        <p style={{
          textAlign: 'center',
          fontSize: 12.5,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          marginTop: 10,
          marginBottom: 20,
        }}>
          Agent ID：<code>{agentId}</code>
        </p>

        {/* 4 指标卡片 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 14,
          marginBottom: 28,
        }}>
          <MetricCard icon="📞" label="总调用" value={callCount} color="var(--text)" />
          <MetricCard icon="📅" label="本月" value={callCount} color="var(--text)" />
          <MetricCard icon="🎯" label="准确率" value="92%" color="var(--text)" />
          <MetricCard icon="💰" label="累计" value={accruedLabel} color="var(--money)" />
        </div>

        {/* 最近调用记录 */}
        <SectionLabel>📜 最近调用记录</SectionLabel>
        <div style={{
          background: 'rgba(255, 255, 255, 0.6)',
          border: '1.5px solid var(--border-soft)',
          borderRadius: 20,
          padding: '8px 20px',
          boxShadow: 'var(--elev-sm)',
          marginTop: 12,
          marginBottom: 28,
        }}>
          {CALLS.map((c, i) => (
            <div
              key={c.id}
              style={{
                padding: '12px 0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 12,
                borderBottom: i < CALLS.length - 1 ? '1px dashed rgb(232, 220, 200)' : 'none',
              }}
            >
              <div>
                <div style={{
                  fontWeight: 800,
                  fontSize: 13.5,
                  color: 'var(--text)',
                }}>
                  📜 {c.task}
                </div>
                <div style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  marginTop: 2,
                }}>
                  来自 {c.employer} · {c.ago}
                </div>
              </div>
              <div style={{
                fontSize: 15,
                fontWeight: 900,
                color: 'var(--money)',
                fontVariantNumeric: 'tabular-nums',
              }}>
                {c.amount}
              </div>
            </div>
          ))}
        </div>

        {/* 收益明细 */}
        <SectionLabel>💰 收益明细</SectionLabel>
        <div style={{
          background: 'var(--primary-bg)',
          border: '1.5px solid #b8ece6',
          borderRadius: 20,
          padding: '20px 24px',
          marginTop: 12,
          marginBottom: 28,
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-around',
            flexWrap: 'wrap',
            gap: 16,
          }}>
            <SplitStat
              label="已计提 (accrued)"
              value={accruedLabel}
              color="var(--warning-active)"
            />
            <SplitStat
              label="已结算 (settled)"
              value="—"
              color="var(--primary-active)"
            />
            <SplitStat
              label="累计 (total)"
              value={accruedLabel}
              color="var(--money)"
            />
          </div>

          {accruedRows.length > 1 && (
            <div style={{
              marginTop: 14,
              padding: '12px 14px',
              borderTop: '1px dashed rgba(0,0,0,0.08)',
              fontSize: 12,
              fontWeight: 700,
              color: 'var(--text-body)',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}>
              {accruedRows.map((row, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{row.currency}{row.chain ? ` @ ${row.chain}` : ''}</span>
                  <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--money)' }}>
                    {formatAmount(row.amount, row.currency)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {earnError && (
            <div style={{
              marginTop: 12,
              fontSize: 12,
              fontWeight: 700,
              color: 'var(--warning-active)',
              textAlign: 'center',
            }}>
              收益数据加载失败：{earnError}
            </div>
          )}
          <div style={{
            textAlign: 'center',
            marginTop: 18,
          }}>
            <PixelButton
              variant="gold"
              onClick={() => alert('💸 提现请求已发送到 Cobo 钱包')}
            >
              💸 提现到 Cobo 钱包
            </PixelButton>
          </div>
        </div>

        {/* 返回按钮 */}
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <PixelButton variant="wood" onClick={() => navigate('/creator')}>
            ◂ 返回工坊
          </PixelButton>
        </div>
      </Board>
    </Scene>
  )
}

function SplitStat({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 120 }}>
      <div style={{
        fontSize: 23,
        fontWeight: 900,
        color,
        fontVariantNumeric: 'tabular-nums',
      }}>
        {value}
      </div>
      <div style={{
        fontSize: 11,
        fontWeight: 700,
        color: 'var(--text-secondary)',
        marginTop: 4,
      }}>
        {label}
      </div>
    </div>
  )
}
