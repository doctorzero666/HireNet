import '../styles/nav.css'
import { useNavigate, useLocation } from 'react-router-dom'
import { useLang } from '../i18n/LanguageProvider'

// The language toggle is rendered once, globally, from App.jsx (fixed
// position) rather than duplicated inside NavBar — NavBar isn't mounted on
// every route (RoleSelect, Login, EmployerHub have none), so a single
// App-level toggle is the only way to guarantee it is present everywhere
// without a second instance appearing on the pages that do have a NavBar.

function useRolePresets(t) {
  return {
    employer: {
      label: 'EMPLOYER',
      links: [
        { label: t('nav.employer.requirementAnalysis'), to: '/employer' },
        { label: t('nav.employer.myTasks'), comingSoon: true },
        { label: t('nav.employer.dashboard'), to: '/employer/dashboard' },
      ],
    },
    creator: {
      label: 'CREATOR',
      links: [
        { label: t('nav.creator.myAgents'), to: '/creator' },
        { label: t('nav.creator.ledger'), to: '/creator/ledger' },
      ],
    },
    jobseeker: {
      label: 'JOBSEEKER',
      links: [
        { label: t('nav.jobseeker.jobBoard'), to: '/jobseeker' },
        { label: t('nav.jobseeker.myProfile'), to: '/jobseeker/profile' },
        { label: t('nav.jobseeker.applications'), comingSoon: true },
      ],
    },
    'agent-world': {
      label: 'AGENT WORLD',
      links: [
        { label: t('nav.agentWorld.roleSelect'), to: '/' },
        { label: t('nav.agentWorld.iAmCreator'), to: '/creator' },
        { label: t('nav.agentWorld.iAmEmployer'), to: '/employer/hub' },
      ],
    },
  }
}

/**
 * NavBar — top wooden-plank navigation bar
 * props:
 *   role: 'employer' | 'creator' | string  (presets above; otherwise raw label)
 *   links: override the default links (optional)
 *   onBack: () => void   override the default "back to /"
 */
export default function NavBar({ role, links, onBack }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useLang()

  const preset = useRolePresets(t)[role]
  const finalLinks = links ?? preset?.links ?? []
  const roleLabel = preset?.label ?? role
  const handleBack = onBack ?? (() => navigate('/'))

  return (
    <nav className="nav-bar">
      <span className="nav-logo">HIRENET</span>

      <div className="nav-links">
        {finalLinks.map((link, i) => {
          if (link.comingSoon) {
            return (
              <a
                key={i}
                className="nav-link nav-link--disabled"
                href="#"
                title={t('nav.comingSoon')}
                onClick={(e) => e.preventDefault()}
              >
                {link.label}
              </a>
            )
          }
          const active =
            link.active ??
            (link.to && location.pathname === link.to)
          return (
            <a
              key={i}
              className={`nav-link ${active ? 'nav-link--active' : ''}`}
              href={link.href || link.to || '#'}
              onClick={(e) => {
                if (link.onClick) {
                  e.preventDefault()
                  link.onClick()
                } else if (link.to) {
                  e.preventDefault()
                  navigate(link.to)
                }
              }}
            >
              {link.label}
            </a>
          )
        })}
      </div>

      <button type="button" className="nav-back-btn" onClick={handleBack}>
        ← BACK
      </button>

      {roleLabel && <span className="nav-role">{roleLabel}</span>}
    </nav>
  )
}
