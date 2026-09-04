import { useEffect, useRef, useState } from 'react'
import PixelButton from './PixelButton'
import { createPact, approvePact, settlePact } from '../services/api'

/**
 * PactConfirmationModal — Pact 授权确认 Modal
 * props:
 *   agent: { name, creator, wallet, pricePerHour }
 *   task: { id, name, description, estimatedHours }
 *   onConfirm: (settlement) => void   // 由结算完成后的“完成”按钮触发，不再在
 *                                     // settle 返回时自动触发（WP-E）
 *   onReject: () => void
 *   onClose: () => void
 */

/* 授权凭证 (mandate) 展示辅助 — 后端 /api/pact/create 返回的 AP2 风格字段
   intent / payee / amount_cap / expires_at 在这里被渲染出来。这些字段只是
   命名对齐 AP2 的 mandate 词汇，没有任何签名背书（后端 app/app.py 的
   pact 段注释写明了这一点），所以 UI 上也不要出现“已签名 / 已验证”字样。 */

/** 0x 地址缩短成 0x1234…abcd；非地址原样显示；空值显示 —。 */
function formatPayee(payee) {
  if (payee === null || payee === undefined || payee === '') return '—'
  const text = String(payee)
  if (/^0x[0-9a-fA-F]{12,}$/.test(text)) {
    return `${text.slice(0, 6)}…${text.slice(-4)}`
  }
  return text
}

/** ISO 8601 (UTC) → 浏览器本地时间；解析不了就原样显示。 */
function formatLocalTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString()
}

/** amount_cap 与 amount 同单位（美元），后端默认取 amount。 */
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
  const [estimatedHours, setEstimatedHours] = useState(task?.estimatedHours ?? 2)
  const [showAdjust, setShowAdjust] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [stage, setStage] = useState('')
  const [dots, setDots] = useState('')
  const [error, setError] = useState('')
  /* mandate: /api/pact/create 的返回体，携带 intent / payee / amount_cap /
     expires_at / content_hash。创建成功后才有值，所以授权凭证区块在点击
     “确认授权”之前不渲染。 */
  const [mandate, setMandate] = useState(null)
  /* settled: /api/pact/settle 的返回体，用于展示 tx hash（有 explorer_url
     时渲染成链接）。 */
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
    setStage('创建 Pact 中')
    cancelledRef.current = false
    let i = 0
    intervalRef.current = setInterval(() => {
      i = (i + 1) % 4
      setDots('.'.repeat(i))
    }, 400)

    try {
      const pact = await createPact({
        task_id: task?.id || 'task-001',
        agent_name: agent?.name ?? '客服话术生成器',
        creator_id: agent?.creator_id,
        /* asset_id (when provided by demo bootstrap) pins billing to zhang_ai's
           Agent instead of the JOB_DESIGN_ASSET_ID fallback. */
        asset_id: agent?.asset_id,
        amount: Number(total),
        currency: 'USD',
      })
      if (cancelledRef.current) return
      setMandate(pact)
      setStage('审批中')

      const approved = await approvePact(pact.pact_id)
      if (cancelledRef.current) return
      /* approve 回的是完整 pact（多了 approved_by / approval_method），用它
         覆盖创建时的快照，凭证区块显示的就是当前状态。 */
      if (approved?.pact_id) setMandate(approved)
      setStage('结算中')

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
         now stays in its settled state and the user leaves via 完成 below. */
      setWaiting(false)
      setStage('')
    } catch (err) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      setWaiting(false)
      setStage('')
      setError(err?.message || '请求失败')
    }
  }

  /* 结算完成后的“完成”按钮：做的正是过去 settle 一返回就自动做的事 —— 把结算
     结果交给父组件（AnalysisReport 卸载 Modal 并跳转到执行页）。区别只是现在
     由用户点一下，凭证与链上交易号因此可读。 */
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
        {/* 标题 */}
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <div
            style={{
              display: 'inline-block',
              fontSize: 22,
              fontWeight: 800,
              color: 'var(--text-body)',
            }}
          >
            📜 Pact 授权确认
          </div>
        </div>

        {/* 信息卡片 */}
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
              🤖 {agent?.name ?? '客服话术生成器'}
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
              {agent?.creator ?? '@李四'}
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

          {/* 费用明细 */}
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
            <div style={{ fontWeight: 800, marginBottom: 8, color: 'var(--text)' }}>💰 费用明细</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: 12 }}>单价</span>
              <span style={{ fontWeight: 800 }}>${price} / 小时</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: 12 }}>预估时长</span>
              <span style={{ fontWeight: 800 }}>{estimatedHours} 小时</span>
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
              <span>总限额</span>
              <span style={{ color: 'var(--money)', fontWeight: 900, fontSize: 15 }}>${total}</span>
            </div>
          </div>

          {showAdjust && (
            <div style={{ marginTop: 12, fontSize: 14 }}>
              <label style={{ marginRight: 10, color: 'var(--text)', fontWeight: 700, fontSize: 13 }}>
                调整预估时长 (小时):
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

        {/* 收款方 */}
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
          <span style={{ fontWeight: 800, color: 'var(--success-active)' }}>📬 收款方钱包：</span>
          <code style={{ marginLeft: 8, fontSize: 12.5 }}>
            {walletShort}
          </code>
        </div>

        {/* 授权凭证 — 后端返回的 AP2 风格 mandate 字段。创建成功后才出现。 */}
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
              📜 授权凭证
            </div>

            <MandateRow label="授权内容">{mandate.intent || '—'}</MandateRow>
            <MandateRow label="收款方">
              <code style={{ fontSize: 12.5 }}>{formatPayee(mandate.payee)}</code>
            </MandateRow>
            <MandateRow label="授权上限">
              {formatCap(mandate.amount_cap, mandate.currency)}
            </MandateRow>
            <MandateRow label="有效期至">
              {formatLocalTime(mandate.expires_at)}
            </MandateRow>

            {/* 结算完成后的链上交易号。explorer_url 由后端在 x402 结算路径上
                提供；没有时只显示纯文本，不伪造链接。 */}
            {settled?.tx_hash && (
              <MandateRow label="交易哈希">
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

        {/* 钱包确认区 */}
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
            📱 请在钱包中确认授权
          </div>

          {/* 钱包确认示意占位 */}
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
            [钱包确认界面示意]
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
            <li>打开你的钱包应用</li>
            <li>查看 Pact 详情</li>
            <li>确认签名</li>
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
              {stage || '等待确认中'}{dots}
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

        {/* 按钮行 */}
        <div
          style={{
            display: 'flex',
            gap: 10,
            justifyContent: 'center',
            flexWrap: 'wrap',
          }}
        >
          {settled ? (
            /* 结算已完成：授权/调整/拒绝都已无意义，只留一个出口。 */
            <PixelButton variant="gold" onClick={handleDone}>
              ✓ 完成
            </PixelButton>
          ) : (
            <>
              <PixelButton variant="gold" onClick={handleConfirm} disabled={waiting}>
                ✓ 确认授权
              </PixelButton>
              <PixelButton
                variant="wood"
                onClick={() => setShowAdjust((v) => !v)}
                disabled={waiting}
              >
                ⚙ 调整限额
              </PixelButton>
              <PixelButton variant="danger" onClick={onReject} disabled={waiting}>
                ✕ 拒绝
              </PixelButton>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
