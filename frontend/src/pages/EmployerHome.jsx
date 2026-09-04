import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Icon from '../components/Icon'
import { startAnalysis } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

function useExamples(t) {
  return [
    { label: t('employerHome.examples.customerService.label'), icon: 'bot', text: t('employerHome.examples.customerService.text') },
    { label: t('employerHome.examples.salesAnalysis.label'), icon: 'chart', text: t('employerHome.examples.salesAnalysis.text') },
    { label: t('employerHome.examples.dataDashboard.label'), icon: 'grid', text: t('employerHome.examples.dataDashboard.text') },
  ]
}

export default function EmployerHome() {
  const navigate = useNavigate()
  const { t, lang } = useLang()
  const EXAMPLES = useExamples(t)
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
      const result = await startAnalysis(trimmed, lang)
      navigate(`/employer/analysis/${result.session_id}`, {
        state: { initialMessage: trimmed, firstReply: result },
      })
    } catch (e) {
      setError(e.message || t('employerHome.errors.startFailed'))
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
          <div className="eyebrow"><Icon name="clipboard" size={14} /> {t('employerHome.eyebrow')}</div>
          <h1>{t('employerHome.title')}</h1>
          <p className="sub">{t('employerHome.subtitle')}</p>

          <div className="composer-label">{t('employerHome.composerLabel')}</div>
          <div className={`composer ${focus ? 'focus' : ''}`}>
            <textarea
              ref={taRef}
              value={value}
              placeholder={t('employerHome.composerPlaceholder')}
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
                ⌘ + Enter {t('employerHome.submit')}
              </span>
              <button
                type="button"
                className="btn btn-primary"
                onClick={go}
                disabled={loading || !value.trim()}
              >
                {loading ? t('employerHome.analyzing') : t('employerHome.startAnalysis')} <Icon name="arrow" size={16} />
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
