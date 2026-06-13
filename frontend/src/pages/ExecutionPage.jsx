import { useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import { settleRoyalty } from '../services/api'

const DEMO_EXECUTION = {
  taskId: 'task-001',
  taskName: '生成客服话术',
  agentName: '客服话术生成器',
  creator: '@李四',
  hours: 1.8,
  total: 54,
  creatorShare: 37.8,
  platformShare: 10.8,
  tax: 5.4,
  txHash: null,
  royaltyId: 'RL-2026-0608-0042',
  mcpResult: null,
}

// royalty_splits amounts come from the backend as integer cents (basis points);
// the UI talks in whole-dollar floats, so divide by 100. Falls back to 0 when
// the split is missing — keeps the page render-safe for partial responses.
function centsToDollars(v) {
  return typeof v === 'number' ? v / 100 : 0
}

function buildExecution(taskId, data) {
  if (!data) return DEMO_EXECUTION
  const splits = data.royalty_splits || {}
  return {
    taskId: taskId || data.task_id || DEMO_EXECUTION.taskId,
    taskName: data.task_name || data.task_id || DEMO_EXECUTION.taskName,
    agentName: data.agent_name || DEMO_EXECUTION.agentName,
    creator: data.creator || DEMO_EXECUTION.creator,
    hours: data.hours || DEMO_EXECUTION.hours,
    total: data.amount != null ? Number(data.amount) : DEMO_EXECUTION.total,
    creatorShare: centsToDollars(splits.creator?.amount),
    platformShare: centsToDollars(splits.platform?.amount),
    tax: centsToDollars(splits.tax?.amount),
    txHash: data.tx_hash || null,
    royaltyId: data.run_id || DEMO_EXECUTION.royaltyId,
    mcpResult: data.mcp_result || null,
  }
}

export default function ExecutionPage() {
  const { taskId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const settlement = location.state?.settlement || null
  const execution = buildExecution(taskId, settlement)
  const [accepted, setAccepted] = useState(false)
  /* settledTxHash overrides execution.txHash after the user clicks 验收. The
     modal path already populates execution.txHash via navigate state; the
     verify button is the only way to surface a tx_hash for runs that came in
     without one (preset records, page refresh). */
  const [settledTxHash, setSettledTxHash] = useState(null)

  async function handleAccept() {
    /* Idempotent: backend /royalty/settle short-circuits when the run is
       already settled and returns the existing tx_hash. So the modal-path
       caller gets the same tx_hash back; the preset-data caller gets the
       newly minted one. Errors are swallowed — 验收 is UX confirmation, not
       a blocking gate. */
    if (execution.royaltyId) {
      try {
        const res = await settleRoyalty(execution.royaltyId)
        if (res?.tx_hash && !execution.txHash) {
          setSettledTxHash(res.tx_hash)
        }
      } catch (_) { /* silent — see comment above */ }
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
          <SectionLabel>🎉 任务完成</SectionLabel>
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
        ⓘ 该 Agent 未接入 MCP，无外部产出
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
          ⚠️ MCP 调用失败（结算不受影响）
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>
          tool: <code>{mcpResult.tool || '?'}</code>
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 4 }}>
          {mcpResult.error || '未知错误'}
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
          📜 Agent 产出预览
        </div>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)' }}>
          tool: <code>{mcpResult.tool}</code> · 共 {total} 条
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
          仅展示前 {preview.length} 条 · 完整产物 {total} 条
        </div>
      )}
    </div>
  )
}

function ResultView({ execution, accepted, onAccept, onRetry }) {
  const e = execution
  const txShort = e.txHash && e.txHash.length > 12
    ? `${e.txHash.slice(0, 6)}...${e.txHash.slice(-4)}`
    : e.txHash
  return (
    <div style={{ padding: '8px 6px' }}>
      {/* 大勾 + 标题 */}
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
          任务完成
        </div>
      </div>

      {/* Agent 信息卡 */}
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
          ⏱️ 耗时 {e.hours} 小时 · <span style={{ color: 'var(--money)', fontWeight: 800 }}>💰 费用 ${e.total}</span>
        </div>
      </div>

      {/* MCP 产出（替代原假进度条/假产物计数） */}
      <McpOutputBlock mcpResult={e.mcpResult} />

      {/* 费用拆分 */}
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
        <div style={{ fontWeight: 800, marginBottom: 10, color: 'var(--text)' }}>💰 费用明细</div>
        <div style={{ lineHeight: 1.8 }}>
          ${e.total} → <strong style={{ color: 'var(--money)', fontWeight: 900 }}>${e.creatorShare}</strong> 创作者 ({e.creator}) +{' '}
          <strong style={{ color: 'var(--money)', fontWeight: 900 }}>${e.platformShare}</strong> 平台 + <strong style={{ color: 'var(--money)', fontWeight: 900 }}>${e.tax}</strong> 税费
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--text-disabled)',
            marginTop: 8,
            fontWeight: 600,
          }}
        >
          版税记录：<code>#{e.royaltyId}</code>
        </div>
      </div>

      {/* 链上 tx_hash 卡 — 仅在有真实 tx_hash 时显示。Anvil 没在线
          浏览器，点击弹 alert 展示完整 hash（demo 验证用：把它喂给
          `cast receipt <hash>` 或本地 RPC 即可见 receipt）。 */}
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
            🔗 链上可查
          </div>
          <div style={{ marginBottom: 8 }}>
            <code style={{ fontSize: 12.5 }}>{txShort}</code>
          </div>
          <button
            type="button"
            onClick={() => alert(`完整 tx_hash:\n\n${e.txHash}\n\n在本地终端验证:\n  cast receipt ${e.txHash} --rpc-url http://localhost:8545`)}
            style={{
              fontSize: 12.5,
              fontWeight: 800,
              color: 'var(--success-active)',
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              borderBottom: '1.5px dashed var(--success-active)',
            }}
          >
            查看完整 tx_hash →
          </button>
        </div>
      )}

      {/* 验收提示 */}
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
          ✅ 已验收 — 结算完成
        </div>
      )}

      {/* 按钮行 */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          flexWrap: 'wrap',
          justifyContent: 'center',
        }}
      >
        <PixelButton variant="gold" onClick={() => alert('下载中...')}>
          📥 下载话术表
        </PixelButton>
        <PixelButton variant="wood" onClick={() => alert('打开预览...')}>
          👀 在线预览
        </PixelButton>
        <PixelButton variant="gold" onClick={onAccept} disabled={accepted}>
          {accepted ? '✅ 已验收' : '✅ 验收确认'}
        </PixelButton>
        <PixelButton variant="wood" onClick={onRetry}>
          🔄 追加任务
        </PixelButton>
      </div>
    </div>
  )
}
