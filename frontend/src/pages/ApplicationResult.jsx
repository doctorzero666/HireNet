import { useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import Icon from '../components/Icon'
import StreamText from '../components/StreamText'

function pick(obj, keys, fallback = null) {
  for (const k of keys) {
    const v = obj?.[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return fallback
}

function formatScore(raw) {
  if (raw === null || raw === undefined) return null
  if (typeof raw === 'number') {
    if (raw <= 1) return `${Math.round(raw * 100)}%`
    if (raw <= 100) return `${Math.round(raw)}%`
    return String(raw)
  }
  return String(raw)
}

export default function ApplicationResult() {
  const navigate = useNavigate()
  const location = useLocation()

  const { result, jobTitle, jobId } = location.state || {}

  const coverLetter = useMemo(() => pick(result, [
    'cover_letter', 'coverLetter', 'letter', 'application_letter',
  ]), [result])
  const matchScore = useMemo(() => formatScore(pick(result, [
    'match_score', 'matchScore', 'score', 'fit_score',
  ])), [result])
  const reasoning = useMemo(() => pick(result, ['reason', 'reasoning', 'analysis']), [result])

  return (
    <Scene>
      <Board maxWidth={780}>
        <NavBar role="jobseeker" />

        <div style={{ textAlign: 'center', margin: '14px 0 18px' }}>
          <Ribbon color="app-green" size={20}>✅ 投递成功</Ribbon>
        </div>

        <div style={{
          background: '#f7f3df',
          border: '1.5px solid var(--border-soft)',
          borderRadius: 20,
          padding: '24px 26px',
          boxShadow: 'var(--elev-sm)',
          textAlign: 'center',
          marginBottom: 18,
        }}>
          <div style={{ fontSize: 48, lineHeight: 1, marginBottom: 8 }}>📨</div>
          <div style={{
            fontSize: 20,
            fontWeight: 800,
            color: 'var(--text)',
            marginBottom: 8,
          }}>
            你的简历已经送达
          </div>
          <div style={{
            fontSize: 14,
            fontWeight: 600,
            color: 'var(--text-muted)',
            lineHeight: 1.65,
          }}>
            {jobTitle
              ? <>已成功投递「<strong style={{ color: 'var(--text)' }}>{jobTitle}</strong>」</>
              : '已成功投递该岗位'}
            {jobId && <span style={{ display: 'block', fontSize: 12, marginTop: 4, color: 'var(--text-disabled)' }}>JOB · {jobId}</span>}
          </div>
        </div>

        {matchScore && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr',
            gap: 12,
            marginBottom: 18,
          }}>
            <div style={{
              padding: '18px 22px',
              background: 'rgba(255, 255, 255, 0.6)',
              border: '1.5px solid var(--border-soft)',
              borderRadius: 20,
              textAlign: 'center',
              boxShadow: 'var(--elev-sm)',
            }}>
              <div style={{
                fontSize: 11.5,
                fontWeight: 800,
                color: 'var(--text-muted)',
                letterSpacing: '0.04em',
                marginBottom: 6,
              }}>
                🎯 匹配度评分
              </div>
              <div style={{
                fontSize: 36,
                fontWeight: 900,
                color: 'var(--success-active)',
                fontVariantNumeric: 'tabular-nums',
                lineHeight: 1.1,
              }}>
                {matchScore}
              </div>
              {reasoning && (
                <div style={{
                  fontSize: 13,
                  fontWeight: 500,
                  color: 'var(--text-body)',
                  marginTop: 10,
                  lineHeight: 1.6,
                }}>
                  {typeof reasoning === 'string' ? reasoning : JSON.stringify(reasoning)}
                </div>
              )}
            </div>
          </div>
        )}

        {coverLetter && (
          <div style={{
            background: 'rgba(255, 255, 255, 0.6)',
            border: '1.5px solid var(--border-soft)',
            borderRadius: 20,
            padding: '20px 24px',
            boxShadow: 'var(--elev-sm)',
            marginBottom: 18,
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 12,
            }}>
              <div className="avatar indigo sm">
                <Icon name="bot" size={14} />
              </div>
              <div style={{
                fontSize: 12.5,
                fontWeight: 800,
                color: 'var(--text-muted)',
                letterSpacing: '0.04em',
              }}>
                AI 为你起草的求职信
              </div>
            </div>
            <div style={{
              fontSize: 14,
              fontWeight: 500,
              color: 'var(--text-body)',
              lineHeight: 1.75,
              whiteSpace: 'pre-wrap',
              minHeight: 80,
            }}>
              <StreamText text={String(coverLetter)} speed={14} />
            </div>
          </div>
        )}

        {!result && (
          <div className="chat-error" style={{ marginBottom: 18 }}>
            未收到投递返回，请从岗位详情重新尝试。
          </div>
        )}

        <div style={{
          display: 'flex',
          justifyContent: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => navigate('/jobseeker/profile')}
          >
            <Icon name="user" size={15} /> 我的资料卡
          </button>
          <button
            type="button"
            className="btn btn-soft"
            onClick={() => navigate('/jobseeker')}
          >
            返回岗位广场 <Icon name="arrow" size={16} />
          </button>
        </div>
      </Board>
    </Scene>
  )
}
