import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'

const INPUT_STYLE = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg-content)',
  border: '2.5px solid var(--border-light)',
  borderRadius: 'var(--pill)',
  height: 44,
  padding: '0 18px',
  fontSize: 14,
  fontWeight: 500,
  color: 'var(--text-body)',
  outline: 'none',
  transition: 'all 0.25s var(--ease)',
}

const TEXTAREA_STYLE = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg-content)',
  border: '2.5px solid var(--border-light)',
  borderRadius: 'var(--r)',
  padding: '11px 16px',
  fontSize: 14,
  fontWeight: 500,
  color: 'var(--text-body)',
  outline: 'none',
  resize: 'vertical',
  minHeight: 74,
  lineHeight: 1.6,
  transition: 'all 0.25s var(--ease)',
}

const LABEL_STYLE = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  fontSize: 13,
  fontWeight: 700,
  color: 'var(--text)',
  marginBottom: 8,
}

const FIELD_WRAP = { marginBottom: 16 }

export default function AgentRegister() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    name: '',
    description: '',
    type: 'Skill',
    price: '',
    wallet: '',
  })

  const onChange = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const handleSubmit = (e) => {
    e.preventDefault()
    alert(`📜 已提交注册：${form.name || '未命名 Agent'}`)
    navigate('/creator')
  }

  const handleFocus = (e) => {
    e.target.style.borderColor = 'var(--focus-yellow)'
  }

  const handleBlur = (e) => {
    e.target.style.borderColor = 'var(--border-light)'
  }

  return (
    <Scene>
      <Board maxWidth={600}>
        <NavBar role="creator" />

        <div style={{ marginTop: 8 }}>
          <SectionLabel>⚒️ 注册新 Agent</SectionLabel>
        </div>

        <p style={{
          textAlign: 'center',
          fontSize: 14,
          color: 'var(--text-muted)',
          fontWeight: 600,
          lineHeight: 1.65,
          marginTop: 12,
          marginBottom: 20,
        }}>
          填写资产信息 · 完成确权后即可被调用
        </p>

        <form onSubmit={handleSubmit}>
          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>Agent 名称</label>
            <input
              type="text"
              value={form.name}
              onChange={onChange('name')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder="例：客服话术生成器"
              style={INPUT_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>描述</label>
            <textarea
              value={form.description}
              onChange={onChange('description')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder="它能做什么？适合什么场景？"
              rows={4}
              style={TEXTAREA_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>类型</label>
            <select
              value={form.type}
              onChange={onChange('type')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              style={INPUT_STYLE}
            >
              <option value="Skill">Skill</option>
              <option value="Agent">Agent</option>
              <option value="Endpoint">Endpoint</option>
            </select>
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>单价 $/小时</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={form.price}
              onChange={onChange('price')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder="例：30"
              style={INPUT_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>钱包地址</label>
            <input
              type="text"
              value={form.wallet}
              onChange={onChange('wallet')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder="0x..."
              style={INPUT_STYLE}
            />
          </div>

          <div style={{
            display: 'flex',
            justifyContent: 'center',
            gap: 14,
            marginTop: 24,
            flexWrap: 'wrap',
          }}>
            <PixelButton variant="gold" type="submit">
              📜 提交注册
            </PixelButton>
            <PixelButton variant="wood" onClick={() => navigate('/creator')}>
              ◂ 返回工坊
            </PixelButton>
          </div>
        </form>
      </Board>
    </Scene>
  )
}
