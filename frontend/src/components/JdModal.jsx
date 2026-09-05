import { useEffect, useMemo, useState } from 'react'
import Icon from './Icon'
import Ribbon from './Ribbon'
import { publishJob } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

/**
 * JdModal — Markdown JD preview + publish to the job pool.
 *
 * Triggered from HiringTaskCard's "Generate JD" button in AnalysisReport.
 * Composes a JD draft from the task + jd_report shape returned by
 * /api/analyze/decide and lets the user publish it via POST /api/jobs/publish.
 */
export default function JdModal({ task, decision, jdReport, onClose }) {
  const { t } = useLang()
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState('')
  const [published, setPublished] = useState(null) // { job_id }

  // Pull the matching job_design from jd_report if generate_jd_report ran;
  // otherwise fall back to a JD built from the task + decision fields.
  const jobDesign = useMemo(() => findJobDesign(task, jdReport), [task, jdReport])
  const jdMarkdown = useMemo(
    () => buildJdMarkdown(task, decision, jobDesign, t),
    [task, decision, jobDesign, t],
  )

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function handlePublish() {
    if (publishing) return
    setPublishing(true)
    setError('')
    try {
      /* Forward the structured fields from the JD agent so candidates see
         the same requirements / skills / responsibilities the employer
         agreed to, not just the rendered markdown blob. */
      const res = await publishJob({
        jd: jdMarkdown,
        job_id: jobDesign?.job_id,
        company: jobDesign?.company,
        job_title: jobDesign?.job_title ?? task?.name,
        required_skills: jobDesign?.required_skills,
        nice_to_have_skills: jobDesign?.nice_to_have_skills,
        core_responsibilities: jobDesign?.core_responsibilities,
        salary_range: jobDesign?.salary_range,
        work_type: jobDesign?.work_type,
      })
      setPublished({ job_id: res.job_id })
    } catch (e) {
      setError(e.message || t('jdModal.errors.publishFailed'))
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div style={BACKDROP} onClick={onClose}>
      <div style={MODAL} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t('jdModal.ariaLabel')}>
        <div style={{ textAlign: 'center', marginBottom: 14 }}>
          <Ribbon color="app-yellow" size={18}>📝 {t('jdModal.draftTitle')}</Ribbon>
        </div>

        <pre style={JD_BLOCK}>{jdMarkdown}</pre>

        {error && <div style={ERROR_BOX}>{error}</div>}
        {published && (
          <div style={SUCCESS_BOX}>
            ✅ {t('jdModal.publishedPrefix')}（job_id：<code>{published.job_id}</code>）
          </div>
        )}

        <div style={ACTIONS}>
          {published ? (
            <button type="button" className="btn btn-primary" onClick={onClose}>
              <Icon name="check" size={15} /> {t('jdModal.done')}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handlePublish}
                disabled={publishing}
              >
                {publishing ? t('jdModal.publishing') : `📤 ${t('jdModal.publish')}`}
              </button>
              <button type="button" className="btn btn-ghost" onClick={onClose}>
                {t('jdModal.close')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function findJobDesign(task, jdReport) {
  if (!jdReport || !Array.isArray(jdReport.job_designs)) return null
  return (
    jdReport.job_designs.find((j) => j.task_id === task?.id) ||
    jdReport.job_designs.find((j) => j.job_title === task?.name) ||
    jdReport.job_designs[0] ||
    null
  )
}

function buildJdMarkdown(task, decision, jobDesign, t) {
  if (jobDesign?.markdown) return jobDesign.markdown

  const title = jobDesign?.job_title ?? task?.name ?? t('jdModal.fallback.title')
  const company = jobDesign?.company ?? t('jdModal.fallback.company')
  const summary = jobDesign?.summary ?? task?.description ?? ''
  const salary = jobDesign?.salary
    ?? decision?.recommendation?.cost_hint
    ?? t('jdModal.fallback.salary')
  const responsibilities = jobDesign?.core_responsibilities ?? []
  /* Match the JD agent's output schema (required_skills / nice_to_have_skills).
     The legacy `requirements` / `nice_to_have` keys were a render-only
     compromise that disconnected the modal from real LLM output — keep both
     reads so a hand-built jobDesign without the schema fields still works. */
  const requirements = jobDesign?.required_skills ?? jobDesign?.requirements ?? []
  const nice = jobDesign?.nice_to_have_skills ?? jobDesign?.nice_to_have ?? []

  const lines = [
    `# ${title}`,
    '',
    `**${t('jdModal.headings.company')}：** ${company}`,
    salary ? `**${t('jdModal.headings.salary')}：** ${salary}` : '',
    '',
    summary ? `## ${t('jdModal.headings.summary')}\n\n${summary}` : '',
    responsibilities.length
      ? `## ${t('jdModal.headings.responsibilities')}\n\n` + responsibilities.map((r) => `- ${r}`).join('\n')
      : '',
    requirements.length
      ? `## ${t('jdModal.headings.requirements')}\n\n` + requirements.map((r) => `- ${r}`).join('\n')
      : '',
    nice.length
      ? `## ${t('jdModal.headings.niceToHave')}\n\n` + nice.map((r) => `- ${r}`).join('\n')
      : '',
  ]
  return lines.filter(Boolean).join('\n\n')
}

const BACKDROP = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(38, 30, 22, 0.45)',
  backdropFilter: 'blur(2px)',
  WebkitBackdropFilter: 'blur(2px)',
  display: 'grid',
  placeItems: 'center',
  zIndex: 9500,
  padding: 24,
}

const MODAL = {
  width: 'min(640px, 100%)',
  maxHeight: '88vh',
  overflow: 'auto',
  background: '#fbf6e7',
  border: '1.5px solid var(--border-soft)',
  borderRadius: 22,
  boxShadow: 'var(--elev-lg, 0 18px 40px rgba(0,0,0,0.18))',
  padding: '22px 26px 24px',
  fontFamily: 'var(--font)',
}

const JD_BLOCK = {
  whiteSpace: 'pre-wrap',
  fontFamily: 'var(--font)',
  fontSize: 13.5,
  lineHeight: 1.7,
  color: 'var(--text)',
  background: 'rgba(255,255,255,0.55)',
  border: '1.5px solid var(--border-soft)',
  borderRadius: 16,
  padding: '18px 20px',
  margin: 0,
}

const ERROR_BOX = {
  marginTop: 12,
  padding: '10px 14px',
  background: '#fde6e1',
  border: '1.5px solid #f3b8ad',
  borderRadius: 12,
  fontSize: 13,
  fontWeight: 700,
  color: '#a23a25',
}

const SUCCESS_BOX = {
  marginTop: 12,
  padding: '10px 14px',
  background: '#e9f4dd',
  border: '1.5px solid #c2dfa0',
  borderRadius: 12,
  fontSize: 13,
  fontWeight: 700,
  color: 'var(--success-active)',
}

const ACTIONS = {
  marginTop: 16,
  display: 'flex',
  gap: 12,
  justifyContent: 'center',
  flexWrap: 'wrap',
}
