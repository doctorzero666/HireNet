import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import { login } from '../services/api'

/* Phase 2 / U6 — minimal real auth login page.
   Demo users: li_boss / zhang_ai / wang_dev / zhao_design, password "demo123". */
const DEMO_HINTS = [
  { id: 'li_boss',     name: '李老板', role: '企业'   },
  { id: 'zhang_ai',    name: '张AI',  role: '创作者' },
  { id: 'wang_dev',    name: '王工',  role: '求职者' },
  { id: 'zhao_design', name: '赵设计', role: '创作者' },
]

export default function Login() {
  const navigate = useNavigate()
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!userId.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    setError('')
    try {
      await login(userId.trim(), password)
      navigate('/')
    } catch (err) {
      setError(err.message || '登录失败')
      setLoading(false)
    }
  }

  return (
    <Scene>
      <Board maxWidth={520}>
        <div className="home" style={{ padding: '32px 8px' }}>
          <div className="eyebrow">🔑 登录</div>
          <h1>登录 HireNet</h1>
          <p className="sub">用账号登录后，你只能看到自己的数据。</p>

          <form onSubmit={handleSubmit} style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label style={FIELD_LABEL}>
              用户名
              <input
                type="text"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="li_boss / zhang_ai / wang_dev / zhao_design"
                autoComplete="username"
                style={FIELD_INPUT}
              />
            </label>
            <label style={FIELD_LABEL}>
              密码
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="demo 用户密码：demo123"
                autoComplete="current-password"
                style={FIELD_INPUT}
              />
            </label>

            {error && <div style={ERROR_BANNER}>{error}</div>}

            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary btn-lg btn-block"
              style={{ marginTop: 4 }}
            >
              {loading ? '登录中…' : '登录'}
            </button>
          </form>

          <div style={DEMO_HINT_BOX}>
            <div style={DEMO_HINT_TITLE}>Demo 账号（密码均为 demo123）</div>
            <div style={DEMO_HINT_GRID}>
              {DEMO_HINTS.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  style={DEMO_HINT_ROW}
                  onClick={() => { setUserId(u.id); setPassword('demo123') }}
                >
                  <span style={{ fontWeight: 800 }}>{u.id}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{u.name} · {u.role}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </Board>
    </Scene>
  )
}

const FIELD_LABEL = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  fontWeight: 700,
  fontSize: 13,
  color: 'var(--text)',
}

const FIELD_INPUT = {
  padding: '10px 12px',
  border: '1.5px solid var(--border-soft)',
  borderRadius: 12,
  background: 'rgba(255,255,255,0.85)',
  fontFamily: 'var(--font)',
  fontSize: 14,
  outline: 'none',
}

const ERROR_BANNER = {
  background: 'rgba(255, 220, 220, 0.7)',
  border: '1.5px solid rgba(220,80,80,0.4)',
  borderRadius: 10,
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 700,
  color: '#a02020',
}

const DEMO_HINT_BOX = {
  marginTop: 28,
  padding: 14,
  borderRadius: 14,
  border: '1.5px dashed var(--border-soft)',
  background: 'rgba(255,255,255,0.45)',
}

const DEMO_HINT_TITLE = {
  fontSize: 11,
  fontWeight: 800,
  color: 'var(--text-muted)',
  letterSpacing: '0.06em',
  marginBottom: 10,
}

const DEMO_HINT_GRID = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: 8,
}

const DEMO_HINT_ROW = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-start',
  gap: 2,
  padding: '8px 10px',
  borderRadius: 10,
  border: '1.5px solid var(--border-soft)',
  background: 'rgba(255,255,255,0.7)',
  fontFamily: 'var(--font)',
  cursor: 'pointer',
  textAlign: 'left',
}
