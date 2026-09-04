/**
 * MetricCard — Island style metric card (maps to island-ref's .metric)
 * Props:
 *   icon: emoji or character (e.g. '💰')
 *   label: metric name
 *   value: metric value (string or number)
 *   color: value color, defaults to #794f27
 */
export default function MetricCard({ icon, label, value, color = '#794f27' }) {
  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.6)',
      borderRadius: 20,
      padding: '16px 18px',
      border: '1.5px solid var(--border-soft)',
      transition: 'all 0.3s ease',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
        {icon && <span style={{ fontSize: 16, lineHeight: 1 }}>{icon}</span>}
        <span style={{
          fontSize: 11.5,
          fontWeight: 700,
          color: 'var(--text-secondary)',
        }}>
          {label}
        </span>
      </div>
      <div style={{
        fontSize: 27,
        fontWeight: 900,
        color,
        lineHeight: 1.1,
      }}>
        {value}
      </div>
    </div>
  )
}
