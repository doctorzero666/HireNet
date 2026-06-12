import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Icon from '../components/Icon'
import StreamText from '../components/StreamText'
import { replyAnalysis, runDecision } from '../services/api'

function extractQuickOptions(text) {
  if (!text) return { body: text, options: [] }
  const match = text.match(/\[([^[\]]+)\]\s*$/)
  if (!match) return { body: text, options: [] }
  const raw = match[1]
  if (!raw.includes('|') && raw.length > 30) return { body: text, options: [] }
  const options = raw.split('|').map((s) => s.trim()).filter(Boolean)
  if (options.length < 2) return { body: text, options: [] }
  const body = text.slice(0, match.index).trim()
  return { body, options }
}

export default function AnalysisChat() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const [messages, setMessages] = useState(() => {
    const state = location.state
    if (!state) return []
    const seed = []
    if (state.initialMessage) {
      seed.push({ role: 'user', text: state.initialMessage, stream: false })
    }
    if (state.firstReply?.response) {
      seed.push({ role: 'ai', text: state.firstReply.response, stream: true })
    }
    return seed
  })
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const isComplete = location.state?.firstReply?.is_complete
  const [complete, setComplete] = useState(!!isComplete)
  const initialMessage = location.state?.initialMessage

  const bottomRef = useRef(null)
  const decidingRef = useRef(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, complete])

  useEffect(() => {
    if (!complete || decidingRef.current) return
    let cancelled = false
    decidingRef.current = true
    runDecision(sessionId)
      .then((result) => {
        if (cancelled) return
        navigate(`/employer/report/${sessionId}`, { state: result })
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || '生成报告失败')
        decidingRef.current = false
      })
    return () => { cancelled = true }
  }, [complete, sessionId, navigate])

  const send = async (text) => {
    const trimmed = (text ?? input).trim()
    if (!trimmed || sending || complete) return
    setInput('')
    setError('')
    setMessages((prev) => [...prev, { role: 'user', text: trimmed, stream: false }])
    setSending(true)
    try {
      const result = await replyAnalysis(sessionId, trimmed)
      setMessages((prev) => [...prev, { role: 'ai', text: result.response, stream: true }])
      if (result.is_complete) setComplete(true)
    } catch (e) {
      setError(e.message || '发送失败')
    } finally {
      setSending(false)
    }
  }

  return (
    <Scene>
      <style>{`.scene .board { animation: none; }`}</style>
      <Board maxWidth={860}>
        <NavBar role="employer" />

        <div className="interview">
          <div className="iv-head">
            <div className="avatar indigo lg" style={{ margin: '0 auto' }}>
              <Icon name="bot" size={20} />
            </div>
            <h2>AI 需求分析</h2>
            {initialMessage && (
              <p>{initialMessage}</p>
            )}
          </div>

          <div style={{ minHeight: '60vh' }}>
            {messages.length === 0 && (
              <div style={{
                textAlign: 'center',
                fontSize: 13.5,
                color: 'var(--text-secondary)',
                fontWeight: 600,
                padding: 32,
              }}>
                开始对话…
              </div>
            )}

            {messages.map((m, i) => {
              const isLast = i === messages.length - 1
              const shouldStream = m.role === 'ai' && m.stream && isLast
              return (
                <ChatMessage
                  key={i}
                  message={m}
                  stream={shouldStream}
                  onPick={send}
                  disabled={sending || complete}
                  showOptions={isLast && !sending}
                />
              )
            })}

            {sending && (
              <ChatMessage
                message={{ role: 'ai', text: '思考中…' }}
                stream={false}
                disabled
                showOptions={false}
              />
            )}
          </div>

          {complete && !error && (
            <div className="generating">
              <div className="spinner" />
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>
                  正在生成需求分析报告…
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 5 }}>
                  拆解任务 · 匹配 Agent · 估算成本
                </div>
              </div>
            </div>
          )}

          <div ref={bottomRef} />

          {error && (
            <div className="chat-error">{error}</div>
          )}

          {!complete && (
            <div className="chat-input-row">
              <input
                type="text"
                className="input-text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') send() }}
                placeholder="继续描述…"
                disabled={sending}
              />
              <button
                type="button"
                className="btn btn-soft"
                onClick={() => send()}
                disabled={sending || !input.trim()}
              >
                发送 <Icon name="arrow" size={16} />
              </button>
            </div>
          )}
        </div>
      </Board>
    </Scene>
  )
}

function ChatMessage({ message, stream, onPick, disabled, showOptions }) {
  const isUser = message.role === 'user'
  const { body, options } = isUser
    ? { body: message.text, options: [] }
    : extractQuickOptions(message.text)

  return (
    <div className={`msg ${isUser ? 'user' : 'ai'}`}>
      <div className={`avatar ${isUser ? 'amber' : 'indigo'}`}>
        <Icon name={isUser ? 'user' : 'bot'} size={isUser ? 15 : 16} />
      </div>
      <div className="msg-body">
        <div className="who">{isUser ? '你' : 'HireNet Agent'}</div>
        <div className="bubble" style={isUser ? undefined : { minHeight: 48 }}>
          {stream ? <StreamText text={body} /> : body}
        </div>
        {!isUser && showOptions && options.length > 0 && onPick && (
          <div className="quick-opts">
            {options.map((opt) => (
              <button
                key={opt}
                type="button"
                className="quick-opt"
                onClick={() => onPick(opt)}
                disabled={disabled}
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
