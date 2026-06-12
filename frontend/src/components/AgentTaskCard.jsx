import PixelButton from './PixelButton'

/**
 * AgentTaskCard — Agent 可完成的任务卡片
 * props:
 *   task: { id, name, description, type, estimated_hours }
 *   decision: { recommendation: { decision, resource, reason, cost_hint }, evaluations }
 *   onLaunch?: () => void
 */
export default function AgentTaskCard({ task, decision, onLaunch }) {
  const rec = decision?.recommendation ?? {}
  const resource = rec.resource?.resource_name ?? rec.resource ?? '匹配中…'
  const cost = rec.cost_hint ?? '—'
  const hours = task?.estimated_hours ?? '—'

  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.6)',
      borderRadius: 20,
      border: '1.5px solid var(--border-soft)',
      borderLeft: '8px solid var(--app-green)',
      padding: '22px 24px',
      boxShadow: 'var(--elev-sm)',
      transition: 'all 0.3s ease',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 10, marginBottom: 10, flexWrap: 'wrap',
      }}>
        <h4 style={{
          fontWeight: 800, fontSize: 18,
          color: 'var(--text)', margin: 0,
        }}>
          {task?.name ?? '未命名任务'}
        </h4>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: '#e9f4dd',
          border: '1.5px solid #cde6b2',
          borderRadius: 'var(--pill)',
          padding: '3px 11px',
          fontSize: 11.5, fontWeight: 800, color: '#5a9e1e',
          whiteSpace: 'nowrap',
        }}>
          ✅ Agent 可完成
        </span>
      </div>

      {task?.description && (
        <p style={{
          fontSize: 13.5, lineHeight: 1.65, color: 'var(--text-body)',
          fontWeight: 500,
          margin: '4px 0 12px',
        }}>
          {task.description}
        </p>
      )}

      <div style={{
        display: 'flex', flexDirection: 'column', gap: 4,
        background: 'var(--primary-bg)',
        borderRadius: 'var(--r)',
        padding: '12px 16px',
        marginBottom: 14,
        fontSize: 12.5, lineHeight: 1.6, color: 'var(--text-body)',
        fontWeight: 600,
      }}>
        <div style={{ color: 'var(--primary-active)', fontWeight: 800 }}>
          🤖 匹配 Agent：{resource}
        </div>
        {rec.reason && (
          <div style={{ color: 'var(--text-body)' }}>
            {rec.reason}
          </div>
        )}
      </div>

      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        gap: 16, flexWrap: 'wrap',
      }}>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 700 }}>
          ⏱️ {hours} 小时 · <span style={{ color: 'var(--money)' }}>💰 {cost}</span>
        </div>
        <PixelButton variant="gold" onClick={onLaunch}>
          ▶ 启动 Agent
        </PixelButton>
      </div>
    </div>
  )
}
