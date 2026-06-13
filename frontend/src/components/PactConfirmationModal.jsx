import { useEffect, useRef, useState } from 'react'
import PixelButton from './PixelButton'
import { createPact, approvePact, settlePact } from '../services/api'

/**
 * PactConfirmationModal — Pact 授权确认 Modal
 * props:
 *   agent: { name, creator, wallet, pricePerHour }
 *   task: { id, name, description, estimatedHours }
 *   onConfirm: () => void
 *   onReject: () => void
 *   onClose: () => void
 */
export default function PactConfirmationModal({ agent, task, onConfirm, onReject, onClose }) {
  const [estimatedHours, setEstimatedHours] = useState(task?.estimatedHours ?? 2)
  const [showAdjust, setShowAdjust] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [stage, setStage] = useState('')
  const [dots, setDots] = useState('')
  const [error, setError] = useState('')
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
      setStage('审批中')

      await approvePact(pact.pact_id)
      if (cancelledRef.current) return
      setStage('结算中')

      const settlement = await settlePact(pact.pact_id)
      if (cancelledRef.current) return

      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      onConfirm?.({
        ...settlement,
        agent_name: agent?.name,
        creator: agent?.creator,
        hours: estimatedHours,
      })
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

        {/* Cobo 确认区 */}
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
            📱 请在 Cobo App 确认
          </div>

          {/* App 截图占位 */}
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
            [Cobo App 截图示意]
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
            <li>打开 Cobo Agentic Wallet App</li>
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
        </div>
      </div>
    </div>
  )
}
