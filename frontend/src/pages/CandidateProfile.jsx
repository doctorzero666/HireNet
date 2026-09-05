import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import Icon from '../components/Icon'
import StreamText from '../components/StreamText'
import { fetchCandidateProfile, fetchCandidates, analyzeCandidate } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

function pick(obj, keys, fallback = '') {
  for (const k of keys) {
    const v = obj?.[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return fallback
}

function asList(value) {
  if (!value) return []
  if (Array.isArray(value)) return value
  if (typeof value === 'string') {
    return value.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
  }
  return [value]
}

export default function CandidateProfile() {
  const navigate = useNavigate()
  const { t, lang } = useLang()
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')
  // See JobSeekerHome for the pattern: `loading` is derived from whether the
  // profile on hand was fetched for the current language, so no effect ever
  // calls setState synchronously on its own body.
  const [loadedLang, setLoadedLang] = useState(null)
  const loading = loadedLang !== lang
  const [analysis, setAnalysis] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState('')

  // Profile fields are localised server-side, so re-fetch on language
  // change. `analysis` (the on-demand AI strengths writeup below) is left
  // alone — like an analysis session, its text is generated once in
  // whatever language was active at the time and isn't retroactively
  // re-translated.
  useEffect(() => {
    let cancelled = false
    fetchCandidates()
      .then((data) => {
        const first = (data?.candidates || [])[0]
        const id = first?.id
        if (!id) throw new Error(t('candidateProfile.errors.noProfile'))
        return fetchCandidateProfile(id)
      })
      .then((data) => {
        if (cancelled) return
        setProfile(data?.profile || data?.candidate || data)
        setError('')
        setLoadedLang(lang)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || t('candidateProfile.errors.loadFailed'))
        setLoadedLang(lang)
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang])

  const name = pick(profile, ['name', 'display_name', 'candidate_name'], t('candidateProfile.defaultName'))
  const headline = pick(profile, ['headline', 'title', 'role', 'current_role'], '')
  const bio = pick(profile, ['bio', 'summary', 'about', 'introduction'], '')
  const skills = asList(pick(profile, ['skills', 'tags', 'tech'], []))
  const experiences = asList(pick(profile, ['experiences', 'experience', 'work_history', 'history'], []))
  const avatar = pick(profile, ['avatar', 'emoji'], '🌱')

  return (
    <Scene>
      <Board maxWidth={780}>
        <NavBar role="jobseeker" />

        <div style={{ textAlign: 'center', margin: '14px 0 18px' }}>
          <Ribbon color="app-pink" size={20}>🪪 {t('candidateProfile.title')}</Ribbon>
        </div>

        {loading && (
          <div className="generating">
            <div className="spinner" />
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)' }}>
              {t('candidateProfile.loading')}
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="chat-error" style={{ marginBottom: 16 }}>{error}</div>
        )}

        {!loading && !error && (
          <>
            <div style={{
              background: '#f7f3df',
              border: '1.5px solid var(--border-soft)',
              borderRadius: 20,
              padding: '22px 24px',
              boxShadow: 'var(--elev-sm)',
              marginBottom: 18,
              display: 'flex',
              alignItems: 'center',
              gap: 18,
              flexWrap: 'wrap',
            }}>
              <div style={{
                width: 72,
                height: 72,
                borderRadius: '50%',
                background: 'var(--app-teal)',
                display: 'grid',
                placeItems: 'center',
                fontSize: 34,
                border: '3px solid rgba(255,255,255,.8)',
                boxShadow: 'var(--elev-sm)',
                flex: '0 0 auto',
              }}>
                {avatar}
              </div>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{
                  fontSize: 22,
                  fontWeight: 800,
                  color: 'var(--text)',
                  lineHeight: 1.3,
                }}>
                  {name}
                </div>
                {headline && (
                  <div style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: 'var(--text-muted)',
                    marginTop: 4,
                  }}>
                    {headline}
                  </div>
                )}
              </div>
            </div>

            {bio && (
              <Section title={t('candidateProfile.bio')}>
                <p style={{
                  fontSize: 14,
                  fontWeight: 500,
                  color: 'var(--text-body)',
                  lineHeight: 1.7,
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                }}>
                  {bio}
                </p>
              </Section>
            )}

            {skills.length > 0 && (
              <Section title={t('candidateProfile.skillTags')}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {skills.map((s, i) => (
                    <span key={i} style={{
                      fontSize: 12.5,
                      fontWeight: 700,
                      color: 'var(--primary-active)',
                      background: 'var(--primary-bg)',
                      border: '2px solid #b8ece6',
                      borderRadius: 'var(--pill)',
                      padding: '4px 12px',
                    }}>
                      {typeof s === 'string' ? s : pick(s, ['name', 'skill', 'label'], JSON.stringify(s))}
                    </span>
                  ))}
                </div>
              </Section>
            )}

            {experiences.length > 0 && (
              <Section title={t('candidateProfile.experience')}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {experiences.map((exp, i) => (
                    <ExperienceItem key={i} exp={exp} />
                  ))}
                </div>
              </Section>
            )}

            <Section title={`🤖 ${t('candidateProfile.aiAnalysis')}`}>
              {!analysis && !analyzing && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={async () => {
                    if (!profile) return
                    setAnalyzing(true)
                    setAnalyzeError('')
                    try {
                      const result = await analyzeCandidate(profile)
                      setAnalysis(result)
                    } catch (e) {
                      setAnalyzeError(e.message || t('candidateProfile.errors.analysisFailed'))
                    } finally {
                      setAnalyzing(false)
                    }
                  }}
                >
                  <Icon name="spark" size={15} /> {t('candidateProfile.analyzeMyStrengths')}
                </button>
              )}

              {analyzing && (
                <div style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                }}>
                  <div className="spinner" /> {t('candidateProfile.analyzing')}
                </div>
              )}

              {analyzeError && (
                <div className="chat-error" style={{ fontSize: 12.5 }}>{analyzeError}</div>
              )}

              {analysis && (
                <div style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                }}>
                  {(analysis.strengths ?? []).map((s, i) => (
                    <StrengthLine key={i} index={i} text={s} />
                  ))}
                  {(!analysis.strengths || analysis.strengths.length === 0) && analysis.raw && (
                    <div style={{
                      whiteSpace: 'pre-wrap',
                      fontSize: 13.5,
                      fontWeight: 500,
                      color: 'var(--text-body)',
                      lineHeight: 1.7,
                    }}>
                      <StreamText text={analysis.raw} />
                    </div>
                  )}
                </div>
              )}
            </Section>

            <div style={{
              display: 'flex',
              justifyContent: 'center',
              gap: 12,
              flexWrap: 'wrap',
              marginTop: 24,
            }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => navigate('/jobseeker')}
              >
                ◂ {t('candidateProfile.backToBoard')}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => alert(t('candidateProfile.editComingSoon'))}
              >
                <Icon name="edit" size={15} /> {t('candidateProfile.editProfile')}
              </button>
            </div>
          </>
        )}
      </Board>
    </Scene>
  )
}

function Section({ title, children }) {
  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.6)',
      border: '1.5px solid var(--border-soft)',
      borderRadius: 20,
      padding: '18px 22px',
      boxShadow: 'var(--elev-sm)',
      marginBottom: 14,
    }}>
      <div style={{
        fontSize: 12.5,
        fontWeight: 800,
        color: 'var(--text-muted)',
        letterSpacing: '0.04em',
        marginBottom: 10,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function StrengthLine({ index, text }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10,
      padding: '10px 14px',
      background: 'var(--primary-bg)',
      border: '1.5px solid #b8ece6',
      borderRadius: 14,
      fontSize: 13.5,
      fontWeight: 600,
      color: 'var(--text)',
      lineHeight: 1.6,
    }}>
      <span style={{
        flex: '0 0 auto',
        fontWeight: 900,
        color: 'var(--primary-active)',
        minWidth: 18,
      }}>
        {String(index + 1).padStart(2, '0')}
      </span>
      <span style={{ flex: 1 }}>
        <StreamText text={text} speed={14} />
      </span>
    </div>
  )
}

function ExperienceItem({ exp }) {
  const { t } = useLang()
  if (typeof exp === 'string') {
    return (
      <div style={{
        fontSize: 14,
        fontWeight: 500,
        color: 'var(--text-body)',
        lineHeight: 1.65,
      }}>
        ▸ {exp}
      </div>
    )
  }
  const title = exp?.title || exp?.role || exp?.position || t('candidateProfile.role')
  const company = exp?.company || exp?.organization || ''
  const period = exp?.period || exp?.duration || (exp?.start && `${exp.start}${exp?.end ? ` ~ ${exp.end}` : ` ~ ${t('candidateProfile.present')}`}`) || ''
  const detail = exp?.description || exp?.summary || ''
  return (
    <div style={{
      borderLeft: '3px solid var(--app-teal)',
      paddingLeft: 12,
    }}>
      <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--text)' }}>
        {title}{company ? ` · ${company}` : ''}
      </div>
      {period && (
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', marginTop: 2 }}>
          {period}
        </div>
      )}
      {detail && (
        <div style={{
          fontSize: 13.5,
          fontWeight: 500,
          color: 'var(--text-body)',
          marginTop: 6,
          lineHeight: 1.65,
          whiteSpace: 'pre-wrap',
        }}>
          {detail}
        </div>
      )}
    </div>
  )
}
