import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'

export default function EmployerHub() {
  const navigate = useNavigate()

  return (
    <Scene>
      <Board maxWidth={700}>
        {/* 品牌区 */}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div style={{
            fontSize: 'clamp(26px, 4vw, 36px)',
            fontWeight: 900,
            color: 'var(--text)',
            textShadow: '0px 3px 0px rgba(189, 174, 160, 0.55)',
            letterSpacing: '0.01em',
          }}>
            🏛 公会大厅
          </div>
          <div style={{
            fontSize: 14,
            fontWeight: 700,
            color: 'var(--text-muted)',
            letterSpacing: 3,
            marginTop: 10,
          }}>
            EMPLOYER GUILD HALL
          </div>
        </div>

        <SectionLabel>请选择你今天要做的事</SectionLabel>

        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
          marginTop: 20,
        }}>
          {/* 卡片 A：业务大本营 */}
          <HubCard
            accentColor="var(--app-green)"
            title="🏰 业务大本营"
            description="查看你的业务全景、Agent 工作状态和关键指标"
            buttonLabel="🚪 进入大本营"
            onClick={() => navigate('/employer/dashboard')}
          />

          {/* 卡片 B：发起委托 */}
          <HubCard
            accentColor="var(--app-teal)"
            title="📜 发起委托"
            description="描述你的业务需求，AI 帮你分析、拆解、匹配 Agent"
            buttonLabel="📜 写一份委托"
            onClick={() => navigate('/employer')}
          />
        </div>

        {/* 返回链接 */}
        <div style={{ textAlign: 'center', marginTop: 28 }}>
          <a
            href="/"
            onClick={(e) => {
              e.preventDefault()
              navigate('/')
            }}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 7,
              fontSize: 13.5,
              fontWeight: 700,
              color: 'var(--primary-active)',
              padding: '9px 18px',
              borderRadius: 'var(--pill)',
              background: 'rgba(255, 255, 255, 0.6)',
              border: '2px solid var(--border-soft)',
              boxShadow: 'var(--elev-sm)',
              transition: 'all 0.25s var(--ease)',
            }}
          >
            ◂ 返回角色选择
          </a>
        </div>
      </Board>
    </Scene>
  )
}

function HubCard({ accentColor, title, description, buttonLabel, onClick }) {
  return (
    <div
      style={{
        background: 'rgba(255, 255, 255, 0.6)',
        border: '1.5px solid var(--border-soft)',
        borderLeft: `8px solid ${accentColor}`,
        borderRadius: 20,
        padding: '22px 24px',
        boxShadow: 'var(--elev-sm)',
        transition: 'all 0.3s ease',
        cursor: 'pointer',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = 'var(--elev-lg)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = 'var(--elev-sm)'
      }}
      onClick={onClick}
    >
      <div style={{
        fontWeight: 800,
        fontSize: 18,
        color: 'var(--text)',
        marginBottom: 8,
      }}>
        {title}
      </div>
      <p style={{
        fontSize: 13.5,
        color: 'var(--text-body)',
        fontWeight: 500,
        lineHeight: 1.65,
        marginBottom: 16,
      }}>
        {description}
      </p>
      <div>
        <PixelButton variant="gold" onClick={onClick}>
          {buttonLabel}
        </PixelButton>
      </div>
    </div>
  )
}
