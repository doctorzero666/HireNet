import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import Icon from '../components/Icon'
import { fetchJobs } from '../services/api'

function normalizeJobs(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.jobs)) return payload.jobs
  if (Array.isArray(payload?.items)) return payload.items
  return []
}

function pickField(job, keys, fallback = '') {
  for (const k of keys) {
    const v = job?.[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return fallback
}

function formatSalaryRange(obj) {
  if (!obj || typeof obj !== 'object') return ''
  const { min, max, unit } = obj
  const hasMin = min !== undefined && min !== null && min !== ''
  const hasMax = max !== undefined && max !== null && max !== ''
  if (!hasMin && !hasMax) return ''
  const range = hasMin && hasMax ? `${min}-${max}` : `${hasMin ? min : '—'}-${hasMax ? max : '—'}`
  return unit ? `${range} ${unit}` : range
}

function salaryText(job) {
  const explicit = pickField(job, ['salary_range', 'salary', 'compensation'])
  if (explicit) {
    if (typeof explicit === 'object') return formatSalaryRange(explicit)
    return explicit
  }
  const min = pickField(job, ['salary_min', 'min_salary'])
  const max = pickField(job, ['salary_max', 'max_salary'])
  if (min || max) return `${min || '—'} ~ ${max || '—'}`
  return ''
}

export default function JobSeekerHome() {
  const navigate = useNavigate()
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchJobs()
      .then((data) => {
        if (cancelled) return
        setJobs(normalizeJobs(data))
        setLoading(false)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || '岗位加载失败')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  return (
    <Scene>
      <Board maxWidth={860}>
        <NavBar role="jobseeker" />

        <div style={{ textAlign: 'center', margin: '14px 0 6px' }}>
          <Ribbon color="app-teal" size={22}>🏝️ 岗位广场</Ribbon>
        </div>
        <p style={{
          textAlign: 'center',
          fontSize: 14,
          color: 'var(--text-muted)',
          fontWeight: 600,
          lineHeight: 1.65,
          margin: '12px auto 24px',
          maxWidth: 520,
        }}>
          挑一份感兴趣的工作，让你的技能被这座岛屿看见
        </p>

        {loading && (
          <div className="generating">
            <div className="spinner" />
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)' }}>
              岛屿信使派送中…
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="chat-error" style={{ marginBottom: 16 }}>
            {error}
          </div>
        )}

        {!loading && !error && jobs.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '40px 20px',
            background: 'rgba(255, 255, 255, 0.6)',
            border: '1.5px solid var(--border-soft)',
            borderRadius: 20,
            boxShadow: 'var(--elev-sm)',
          }}>
            <div style={{ fontSize: 56, lineHeight: 1, marginBottom: 14 }}>🏝️</div>
            <div style={{ fontWeight: 800, fontSize: 16, color: 'var(--text)' }}>
              暂无开放岗位
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', marginTop: 6 }}>
              下一艘招聘船即将靠岸，再来看看吧
            </div>
          </div>
        )}

        {!loading && !error && jobs.length > 0 && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            marginBottom: 24,
          }}>
            {jobs.map((job, i) => {
              const jobId = pickField(job, ['job_id', 'id', 'jd_id'], `job-${i}`)
              const title = pickField(job, ['title', 'job_title', 'name'], '未命名岗位')
              const company = pickField(job, ['company', 'company_name', 'employer'], '')
              const salary = salaryText(job)
              const desc = pickField(job, ['description', 'summary', 'jd', 'detail'], '')
              const matchScore = pickField(job, ['match_score', 'match', 'score'], null)

              return (
                <JobCard
                  key={jobId}
                  title={title}
                  company={company}
                  salary={salary}
                  desc={desc}
                  matchScore={matchScore}
                  onClick={() => navigate(`/jobseeker/job/${encodeURIComponent(jobId)}`, { state: { job } })}
                />
              )
            })}
          </div>
        )}

        <div style={{ textAlign: 'center', marginTop: 18 }}>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => navigate('/jobseeker/profile')}
          >
            <Icon name="user" size={16} /> 查看我的资料卡
          </button>
        </div>
      </Board>
    </Scene>
  )
}

function JobCard({ title, company, salary, desc, matchScore, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        textAlign: 'left',
        background: '#f7f3df',
        border: '1.5px solid var(--border-soft)',
        borderRadius: 20,
        padding: 20,
        cursor: 'pointer',
        boxShadow: 'var(--elev-sm)',
        transition: 'all 0.25s var(--ease)',
        font: 'inherit',
        color: 'var(--text-body)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = 'var(--elev-base)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = 'var(--elev-sm)'
      }}
    >
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 14,
        marginBottom: 8,
      }}>
        <div style={{
          fontWeight: 700,
          fontSize: 17,
          color: 'var(--text)',
          lineHeight: 1.35,
        }}>
          {title}
        </div>
        {matchScore !== null && matchScore !== undefined && (
          <span style={{
            flex: '0 0 auto',
            fontSize: 11.5,
            fontWeight: 800,
            color: 'var(--success-active)',
            background: '#e9f4dd',
            borderRadius: 'var(--pill)',
            padding: '3px 12px',
            whiteSpace: 'nowrap',
          }}>
            🎯 匹配 {typeof matchScore === 'number' ? `${Math.round(matchScore * (matchScore <= 1 ? 100 : 1))}%` : matchScore}
          </span>
        )}
      </div>

      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 12,
        fontSize: 13,
        fontWeight: 700,
        color: 'var(--text-body)',
        marginBottom: 10,
      }}>
        {company && <span>🏢 {company}</span>}
        {salary && <span style={{ color: 'var(--money)' }}>💰 {salary}</span>}
      </div>

      {desc && (
        <p style={{
          fontSize: 13,
          fontWeight: 500,
          color: 'var(--text-muted)',
          lineHeight: 1.6,
          margin: 0,
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}>
          {desc}
        </p>
      )}

      <div style={{
        display: 'flex',
        justifyContent: 'flex-end',
        alignItems: 'center',
        gap: 6,
        fontSize: 12.5,
        fontWeight: 800,
        color: 'var(--primary-active)',
        marginTop: 12,
      }}>
        查看详情 <Icon name="arrow" size={14} />
      </div>
    </button>
  )
}
