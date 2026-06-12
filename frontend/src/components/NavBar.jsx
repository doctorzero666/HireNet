import '../styles/nav.css'
import { useNavigate, useLocation } from 'react-router-dom'

const ROLE_PRESETS = {
  employer: {
    label: 'EMPLOYER',
    links: [
      { label: '需求分析', to: '/employer' },
      { label: '我的任务', comingSoon: true },
      { label: '控制台', to: '/employer/dashboard' },
    ],
  },
  creator: {
    label: 'CREATOR',
    links: [
      { label: '我的 Agent', to: '/creator' },
      { label: '收益账本', comingSoon: true },
    ],
  },
  jobseeker: {
    label: 'JOBSEEKER',
    links: [
      { label: '岗位广场', to: '/jobseeker' },
      { label: '我的资料', to: '/jobseeker/profile' },
      { label: '投递记录', comingSoon: true },
    ],
  },
}

/**
 * NavBar — 顶部木条导航
 * props:
 *   role: 'employer' | 'creator' | string  (presets above; otherwise raw label)
 *   links: 覆盖默认 links（可选）
 *   onBack: () => void   覆盖默认回到 /
 */
export default function NavBar({ role, links, onBack }) {
  const navigate = useNavigate()
  const location = useLocation()

  const preset = ROLE_PRESETS[role]
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
                title="即将上线"
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
