import { useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'

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
  output: { count: 120, presale: 40, afterSale: 50, complaint: 30 },
}

const STEPS = ['分析需求', '匹配 Agent', '生成话术', '完成']

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
    output: DEMO_EXECUTION.output,
  }
}

export default function ExecutionPage() {
  const { taskId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const settlement = location.state?.settlement || null
  const execution = buildExecution(taskId, settlement)
  const [stepIdx, setStepIdx] = useState(0)
  const [done, setDone] = useState(false)
  const [accepted, setAccepted] = useState(false)

  useEffect(() => {
    if (stepIdx >= STEPS.length - 1) {
      const t = setTimeout(() => setDone(true), 600)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setStepIdx((i) => i + 1), 1000)
    return () => clearTimeout(t)
  }, [stepIdx])

  return (
    <Scene>
      <Board maxWidth={820}>
        <NavBar role="employer" />

        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <SectionLabel>
            {done ? '🎉 任务完成' : '⚔️ 任务执行中'}
          </SectionLabel>
        </div>

        {!done ? (
          <ProgressView stepIdx={stepIdx} execution={execution} />
        ) : (
          <ResultView
            execution={execution}
            accepted={accepted}
            onAccept={() => setAccepted(true)}
            onRetry={() => navigate('/employer')}
          />
        )}

        <div style={{ textAlign: 'center', marginTop: 16, fontSize: 12.5, fontWeight: 600, color: 'var(--text-secondary)' }}>
          Task: <code>{execution.taskId}</code>
        </div>
      </Board>
    </Scene>
  )
}

function ProgressView({ stepIdx, execution }) {
  const progress = ((stepIdx + 1) / STEPS.length) * 100

  return (
    <div style={{ padding: '12px 8px' }}>
      <div
        style={{
          textAlign: 'center',
          fontSize: 22,
          fontWeight: 900,
          color: 'var(--text)',
          marginBottom: 8,
        }}
      >
        {execution.taskName}
      </div>
      <div
        style={{
          textAlign: 'center',
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          marginBottom: 20,
        }}
      >
        🤖 {execution.agentName} · {execution.creator}
      </div>

      {/* 进度条 */}
      <div
        style={{
          height: 18,
          background: 'var(--bg-secondary)',
          border: '2px solid var(--border-soft)',
          borderRadius: 'var(--pill)',
          margin: '0 auto 16px',
          maxWidth: 480,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            borderRadius: 'var(--pill)',
            background: '#0ec4b6',
            backgroundImage: 'repeating-linear-gradient(-45deg, #0ec4b6, #0ec4b6 10px, #01b0a7 10px, #01b0a7 20px)',
            backgroundSize: '28.28px 28.28px',
            animation: 'animal-btn-loading 1s linear infinite',
            transition: 'width .4s ease',
          }}
        />
      </div>

      {/* 步骤列表（pill 小标签） */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          gap: 8,
          maxWidth: 540,
          margin: '0 auto 20px',
          flexWrap: 'wrap',
        }}
      >
        {STEPS.map((s, i) => {
          const reached = i <= stepIdx
          return (
            <span
              key={s}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                fontSize: 13,
                fontWeight: 700,
                color: reached ? '#fff' : 'var(--text-body)',
                background: reached ? 'var(--primary)' : 'var(--bg-content)',
                border: reached ? '2px solid var(--primary-active)' : '2px solid var(--border-light)',
                borderRadius: 'var(--pill)',
                padding: '5px 14px',
                boxShadow: 'var(--elev-sm)',
                transition: 'all 0.25s var(--ease)',
              }}
            >
              {i < stepIdx ? '✓ ' : i === stepIdx ? '▸ ' : ''}
              {s}
            </span>
          )
        })}
      </div>

      <div
        style={{
          textAlign: 'center',
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--text-secondary)',
        }}
      >
        正在 {STEPS[stepIdx]}...
      </div>
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
        <div style={{ marginBottom: 10, fontWeight: 600 }}>
          ⏱️ 耗时 {e.hours} 小时 · <span style={{ color: 'var(--money)', fontWeight: 800 }}>💰 费用 ${e.total}</span>
        </div>
        <div style={{ fontWeight: 800, marginBottom: 6, color: 'var(--text)' }}>📦 产出</div>
        <div style={{ fontWeight: 600 }}>
          话术 {e.output.count} 条 · 售前 {e.output.presale} + 售后{' '}
          {e.output.afterSale} + 投诉 {e.output.complaint}
        </div>
      </div>

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

      {/* 链上 tx_hash 卡 — 仅在有真实 tx_hash 时显示 */}
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
          <a
            href={`https://sepolia.etherscan.io/tx/${e.txHash}`}
            target="_blank"
            rel="noreferrer"
            style={{
              fontSize: 12.5,
              fontWeight: 800,
              color: 'var(--success-active)',
              textDecoration: 'none',
              borderBottom: '1.5px dashed var(--success-active)',
            }}
          >
            在 Etherscan 查看 →
          </a>
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
