import { useEffect, useState } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import Ribbon from '../components/Ribbon'
import Icon from '../components/Icon'
import { fetchJobs, fetchCandidates, applyToJob } from '../services/api'

function normalizeJobs(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.jobs)) return payload.jobs
  if (Array.isArray(payload?.items)) return payload.items
  return []
}

function pick(job, keys, fallback = '') {
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
  const explicit = pick(job, ['salary_range', 'salary', 'compensation'])
  if (explicit) {
    if (typeof explicit === 'object') return formatSalaryRange(explicit)
    return explicit
  }
  const min = pick(job, ['salary_min', 'min_salary'])
  const max = pick(job, ['salary_max', 'max_salary'])
  if (min || max) return `${min || '—'} ~ ${max || '—'}`
  return ''
}

export default function JobDetail() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const [job, setJob] = useState(location.state?.job || null)
  const [loading, setLoading] = useState(!location.state?.job)
  const [error, setError] = useState('')
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState('')
  const [candidateId, setCandidateId] = useState(null)

  useEffect(() => {
    if (job) return
    let cancelled = false
    fetchJobs()
      .then((data) => {
        if (cancelled) return
        const list = normalizeJobs(data)
        const found = list.find((j) => {
          const id = pick(j, ['job_id', 'id', 'jd_id'])
          return String(id) === String(jobId)
        })
        if (found) setJob(found)
        else setError('未找到该岗位')
        setLoading(false)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || '岗位加载失败')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [job, jobId])

  useEffect(() => {
    let cancelled = false
    fetchCandidates()
      .then((data) => {
        if (cancelled) return
        const first = (data?.candidates || [])[0]
        if (first?.id) setCandidateId(first.id)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const handleApply = async () => {
    if (applying) return
    if (!candidateId) {
      setApplyError('候选人资料尚未就绪，请稍后再试')
      return
    }
    setApplying(true)
    setApplyError('')
    try {
      const result = await applyToJob({
        candidate_id: candidateId,
        job_design: job,
      })
      navigate('/jobseeker/result', {
        state: {
          result,
          jobTitle: pick(job, ['title', 'job_title', 'name'], '该岗位'),
          jobId,
        },
      })
    } catch (e) {
      setApplyError(e.message || '投递失败，请稍后再试')
      setApplying(false)
    }
  }

  const title = pick(job, ['title', 'job_title', 'name'], '岗位详情')
  const company = pick(job, ['company', 'company_name', 'employer'], '')
  const salary = salaryText(job)
  const location_ = pick(job, ['location', 'city', 'work_location'], '')
  /* publish_job stores the JD blob as `job_description` (matches the backend
     schema). Without it in the lookup list, a published JD renders an empty
     description even though the API returned one. */
  const desc = pick(job, ['job_description', 'description', 'summary', 'jd', 'detail'], '')
  const requirements = pick(job, ['requirements', 'required_skills'], null)
  const skills = pick(job, ['skills', 'tags', 'nice_to_have_skills'], null)

  return (
    <Scene>
      <Board maxWidth={780}>
        <NavBar role="jobseeker" />

        <div style={{ textAlign: 'center', margin: '14px 0 18px' }}>
          <Ribbon color="app-yellow" size={20}>📜 岗位详情</Ribbon>
        </div>

        {loading && (
          <div className="generating">
            <div className="spinner" />
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)' }}>
              翻开岗位文卷…
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="chat-error" style={{ marginBottom: 16 }}>{error}</div>
        )}

        {!loading && !error && job && (
          <>
            <div style={{
              background: '#f7f3df',
              border: '1.5px solid var(--border-soft)',
              borderRadius: 20,
              padding: '22px 24px',
              boxShadow: 'var(--elev-sm)',
              marginBottom: 18,
            }}>
              <div style={{
                fontWeight: 700,
                fontSize: 22,
                color: 'var(--text)',
                lineHeight: 1.35,
                marginBottom: 12,
              }}>
                {title}
              </div>

              <div style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 10,
                marginBottom: 16,
              }}>
                {company && <MetaChip icon="🏢" text={company} />}
                {location_ && <MetaChip icon="📍" text={location_} />}
                {salary && <MetaChip icon="💰" text={salary} accent="var(--money)" />}
              </div>

              {desc && (
                <div>
                  <SectionTitle>岗位描述</SectionTitle>
                  <p style={{
                    fontSize: 14,
                    lineHeight: 1.7,
                    color: 'var(--text-body)',
                    fontWeight: 500,
                    margin: 0,
                    whiteSpace: 'pre-wrap',
                  }}>
                    {desc}
                  </p>
                </div>
              )}

              {requirements && (
                <div style={{ marginTop: 18 }}>
                  <SectionTitle>要求</SectionTitle>
                  <RequirementsBlock data={requirements} />
                </div>
              )}

              {skills && (
                <div style={{ marginTop: 18 }}>
                  <SectionTitle>关键技能</SectionTitle>
                  <SkillsRow data={skills} />
                </div>
              )}
            </div>

            {applyError && (
              <div className="chat-error" style={{ marginBottom: 12 }}>{applyError}</div>
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
                onClick={() => navigate('/jobseeker')}
                disabled={applying}
              >
                ◂ 返回广场
              </button>
              <button
                type="button"
                className="btn btn-soft btn-lg"
                onClick={handleApply}
                disabled={applying}
              >
                {applying ? '投递中…' : '一键投递'} <Icon name="rocket" size={16} />
              </button>
            </div>
          </>
        )}
      </Board>
    </Scene>
  )
}

function MetaChip({ icon, text, accent }) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      fontSize: 13,
      fontWeight: 700,
      color: accent || 'var(--text-body)',
      background: 'rgba(255, 255, 255, 0.7)',
      border: '1.5px solid var(--border-soft)',
      borderRadius: 'var(--pill)',
      padding: '4px 12px',
    }}>
      <span aria-hidden="true">{icon}</span> {text}
    </span>
  )
}

function SectionTitle({ children }) {
  return (
    <div style={{
      fontSize: 12.5,
      fontWeight: 800,
      color: 'var(--text-muted)',
      letterSpacing: '0.04em',
      marginBottom: 8,
    }}>
      {children}
    </div>
  )
}

function RequirementsBlock({ data }) {
  if (Array.isArray(data)) {
    return (
      <ul style={{
        margin: 0,
        paddingLeft: 20,
        fontSize: 14,
        lineHeight: 1.7,
        color: 'var(--text-body)',
        fontWeight: 500,
      }}>
        {data.map((r, i) => <li key={i}>{typeof r === 'string' ? r : JSON.stringify(r)}</li>)}
      </ul>
    )
  }
  return (
    <p style={{
      fontSize: 14,
      lineHeight: 1.7,
      color: 'var(--text-body)',
      fontWeight: 500,
      margin: 0,
      whiteSpace: 'pre-wrap',
    }}>{String(data)}</p>
  )
}

function SkillsRow({ data }) {
  const list = Array.isArray(data) ? data : String(data).split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {list.map((s, i) => (
        <span key={i} style={{
          fontSize: 12.5,
          fontWeight: 700,
          color: 'var(--primary-active)',
          background: 'var(--primary-bg)',
          border: '2px solid #b8ece6',
          borderRadius: 'var(--pill)',
          padding: '3px 12px',
        }}>
          {typeof s === 'string' ? s : JSON.stringify(s)}
        </span>
      ))}
    </div>
  )
}
