/**
 * HybridTaskCard — 人机协同任务卡片
 */
export default function HybridTaskCard({ task, decision }) {
  const rec = decision?.recommendation ?? {}
  const division = rec.reason ?? rec.resource ?? '人机分工待定'
  const cost = rec.cost_hint ?? '—'
  const hours = task?.estimated_hours ?? '—'

  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.6)',
      borderRadius: 20,
      border: '1.5px solid var(--border-soft)',
      borderLeft: '8px solid var(--app-blue)',
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
          background: '#e9edfc',
          border: '1.5px solid #ccd5f8',
          borderRadius: 'var(--pill)',
          padding: '3px 11px',
          fontSize: 11.5, fontWeight: 800, color: '#5068d8',
          whiteSpace: 'nowrap',
        }}>
          🔄 人机协同
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
        <div style={{ color: '#5068d8', fontWeight: 800 }}>
          🤝 分工说明
        </div>
        <div>{division}</div>
      </div>

      <div style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 700 }}>
        ⏱️ {hours} 小时 · <span style={{ color: 'var(--money)' }}>💰 {cost}</span>
      </div>
    </div>
  )
}
