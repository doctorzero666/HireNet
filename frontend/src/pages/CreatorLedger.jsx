import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import MetricCard from '../components/MetricCard'
import PixelButton from '../components/PixelButton'
import { fetchCreatorEarnings, fetchCreatorLedger } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

/* Backend stores ledger amounts as integer basis points (USD cents).
   formatAmount turns 1234 → "$12.34" — same convention as AgentPerformance. */
function formatAmount(amountCents, currency) {
  if (amountCents == null) return '$0.00'
  const value = amountCents / 100
  if (currency === 'USD') return `$${value.toFixed(2)}`
  return `${value.toFixed(2)} ${currency || ''}`.trim()
}

function sumBuckets(buckets) {
  /* Headline display picks the first (currency, chain) bucket; the rest are
     rendered as secondary lines below so multi-currency creators still see
     their full breakdown. */
  if (!buckets || buckets.length === 0) return { display: '$0.00', extras: [] }
  const head = buckets[0]
  return {
    display: formatAmount(head.amount, head.currency),
    extras: buckets.slice(1),
  }
}

function formatTime(iso, t) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const now = new Date()
  const diffMs = now - d
  const min = Math.floor(diffMs / 60000)
  if (min < 1) return t('creatorLedger.time.justNow')
  if (min < 60) return t('creatorLedger.time.minutesAgo', { n: min })
  const hr = Math.floor(min / 60)
  if (hr < 24) return t('creatorLedger.time.hoursAgo', { n: hr })
  const day = Math.floor(hr / 24)
  if (day < 30) return t('creatorLedger.time.daysAgo', { n: day })
  return d.toLocaleDateString()
}

function shortHash(h) {
  if (!h) return null
  if (h.length <= 14) return h
  return `${h.slice(0, 8)}…${h.slice(-4)}`
}

export default function CreatorLedger() {
  const navigate = useNavigate()
  const { t } = useLang()
  const [ledger, setLedger] = useState(null)
  const [earnings, setEarnings] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchCreatorLedger(), fetchCreatorEarnings()])
      .then(([l, e]) => {
        if (cancelled) return
        setLedger(l)
        setEarnings(e)
      })
      .catch((e) => { if (!cancelled) setError(e.message || t('creatorLedger.errors.loadFailed')) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const entries = ledger?.entries ?? []
  const callCount = earnings?.call_count ?? entries.length

  /* Accrued totals from /earnings still drive the headline because they
     filter for status='accrued' explicitly. /ledger also returns
     accrued_totals + settled_totals so the "Settled" card has its own bucket
     instead of guessing from the per-entry sum. */
  const accrued = sumBuckets(earnings?.totals_by_currency ?? ledger?.accrued_totals)
  const settled = sumBuckets(ledger?.settled_totals)
  const totalCalls = callCount

  // total = accrued + settled by (currency, chain). We sum on first bucket only
  // because that's what the headline reads; secondary buckets render under it.
  const totalDisplay = (() => {
    const accAmt = earnings?.totals_by_currency?.[0]?.amount ?? 0
    const setAmt = ledger?.settled_totals?.[0]?.amount ?? 0
    const ccy = earnings?.totals_by_currency?.[0]?.currency
      || ledger?.settled_totals?.[0]?.currency
      || 'USD'
    return formatAmount(accAmt + setAmt, ccy)
  })()

  return (
    <Scene>
      <Board maxWidth={860}>
        <NavBar role="creator" />

        <div style={{ textAlign: 'center', margin: '6px 0 20px' }}>
          <Ribbon color="app-yellow" size={20}>💰 {t('creatorLedger.title')}</Ribbon>
        </div>

        {/* 4 metric cards */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 14,
          marginBottom: 24,
        }}>
          <MetricCard icon="📞" label={t('creatorLedger.metrics.totalCalls')} value={totalCalls} color="var(--text)" />
          <MetricCard icon="💰" label={t('creatorLedger.metrics.totalEarnings')} value={totalDisplay} color="var(--money)" />
          <MetricCard icon="✅" label={t('creatorLedger.metrics.settled')} value={settled.display} color="var(--primary-active)" />
          <MetricCard icon="⏳" label={t('creatorLedger.metrics.pending')} value={accrued.display} color="var(--warning-active)" />
        </div>

        {/* Multi-currency footnote (when there's more than one bucket) */}
        {(accrued.extras.length > 0 || settled.extras.length > 0) && (
          <div style={{
            background: 'rgba(255, 255, 255, 0.5)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 16,
            padding: '10px 16px',
            marginBottom: 20,
            fontSize: 12,
            fontWeight: 700,
            color: 'var(--text-body)',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}>
            {accrued.extras.map((b, i) => (
              <div key={`acc-${i}`} style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>{t('creatorLedger.metrics.pending')} · {b.currency}{b.chain ? ` @ ${b.chain}` : ''}</span>
                <span style={{ color: 'var(--warning-active)' }}>{formatAmount(b.amount, b.currency)}</span>
              </div>
            ))}
            {settled.extras.map((b, i) => (
              <div key={`set-${i}`} style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>{t('creatorLedger.metrics.settled')} · {b.currency}{b.chain ? ` @ ${b.chain}` : ''}</span>
                <span style={{ color: 'var(--primary-active)' }}>{formatAmount(b.amount, b.currency)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Call ledger list */}
        <div style={{
          background: '#f7f3df',
          border: '1.5px solid var(--border-soft)',
          borderRadius: 20,
          padding: '14px 22px',
          boxShadow: 'var(--elev-sm)',
          marginBottom: 24,
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 13.5,
            fontWeight: 800,
            color: 'var(--text)',
            padding: '6px 0 12px',
            borderBottom: '1px dashed rgb(232, 220, 200)',
          }}>
            📋 {t('creatorLedger.callLog')}
            <span style={{
              fontSize: 11,
              fontWeight: 700,
              color: 'var(--text-secondary)',
              marginLeft: 'auto',
            }}>
              {t('creatorLedger.entryCount', { count: entries.length })}
            </span>
          </div>

          {error && (
            <div style={{
              padding: '18px 0',
              fontSize: 12.5,
              fontWeight: 700,
              color: 'var(--warning-active)',
              textAlign: 'center',
            }}>
              {t('creatorLedger.errors.loadFailedPrefix')}{error}
            </div>
          )}

          {!error && ledger && entries.length === 0 && (
            <div style={{
              padding: '36px 0',
              textAlign: 'center',
              fontSize: 14,
              fontWeight: 700,
              color: 'var(--text-secondary)',
            }}>
              🏝️ {t('creatorLedger.empty.title')}
              <div style={{
                marginTop: 6,
                fontSize: 11.5,
                fontWeight: 600,
                color: 'var(--text-muted)',
              }}>
                {t('creatorLedger.empty.subtitle')}
              </div>
            </div>
          )}

          {entries.map((e, i) => (
            <LedgerRow key={e.run_id} entry={e} isLast={i === entries.length - 1} t={t} />
          ))}
        </div>

        <div style={{ textAlign: 'center', marginTop: 6 }}>
          <PixelButton variant="wood" onClick={() => navigate('/creator')}>
            ◂ {t('agentPerformance.backToWorkshop')}
          </PixelButton>
        </div>
      </Board>
    </Scene>
  )
}

function LedgerRow({ entry, isLast, t }) {
  const status = entry.status
  const isSettled = status === 'settled'
  const txShort = shortHash(entry.tx_hash)

  return (
    <div style={{
      padding: '14px 0',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: 12,
      borderBottom: isLast ? 'none' : '1px dashed rgb(232, 220, 200)',
    }}>
      <div style={{ minWidth: 0, flex: '1 1 60%' }}>
        <div style={{
          fontWeight: 800,
          fontSize: 13.5,
          color: 'var(--text)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          flexWrap: 'wrap',
        }}>
          🤖 {entry.agent_name || t('creatorLedger.unnamedAgent')}
          <span style={{
            fontSize: 11,
            fontWeight: 700,
            color: 'var(--text-secondary)',
          }}>
            · {t('agentPerformance.fromPrefix')} {entry.caller_name || entry.caller_id || t('creatorLedger.unknownEmployer')}
          </span>
        </div>
        <div style={{
          fontSize: 11.5,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          marginTop: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}>
          <span>🕐 {formatTime(entry.created_at, t)}</span>
          {txShort && (
            <span style={{
              fontFamily: 'monospace',
              fontSize: 10.5,
              padding: '2px 7px',
              borderRadius: 6,
              background: 'rgba(0,0,0,0.04)',
              border: '1px solid var(--border-soft)',
            }}>
              tx · {txShort}
            </span>
          )}
        </div>
      </div>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flex: '0 0 auto',
      }}>
        <span style={{
          fontSize: 10.5,
          fontWeight: 800,
          padding: '3px 10px',
          borderRadius: 'var(--pill)',
          color: isSettled ? 'var(--primary-active)' : 'var(--warning-active)',
          background: isSettled ? '#e9f4dd' : '#fdf3d7',
          border: `1px solid ${isSettled ? '#c8e4a6' : '#eddca2'}`,
        }}>
          {isSettled ? `✅ ${t('creatorLedger.metrics.settled')}` : `⏳ ${t('creatorLedger.metrics.pending')}`}
        </span>
        <span style={{
          fontSize: 15,
          fontWeight: 900,
          color: 'var(--money)',
          fontVariantNumeric: 'tabular-nums',
          minWidth: 70,
          textAlign: 'right',
        }}>
          {formatAmount(entry.amount, entry.currency)}
        </span>
      </div>
    </div>
  )
}
