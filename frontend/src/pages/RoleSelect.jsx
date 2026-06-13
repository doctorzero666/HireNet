import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Ribbon from '../components/Ribbon'
import Icon from '../components/Icon'

const EMPLOYER = {
  role: 'ent',
  icon: '🏢',
  title: '我是雇主',
  sub: '描述需求 · 智能匹配 · 找到资源。',
  steps: [
    '描述你的业务需求',
    'AI 智能拆解与匹配',
    '启动 Agent 或招募人才',
  ],
  cta: '进入',
  to: '/employer/hub',
}

const SEEKER = {
  role: 'cre',
  icon: '👤',
  title: '我是求职者',
  sub: '探索机会 · 参与任务 · 成长路径。',
  steps: [
    '探索机会，发现合适的任务',
    '参与任务，让技能被调用',
    '建立成长路径与版税收益',
  ],
  cta: '进入',
  to: '/jobseeker',
}

const CREATOR = {
  role: 'cre',
  icon: '🎨',
  title: '我是创作者',
  sub: '发布 Agent · 获得收益 · 建立版税。',
  steps: [
    '注册你的 AI Agent 能力',
    '被企业调用，自动完成工作',
    '获得持续版税收益',
  ],
  cta: '进入',
  to: '/creator',
}

export default function RoleSelect() {
  const navigate = useNavigate()
  return (
    <Scene>
      <div className="roleselect">
        <div className="guild-brand">
          <h1 className="guild-logo"><span className="leaf">🍃</span> HireNet</h1>
          <p className="guild-sub">AI 劳动力网络 · 岛民版</p>
          <div className="guild-pill">🏝️ 让工作像岛上生活一样自然</div>
        </div>

        <div className="rs-board-title">
          <Ribbon color="app-teal" size={22}>选择你的身份</Ribbon>
        </div>

        <div className="role-grid">
          <RoleCard d={EMPLOYER} onEnter={() => navigate(EMPLOYER.to)} />
          <RoleCard d={SEEKER} onEnter={() => navigate(SEEKER.to)} />
          <RoleCard d={CREATOR} onEnter={() => navigate(CREATOR.to)} />
        </div>

        <div className="rs-foot">
          <a
            href="/agents"
            onClick={(e) => { e.preventDefault(); navigate('/agents') }}
          >
            看看谁正在让这个世界运转 · 进入 Agent 世界 <Icon name="arrow" size={14} />
          </a>
        </div>
      </div>
    </Scene>
  )
}

function RoleCard({ d, onEnter }) {
  return (
    <div className={`role-card ${d.role}`} onClick={onEnter}>
      <div className={`role-ic ${d.role}`}>{d.icon}</div>
      <h2>{d.title}</h2>
      <p className="rc-sub">{d.sub}</p>
      <div className="role-steps">
        {d.steps.map((s, i) => (
          <div className="role-step" key={i}>
            <span className="rs-n">▸</span>
            <span className="rs-t">{s}</span>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="btn btn-primary btn-lg btn-block rc-btn"
        onClick={(e) => { e.stopPropagation(); onEnter() }}
      >
        {d.cta} <Icon name="arrow" size={16} />
      </button>
    </div>
  )
}
