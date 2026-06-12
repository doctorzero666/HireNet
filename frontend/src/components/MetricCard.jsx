/**
 * MetricCard — Island 风格指标卡片（对应 island-ref 的 .metric）
 * Props:
 *   icon: 表情或字符（例：'💰'）
 *   label: 指标名称
 *   value: 指标数值（字符串或数字）
 *   color: 数值颜色，默认 #794f27
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
