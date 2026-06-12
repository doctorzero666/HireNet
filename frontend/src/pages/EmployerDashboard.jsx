import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import MetricCard from '../components/MetricCard'

const AGENTS = [
  { name: '客服话术生成器', creator: '@李四', calls: 12, accuracy: '92%', online: true },
  { name: '数据分析助手', creator: '@王五', calls: 8, accuracy: '88%', online: true },
  { name: '代码审查 Bot', creator: '@赵六', calls: 5, accuracy: '95%', online: false },
]

const WARNINGS = [
  '客服话术生成器本周调用量下降 30%',
  '数据分析助手准确率低于 90% 阈值',
]

export default function EmployerDashboard() {
  const navigate = useNavigate()

  return (
    <Scene>
      <Board maxWidth={920}>
        <NavBar role="employer" />

        <div style={{ marginTop: 8 }}>
          <SectionLabel>🏰 业务大本营</SectionLabel>
        </div>

        {/* 4 指标卡片 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 14,
          marginTop: 14,
          marginBottom: 28,
        }}>
          <MetricCard icon="💰" label="本月总支出" value="$1,240" color="var(--money)" />
          <MetricCard icon="🤖" label="活跃 Agent" value="3" color="var(--text)" />
          <MetricCard icon="✅" label="任务完成率" value="85%" color="var(--text)" />
          <MetricCard icon="⏱️" label="节省人力" value="120h" color="var(--text)" />
        </div>

        {/* Agent 列表 */}
        <SectionLabel>🤖 旗下 Agent</SectionLabel>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          marginTop: 12,
          marginBottom: 28,
        }}>
          {AGENTS.map((a) => (
            <div
              key={a.name}
              style={{
                background: 'rgba(255, 255, 255, 0.6)',
                border: '1.5px solid var(--border-soft)',
                borderRadius: 20,
                padding: '14px 18px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 12,
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'translateY(-2px)'
                e.currentTarget.style.boxShadow = 'var(--elev-base)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translateY(0)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              <div>
                <div style={{
                  fontWeight: 800,
                  fontSize: 14,
                  color: 'var(--text)',
                  whiteSpace: 'nowrap',
                }}>
                  🤖 {a.name}
                </div>
                <div style={{
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  marginTop: 1,
                }}>
                  {a.creator}
                </div>
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontSize: 13,
                color: 'var(--text-body)',
                fontWeight: 600,
              }}>
                <span>📞 {a.calls} 次</span>
                <span style={{ color: 'var(--text-disabled)' }}>·</span>
                <span>🎯 {a.accuracy}</span>
                <span style={{ color: 'var(--text-disabled)' }}>·</span>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 7,
                    padding: '3px 12px',
                    borderRadius: 'var(--pill)',
                    fontSize: 11.5,
                    fontWeight: 800,
                    color: a.online ? 'var(--success-active)' : 'var(--text-secondary)',
                    background: a.online ? '#e9f4dd' : 'var(--bg-secondary)',
                  }}
                >
                  {a.online ? '● 在线' : '○ 离线'}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* 预警区 */}
        <SectionLabel>⚠️ 预警</SectionLabel>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          marginTop: 12,
          marginBottom: 28,
        }}>
          {WARNINGS.map((w, i) => (
            <div
              key={i}
              style={{
                background: 'rgba(255, 255, 255, 0.6)',
                border: '1.5px solid var(--border-soft)',
                borderLeft: '6px solid var(--warning)',
                borderRadius: 20,
                padding: '14px 18px',
                fontSize: 13.5,
                fontWeight: 800,
                color: 'var(--text)',
              }}
            >
              ⚠️ {w}
            </div>
          ))}
        </div>

        {/* 返回按钮 */}
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <PixelButton variant="wood" onClick={() => navigate('/employer/hub')}>
            ◂ 返回公会大厅
          </PixelButton>
        </div>
      </Board>
    </Scene>
  )
}
