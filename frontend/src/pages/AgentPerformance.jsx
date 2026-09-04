import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import MetricCard from '../components/MetricCard'
import { fetchCreatorEarnings } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

function useCalls(t) {
  return [
    { id: 'call-1', task: t('agentPerformance.calls.csScript'), employer: t('agentPerformance.calls.ecommercePlatform'), ago: t('agentPerformance.calls.hoursAgo', { hours: 2 }), amount: '$60' },
    { id: 'call-2', task: t('agentPerformance.calls.salesAnalysis'), employer: t('agentPerformance.calls.retailCompany'), ago: t('agentPerformance.calls.daysAgo', { days: 1 }), amount: '$45' },
  ]
}

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
  const { t } = useLang()
  const CALLS = useCalls(t)
  const [earnings, setEarnings] = useState(null)
  const [earnError, setEarnError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchCreatorEarnings()
      .then((data) => { if (!cancelled) setEarnings(data) })
      .catch((e) => { if (!cancelled) setEarnError(e.message || t('agentPerformance.errors.earningsFailed')) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          <SectionLabel>🤖 {t('agentPerformance.title')}</SectionLabel>
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

        {/* 4 metric cards */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 14,
          marginBottom: 28,
        }}>
          <MetricCard icon="📞" label={t('agentPerformance.metrics.totalCalls')} value={callCount} color="var(--text)" />
          <MetricCard icon="📅" label={t('agentPerformance.metrics.thisMonth')} value={callCount} color="var(--text)" />
          <MetricCard icon="🎯" label={t('agentPerformance.metrics.accuracy')} value="92%" color="var(--text)" />
          <MetricCard icon="💰" label={t('agentPerformance.metrics.total')} value={accruedLabel} color="var(--money)" />
        </div>

        {/* Recent calls */}
        <SectionLabel>📜 {t('agentPerformance.recentCalls')}</SectionLabel>
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
                  {t('agentPerformance.fromPrefix')} {c.employer} · {c.ago}
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

        {/* Earnings breakdown */}
        <SectionLabel>💰 {t('agentPerformance.earningsBreakdown')}</SectionLabel>
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
              label={t('agentPerformance.accrued')}
              value={accruedLabel}
              color="var(--warning-active)"
            />
            <SplitStat
              label={t('agentPerformance.settled')}
              value="—"
              color="var(--primary-active)"
            />
            <SplitStat
              label={t('agentPerformance.totalLabel')}
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
              {t('agentPerformance.errors.earningsFailedPrefix')}{earnError}
            </div>
          )}
          <div style={{
            textAlign: 'center',
            marginTop: 18,
          }}>
            <PixelButton
              variant="gold"
              onClick={() => alert(t('agentPerformance.withdrawSent'))}
            >
              💸 {t('agentPerformance.withdrawToWallet')}
            </PixelButton>
          </div>
        </div>

        {/* Back button */}
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <PixelButton variant="wood" onClick={() => navigate('/creator')}>
            ◂ {t('agentPerformance.backToWorkshop')}
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
