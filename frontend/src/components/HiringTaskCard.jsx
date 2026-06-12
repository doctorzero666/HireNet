import PixelButton from './PixelButton'

/**
 * HiringTaskCard — 需要招聘人选的任务卡片
 */
export default function HiringTaskCard({ task, decision, onGenerateJD }) {
  const rec = decision?.recommendation ?? {}
  const reason = rec.reason ?? '当前 Agent 资源无法胜任，建议招聘'
  const salary = rec.cost_hint ?? '—'
  const hours = task?.estimated_hours ?? '—'

  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.6)',
      borderRadius: 20,
      border: '1.5px solid var(--border-soft)',
      borderLeft: '8px solid var(--app-yellow)',
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
          background: '#fdf3d2',
          border: '1.5px solid #f3df9a',
          borderRadius: 'var(--pill)',
          padding: '3px 11px',
          fontSize: 11.5, fontWeight: 800, color: '#b8900a',
          whiteSpace: 'nowrap',
        }}>
          ⚠️ 建议招人
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
        background: 'rgba(255, 255, 255, 0.55)',
        border: '1px dashed rgb(220, 206, 180)',
        borderRadius: 'var(--r)',
        padding: '12px 16px',
        marginBottom: 14,
        fontSize: 12.5, lineHeight: 1.6, color: 'var(--text-body)',
        fontWeight: 600,
      }}>
        <div style={{ color: 'var(--warning-active)', fontWeight: 800 }}>
          📋 招聘原因
        </div>
        <div>{reason}</div>
      </div>

      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        gap: 16, flexWrap: 'wrap',
      }}>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 700 }}>
          ⏱️ {hours} 小时 · <span style={{ color: 'var(--money)' }}>💰 预估薪资 {salary}</span>
        </div>
        <PixelButton variant="gold" onClick={onGenerateJD}>
          📝 生成 JD
        </PixelButton>
      </div>
    </div>
  )
}
