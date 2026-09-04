import { useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import { settleRoyalty } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

function demoExecution(t) {
  return {
    taskId: 'task-001',
    taskName: t('executionPage.demo.taskName'),
    agentName: t('executionPage.demo.agentName'),
    creator: t('executionPage.demo.creator'),
    hours: 1.8,
    total: 54,
    creatorShare: 37.8,
    platformShare: 10.8,
    tax: 5.4,
    txHash: null,
    royaltyId: 'RL-2026-0608-0042',
    mcpResult: null,
  }
}

// royalty_splits amounts come from the backend as integer cents (basis points);
// the UI talks in whole-dollar floats, so divide by 100. Falls back to 0 when
// the split is missing — keeps the page render-safe for partial responses.
function centsToDollars(v) {
  return typeof v === 'number' ? v / 100 : 0
}

function buildExecution(taskId, data, demo) {
  if (!data) return demo
  const splits = data.royalty_splits || {}
  return {
    taskId: taskId || data.task_id || demo.taskId,
    taskName: data.task_name || data.task_id || demo.taskName,
    agentName: data.agent_name || demo.agentName,
    creator: data.creator || demo.creator,
    hours: data.hours || demo.hours,
    total: data.amount != null ? Number(data.amount) : demo.total,
    creatorShare: centsToDollars(splits.creator?.amount),
    platformShare: centsToDollars(splits.platform?.amount),
    tax: centsToDollars(splits.tax?.amount),
    txHash: data.tx_hash || null,
    royaltyId: data.run_id || demo.royaltyId,
    mcpResult: data.mcp_result || null,
  }
}

export default function ExecutionPage() {
  const { taskId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { t } = useLang()
  const settlement = location.state?.settlement || null
  const execution = buildExecution(taskId, settlement, demoExecution(t))
  const [accepted, setAccepted] = useState(false)
  /* settledTxHash overrides execution.txHash after the user clicks Accept. The
     modal path already populates execution.txHash via navigate state; the
     verify button is the only way to surface a tx_hash for runs that came in
     without one (preset records, page refresh). */
  const [settledTxHash, setSettledTxHash] = useState(null)

  async function handleAccept() {
    /* Idempotent: backend /royalty/settle short-circuits when the run is
       already settled and returns the existing tx_hash. So the modal-path
       caller gets the same tx_hash back; the preset-data caller gets the
       newly minted one. Errors are swallowed — Accept is UX confirmation, not
       a blocking gate. */
    if (execution.royaltyId) {
      try {
        const res = await settleRoyalty(execution.royaltyId)
        if (res?.tx_hash && !execution.txHash) {
          setSettledTxHash(res.tx_hash)
        }
      } catch { /* silent — see comment above */ }
    }
    setAccepted(true)
  }

  const effectiveTxHash = execution.txHash || settledTxHash
  const renderedExecution = effectiveTxHash === execution.txHash
    ? execution
    : { ...execution, txHash: effectiveTxHash }

  return (
    <Scene>
      <Board maxWidth={820}>
        <NavBar role="employer" />

        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <SectionLabel>🎉 {t('executionPage.taskComplete')}</SectionLabel>
        </div>

        <ResultView
          execution={renderedExecution}
          accepted={accepted}
          onAccept={handleAccept}
          onRetry={() => navigate('/employer')}
        />

        <div style={{ textAlign: 'center', marginTop: 16, fontSize: 12.5, fontWeight: 600, color: 'var(--text-secondary)' }}>
          Task: <code>{execution.taskId}</code>
        </div>
      </Board>
    </Scene>
  )
}

function McpOutputBlock({ mcpResult }) {
  const { t } = useLang()
  if (!mcpResult) {
    return (
      <div
        style={{
          background: 'rgba(255, 255, 255, 0.6)',
          border: '1.5px dashed var(--border-soft)',
          borderRadius: 'var(--r)',
          padding: '14px 18px',
          marginBottom: 16,
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          textAlign: 'center',
        }}
      >
        ⓘ {t('executionPage.mcp.notConnected')}
      </div>
    )
  }

  if (mcpResult.status === 'error') {
    return (
      <div
        style={{
          background: '#fbe7e2',
          border: '1.5px solid #f0c2b7',
          borderRadius: 'var(--r)',
          padding: '14px 18px',
          marginBottom: 16,
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--danger-active, #c1432b)',
        }}
      >
        <div style={{ fontWeight: 800, marginBottom: 6 }}>
          ⚠️ {t('executionPage.mcp.callFailed')}
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>
          tool: <code>{mcpResult.tool || '?'}</code>
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 4 }}>
          {mcpResult.error || t('executionPage.mcp.unknownError')}
        </div>
      </div>
    )
  }

  const preview = Array.isArray(mcpResult.preview) ? mcpResult.preview : []
  const total = typeof mcpResult.total === 'number' ? mcpResult.total : preview.length

  return (
    <div
      style={{
        background: 'rgba(255, 255, 255, 0.6)',
        border: '1.5px solid var(--border-soft)',
        borderRadius: 'var(--r)',
        padding: '16px 20px',
        marginBottom: 16,
        fontSize: 13.5,
        fontWeight: 500,
        color: 'var(--text-body)',
        boxShadow: 'var(--elev-sm)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 10,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <div style={{ fontWeight: 800, fontSize: 15, color: 'var(--text)' }}>
          📜 {t('executionPage.mcp.outputPreview')}
        </div>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)' }}>
          tool: <code>{mcpResult.tool}</code> · {t('executionPage.mcp.totalCount', { count: total })}
        </div>
      </div>
      <ol
        style={{
          margin: 0,
          paddingLeft: 22,
          lineHeight: 1.75,
          fontWeight: 600,
        }}
      >
        {preview.map((item, i) => (
          <li key={i} style={{ marginBottom: 4 }}>
            {item}
          </li>
        ))}
      </ol>
      {total > preview.length && (
        <div style={{ fontSize: 11.5, color: 'var(--text-disabled)', fontWeight: 600, marginTop: 8 }}>
          {t('executionPage.mcp.showingFirst', { shown: preview.length, total })}
        </div>
      )}
    </div>
  )
}

function ResultView({ execution, accepted, onAccept, onRetry }) {
  const { t } = useLang()
  const e = execution
  const txShort = e.txHash && e.txHash.length > 12
    ? `${e.txHash.slice(0, 6)}...${e.txHash.slice(-4)}`
    : e.txHash
  return (
    <div style={{ padding: '8px 6px' }}>
      {/* Big checkmark + title */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div
          style={{
            fontSize: 64,
            lineHeight: 1,
            color: 'var(--success)',
          }}
        >
          ✅
        </div>
        <div
          style={{
            fontSize: 19,
            fontWeight: 800,
            color: 'var(--success-active)',
            marginTop: 8,
          }}
        >
          {t('executionPage.taskComplete')}
        </div>
      </div>

      {/* Agent info card */}
      <div
        style={{
          background: 'rgba(255, 255, 255, 0.6)',
          border: '1.5px solid var(--border-soft)',
          borderRadius: 20,
          padding: '18px 24px',
          marginBottom: 16,
          fontSize: 13.5,
          fontWeight: 500,
          color: 'var(--text-body)',
          boxShadow: 'var(--elev-sm)',
        }}
      >
        <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 6, color: 'var(--text)' }}>
          🤖 {e.agentName} <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>({e.creator})</span>
        </div>
        <div style={{ marginBottom: 4, fontWeight: 600 }}>
          ⏱️ {t('executionPage.timeSpent', { hours: e.hours })} · <span style={{ color: 'var(--money)', fontWeight: 800 }}>💰 {t('executionPage.cost', { amount: e.total })}</span>
        </div>
      </div>

      {/* MCP output (replaces the old fake progress bar / fake output count) */}
      <McpOutputBlock mcpResult={e.mcpResult} />

      {/* Cost breakdown */}
      <div
        style={{
          background: 'rgba(255, 255, 255, 0.55)',
          border: '1px dashed rgb(220, 206, 180)',
          borderRadius: 'var(--r)',
          padding: '16px 20px',
          marginBottom: 20,
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--text-body)',
        }}
      >
        <div style={{ fontWeight: 800, marginBottom: 10, color: 'var(--text)' }}>💰 {t('executionPage.costBreakdown')}</div>
        <div style={{ lineHeight: 1.8 }}>
          ${e.total} → <strong style={{ color: 'var(--money)', fontWeight: 900 }}>${e.creatorShare}</strong> {t('executionPage.creatorLabel')} ({e.creator}) +{' '}
          <strong style={{ color: 'var(--money)', fontWeight: 900 }}>${e.platformShare}</strong> {t('executionPage.platformLabel')} + <strong style={{ color: 'var(--money)', fontWeight: 900 }}>${e.tax}</strong> {t('executionPage.taxLabel')}
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--text-disabled)',
            marginTop: 8,
            fontWeight: 600,
          }}
        >
          {t('executionPage.royaltyRecord')}：<code>#{e.royaltyId}</code>
        </div>
      </div>

      {/* On-chain tx_hash card — only shown when there's a real tx_hash.
          Sepolia testnet has a public explorer; clicking jumps straight to
          Etherscan to see the receipt / value / input data. */}
      {e.txHash && (
        <div
          style={{
            background: '#e9f4dd',
            border: '1.5px solid var(--success, #6fbf3d)',
            borderRadius: 'var(--r)',
            padding: '14px 18px',
            marginBottom: 20,
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--text-body)',
          }}
        >
          <div style={{ fontWeight: 800, marginBottom: 6, color: 'var(--success-active)' }}>
            🔗 {t('executionPage.onChain')}
          </div>
          <div style={{ marginBottom: 8 }}>
            <code style={{ fontSize: 12.5 }}>{txShort}</code>
          </div>
          <a
            href={`https://sepolia.etherscan.io/tx/${e.txHash}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: 12.5,
              fontWeight: 800,
              color: 'var(--success-active)',
              textDecoration: 'none',
              borderBottom: '1.5px dashed var(--success-active)',
            }}
          >
            {t('executionPage.viewOnEtherscan')} →
          </a>
        </div>
      )}

      {/* Accepted confirmation */}
      {accepted && (
        <div
          style={{
            background: '#e9f4dd',
            border: '1.5px solid #cde6b2',
            borderRadius: 'var(--pill)',
            padding: '9px 22px',
            textAlign: 'center',
            fontWeight: 800,
            fontSize: 13.5,
            color: 'var(--success-active)',
            marginBottom: 16,
            maxWidth: 340,
            marginLeft: 'auto',
            marginRight: 'auto',
          }}
        >
          ✅ {t('executionPage.acceptedSettled')}
        </div>
      )}

      {/* Button row */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          flexWrap: 'wrap',
          justifyContent: 'center',
        }}
      >
        <PixelButton variant="gold" onClick={() => alert(t('executionPage.downloading'))}>
          📥 {t('executionPage.downloadScript')}
        </PixelButton>
        <PixelButton variant="wood" onClick={() => alert(t('executionPage.openingPreview'))}>
          👀 {t('executionPage.preview')}
        </PixelButton>
        <PixelButton variant="gold" onClick={onAccept} disabled={accepted}>
          {accepted ? `✅ ${t('executionPage.accepted')}` : `✅ ${t('executionPage.acceptConfirm')}`}
        </PixelButton>
        <PixelButton variant="wood" onClick={onRetry}>
          🔄 {t('executionPage.addAnotherTask')}
        </PixelButton>
      </div>
    </div>
  )
}
