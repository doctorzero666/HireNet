import { useEffect, useRef, useState } from 'react'
import PixelButton from './PixelButton'
import { createPact, approvePact, settlePact } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

/**
 * PactConfirmationModal — Pact authorization confirmation modal
 * props:
 *   agent: { name, creator, wallet, pricePerHour }
 *   task: { id, name, description, estimatedHours }
 *   onConfirm: (settlement) => void   // fired by the "Done" button once
 *                                     // settlement is complete, no longer
 *                                     // fired automatically when settle
 *                                     // returns (WP-E)
 *   onReject: () => void
 *   onClose: () => void
 */

/* Mandate display helpers — the backend's /api/pact/create response carries
   AP2-style fields (intent / payee / amount_cap / expires_at) rendered here.
   These fields only align on AP2's mandate vocabulary; there is no signature
   backing them (the pact section of app/app.py says so explicitly), so the
   UI must never say "signed" / "verified". */

/** Shorten a 0x address to 0x1234…abcd; show a non-address as-is; — for empty. */
function formatPayee(payee) {
  if (payee === null || payee === undefined || payee === '') return '—'
  const text = String(payee)
  if (/^0x[0-9a-fA-F]{12,}$/.test(text)) {
    return `${text.slice(0, 6)}…${text.slice(-4)}`
  }
  return text
}

/** ISO 8601 (UTC) → browser-local time; shown as-is if it doesn't parse. */
function formatLocalTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString()
}

/** amount_cap is in the same unit as amount (USD); the backend defaults it to amount. */
function formatCap(cap, currency) {
  if (cap === null || cap === undefined || cap === '') return '—'
  const n = Number(cap)
  const shown = Number.isFinite(n) ? n.toFixed(2) : String(cap)
  return `${shown} ${currency || 'USD'}`
}

function MandateRow({ label, children }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 12,
        marginBottom: 6,
      }}
    >
      <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: 12, flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ fontWeight: 700, textAlign: 'right', wordBreak: 'break-word' }}>
        {children}
      </span>
    </div>
  )
}
export default function PactConfirmationModal({ agent, task, onConfirm, onReject, onClose }) {
  const { t } = useLang()
  const [estimatedHours, setEstimatedHours] = useState(task?.estimatedHours ?? 2)
  const [showAdjust, setShowAdjust] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [stage, setStage] = useState('')
  const [dots, setDots] = useState('')
  const [error, setError] = useState('')
  /* mandate: the response body from /api/pact/create, carrying intent /
     payee / amount_cap / expires_at / content_hash. Only has a value after
     creation succeeds, so the mandate block doesn't render before "Confirm
     authorization" is clicked. */
  const [mandate, setMandate] = useState(null)
  /* settled: the response body from /api/pact/settle, used to show the tx
     hash (rendered as a link when explorer_url is present). */
  const [settled, setSettled] = useState(null)
  const intervalRef = useRef(null)
  const cancelledRef = useRef(false)

  const price = agent?.pricePerHour ?? 30
  const total = (price * estimatedHours).toFixed(2)
  const wallet = agent?.wallet ?? '0x0000...0000'
  const walletShort = wallet.length > 12
    ? `${wallet.slice(0, 6)}...${wallet.slice(-4)}`
    : wallet

  const handleConfirm = async () => {
    setError('')
    setWaiting(true)
    setStage(t('pactModal.stages.creating'))
    cancelledRef.current = false
    let i = 0
    intervalRef.current = setInterval(() => {
      i = (i + 1) % 4
      setDots('.'.repeat(i))
    }, 400)

    try {
      const pact = await createPact({
        task_id: task?.id || 'task-001',
        agent_name: agent?.name ?? t('pactModal.defaultAgentName'),
        creator_id: agent?.creator_id,
        /* asset_id (when provided by demo bootstrap) pins billing to zhang_ai's
           Agent instead of the JOB_DESIGN_ASSET_ID fallback. */
        asset_id: agent?.asset_id,
        amount: Number(total),
        currency: 'USD',
      })
      if (cancelledRef.current) return
      setMandate(pact)
      setStage(t('pactModal.stages.approving'))

      const approved = await approvePact(pact.pact_id)
      if (cancelledRef.current) return
      /* approve returns the full pact (with approved_by / approval_method
         added) — use it to overwrite the create-time snapshot, so the
         mandate block always shows current state. */
      if (approved?.pact_id) setMandate(approved)
      setStage(t('pactModal.stages.settling'))

      const settlement = await settlePact(pact.pact_id)
      if (cancelledRef.current) return
      setSettled(settlement)

      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      /* Stage 2 / WP-E: do NOT navigate here. onConfirm unmounts this modal,
         which used to happen the instant settle resolved — the mandate block
         and the on-chain tx link were on screen for a single frame. The modal
         now stays in its settled state and the user leaves via "Done" below. */
      setWaiting(false)
      setStage('')
    } catch (err) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      setWaiting(false)
      setStage('')
      setError(err?.message || t('pactModal.errors.requestFailed'))
    }
  }

  /* The "Done" button after settlement completes: does exactly what used to
     happen automatically the instant settle returned — hands the settlement
     result to the parent (AnalysisReport unmounts the modal and navigates to
     the execution page). The only difference is the user now clicks it, so
     the mandate block and on-chain tx link stay readable. */
  const handleDone = () => {
    onConfirm?.({
      ...settled,
      agent_name: agent?.name,
      creator: agent?.creator,
      hours: estimatedHours,
    })
  }

  // Closing the modal mid-flow must not navigate (user backed out) and must
  // not leak the dots interval onto an unmounted component. cancelledRef
  // suppresses the final onConfirm after an in-flight settle resolves.
  useEffect(() => {
    return () => {
      cancelledRef.current = true
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.35)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: 20,
        animation: 'animal-fade-in 0.25s ease',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--bg-content)',
          borderRadius: 'var(--r-lg)',
          maxWidth: 520,
          width: '100%',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '36px 34px 30px',
          boxShadow: 'var(--elev-lg)',
          animation: 'animal-zoom-in 0.3s ease',
        }}
      >
        {/* Title */}
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <div
            style={{
              display: 'inline-block',
              fontSize: 22,
              fontWeight: 800,
              color: 'var(--text-body)',
            }}
          >
            📜 {t('pactModal.title')}
          </div>
        </div>

        {/* Info card */}
        <div
          style={{
            background: 'rgba(255, 255, 255, 0.55)',
            border: '1px dashed rgb(220, 206, 180)',
            borderRadius: 'var(--r)',
            padding: '16px 18px',
            marginBottom: 16,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginBottom: 10,
              flexWrap: 'wrap',
            }}
          >
            <span
              style={{
                fontWeight: 800,
                fontSize: 16,
                color: 'var(--text)',
              }}
            >
              🤖 {agent?.name ?? t('pactModal.defaultAgentName')}
            </span>
            <span
              style={{
                fontSize: 12.5,
                fontWeight: 700,
                color: 'var(--primary-active)',
                background: 'var(--primary-bg)',
                border: '1.5px solid #b8ece6',
                borderRadius: 'var(--pill)',
                padding: '3px 11px',
              }}
            >
              {agent?.creator ?? t('pactModal.defaultCreator')}
            </span>
          </div>

          {task?.description && (
            <div
              style={{
                fontSize: 13.5,
                color: 'var(--text-body)',
                lineHeight: 1.65,
                fontWeight: 500,
                marginBottom: 12,
              }}
            >
              {task.description}
            </div>
          )}

          {/* Cost breakdown */}
          <div
            style={{
              background: 'var(--bg)',
              borderRadius: 'var(--r-sm)',
              padding: '12px 14px',
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--text-body)',
            }}
          >
            <div style={{ fontWeight: 800, marginBottom: 8, color: 'var(--text)' }}>💰 {t('pactModal.costBreakdown')}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: 12 }}>{t('pactModal.rate')}</span>
              <span style={{ fontWeight: 800 }}>{t('pactModal.rateValue', { price })}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: 12 }}>{t('pactModal.estimatedDuration')}</span>
              <span style={{ fontWeight: 800 }}>{t('pactModal.hoursValue', { hours: estimatedHours })}</span>
            </div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                borderTop: '1px dashed rgb(232, 220, 200)',
                marginTop: 8,
                paddingTop: 8,
                fontWeight: 800,
                color: 'var(--text)',
              }}
            >
              <span>{t('pactModal.totalCap')}</span>
              <span style={{ color: 'var(--money)', fontWeight: 900, fontSize: 15 }}>${total}</span>
            </div>
          </div>

          {showAdjust && (
            <div style={{ marginTop: 12, fontSize: 14 }}>
              <label style={{ marginRight: 10, color: 'var(--text)', fontWeight: 700, fontSize: 13 }}>
                {t('pactModal.adjustDuration')}
              </label>
              <input
                type="number"
                min="0.5"
                step="0.5"
                value={estimatedHours}
                onChange={(e) =>
                  setEstimatedHours(Math.max(0.5, Number(e.target.value) || 0.5))
                }
                style={{
                  width: 100,
                  height: 44,
                  padding: '0 18px',
                  border: '2.5px solid var(--border-light)',
                  borderRadius: 'var(--pill)',
                  fontFamily: 'var(--font)',
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--text-body)',
                  background: 'var(--bg-content)',
                  outline: 'none',
                  transition: 'all 0.25s var(--ease)',
                }}
              />
            </div>
          )}
        </div>

        {/* Payee */}
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--text-body)',
            marginBottom: 16,
            padding: '10px 16px',
            background: '#e9f4dd',
            borderRadius: 'var(--r)',
          }}
        >
          <span style={{ fontWeight: 800, color: 'var(--success-active)' }}>📬 {t('pactModal.payeeWallet')}</span>
          <code style={{ marginLeft: 8, fontSize: 12.5 }}>
            {walletShort}
          </code>
        </div>

        {/* Mandate — AP2-style fields returned by the backend. Only appears after creation succeeds. */}
        {mandate && (
          <div
            style={{
              background: 'var(--bg)',
              border: '1px dashed rgb(220, 206, 180)',
              borderRadius: 'var(--r)',
              padding: '14px 16px',
              marginBottom: 16,
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--text-body)',
            }}
          >
            <div style={{ fontWeight: 800, marginBottom: 8, color: 'var(--text)' }}>
              📜 {t('pactModal.mandate.title')}
            </div>

            <MandateRow label={t('pactModal.mandate.intent')}>{mandate.intent || '—'}</MandateRow>
            <MandateRow label={t('pactModal.mandate.payee')}>
              <code style={{ fontSize: 12.5 }}>{formatPayee(mandate.payee)}</code>
            </MandateRow>
            <MandateRow label={t('pactModal.mandate.amountCap')}>
              {formatCap(mandate.amount_cap, mandate.currency)}
            </MandateRow>
            <MandateRow label={t('pactModal.mandate.expiresAt')}>
              {formatLocalTime(mandate.expires_at)}
            </MandateRow>

            {/* On-chain tx hash once settlement completes. explorer_url comes
                from the backend on the x402 settlement path; when absent,
                only plain text is shown — never a fabricated link. */}
            {settled?.tx_hash && (
              <MandateRow label={t('pactModal.mandate.txHash')}>
                {settled.explorer_url ? (
                  <a
                    href={settled.explorer_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'var(--primary-active)', wordBreak: 'break-all' }}
                  >
                    <code style={{ fontSize: 12.5 }}>{settled.tx_hash}</code>
                  </a>
                ) : (
                  <code style={{ fontSize: 12.5, wordBreak: 'break-all' }}>
                    {settled.tx_hash}
                  </code>
                )}
              </MandateRow>
            )}
          </div>
        )}

        {/* Wallet confirmation section */}
        <div
          style={{
            border: '1px dashed rgb(220, 206, 180)',
            borderRadius: 'var(--r)',
            padding: '16px 18px',
            marginBottom: 20,
            background: 'rgba(255, 255, 255, 0.55)',
          }}
        >
          <div
            style={{
              fontWeight: 800,
              color: 'var(--text)',
              marginBottom: 10,
              fontSize: 13.5,
            }}
          >
            📱 {t('pactModal.wallet.confirmInWallet')}
          </div>

          {/* Wallet confirmation illustrative placeholder */}
          <div
            style={{
              height: 80,
              background: 'var(--bg)',
              border: '1px dashed var(--border-light)',
              borderRadius: 'var(--r-sm)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 12.5,
              color: 'var(--text-disabled)',
              fontWeight: 600,
              marginBottom: 12,
            }}
          >
            {t('pactModal.wallet.placeholder')}
          </div>

          <ol
            style={{
              margin: 0,
              paddingLeft: 20,
              fontSize: 12.5,
              fontWeight: 600,
              color: 'var(--text-body)',
              lineHeight: 1.8,
            }}
          >
            <li>{t('pactModal.wallet.step1')}</li>
            <li>{t('pactModal.wallet.step2')}</li>
            <li>{t('pactModal.wallet.step3')}</li>
          </ol>

          {waiting && (
            <div
              style={{
                marginTop: 12,
                fontSize: 13,
                fontWeight: 800,
                color: 'var(--primary-active)',
                textAlign: 'center',
              }}
            >
              {stage || t('pactModal.stages.waiting')}{dots}
            </div>
          )}

          {error && (
            <div
              style={{
                marginTop: 12,
                fontSize: 12.5,
                fontWeight: 700,
                color: 'var(--danger-active, #c1432b)',
                textAlign: 'center',
                padding: '8px 10px',
                background: '#fbe7e2',
                border: '1px solid #f0c2b7',
                borderRadius: 'var(--r-sm)',
              }}
            >
              ✕ {error}
            </div>
          )}
        </div>

        {/* Button row */}
        <div
          style={{
            display: 'flex',
            gap: 10,
            justifyContent: 'center',
            flexWrap: 'wrap',
          }}
        >
          {settled ? (
            /* Settlement is complete: authorize/adjust/reject no longer apply — one exit only. */
            <PixelButton variant="gold" onClick={handleDone}>
              ✓ {t('pactModal.buttons.done')}
            </PixelButton>
          ) : (
            <>
              <PixelButton variant="gold" onClick={handleConfirm} disabled={waiting}>
                ✓ {t('pactModal.buttons.confirmAuthorization')}
              </PixelButton>
              <PixelButton
                variant="wood"
                onClick={() => setShowAdjust((v) => !v)}
                disabled={waiting}
              >
                ⚙ {t('pactModal.buttons.adjustCap')}
              </PixelButton>
              <PixelButton variant="danger" onClick={onReject} disabled={waiting}>
                ✕ {t('pactModal.buttons.reject')}
              </PixelButton>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
