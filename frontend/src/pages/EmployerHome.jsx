import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Icon from '../components/Icon'
import { startAnalysis } from '../services/api'

const EXAMPLES = [
  { label: '搭建智能客服', icon: 'bot', text: '我想为电商平台搭建一套智能客服系统，覆盖售前咨询、售后处理和投诉响应。' },
  { label: '分析销售数据', icon: 'chart', text: '帮我分析最近三个季度的销售数据，找出增长机会和异常波动。' },
  { label: '开发数据看板', icon: 'grid',  text: '我需要一个实时业务数据看板，汇总销售额、客诉率和各渠道转化。' },
]

export default function EmployerHome() {
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  const [focus, setFocus] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const taRef = useRef(null)

  const go = async () => {
    const trimmed = value.trim()
    if (!trimmed) { taRef.current?.focus(); return }
    setLoading(true)
    setError('')
    try {
      const result = await startAnalysis(trimmed)
      navigate(`/employer/analysis/${result.session_id}`, {
        state: { initialMessage: trimmed, firstReply: result },
      })
    } catch (e) {
      setError(e.message || '启动分析失败')
      setLoading(false)
    }
  }

  const pickExample = (ex) => {
    setValue(ex.text)
    taRef.current?.focus()
  }

  return (
    <Scene>
      <Board maxWidth={860}>
        <NavBar role="employer" />

        <div className="home">
          <div className="eyebrow"><Icon name="clipboard" size={14} /> 新任务</div>
          <h1>今天想完成什么？</h1>
          <p className="sub">把目标交给平台。我们会拆解任务、匹配可信 Agent，并在你的授权范围内安全执行。</p>

          <div className="composer-label">描述你的需求</div>
          <div className={`composer ${focus ? 'focus' : ''}`}>
            <textarea
              ref={taRef}
              value={value}
              placeholder="例如：我需要为电商平台搭建智能客服系统..."
              onChange={(e) => setValue(e.target.value)}
              onFocus={() => setFocus(true)}
              onBlur={() => setFocus(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !loading) go()
              }}
              disabled={loading}
            />
            <div className="composer-bar">
              <span style={{
                fontSize: 12,
                color: 'var(--text-disabled)',
                fontWeight: 600,
              }}>
                ⌘ + Enter 提交
              </span>
              <button
                type="button"
                className="btn btn-primary"
                onClick={go}
                disabled={loading || !value.trim()}
              >
                {loading ? '分析中…' : '开始分析'} <Icon name="arrow" size={16} />
              </button>
            </div>
          </div>

          {error && (
            <div style={{
              marginTop: 14,
              fontSize: 12.5,
              fontWeight: 700,
              color: 'var(--error-active)',
              background: '#fbe5e5',
              border: '1.5px solid #f3c6c6',
              padding: '10px 16px',
              borderRadius: 'var(--r)',
            }}>
              {error}
            </div>
          )}

          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex.label}
                type="button"
                className="chip"
                onClick={() => pickExample(ex)}
              >
                <Icon name={ex.icon} size={15} /> {ex.label}
              </button>
            ))}
          </div>
        </div>
      </Board>
    </Scene>
  )
}
