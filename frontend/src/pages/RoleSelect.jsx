import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Ribbon from '../components/Ribbon'
import Icon from '../components/Icon'
import { useLang } from '../i18n/LanguageProvider'

function useRoleCards(t) {
  return {
    EMPLOYER: {
      role: 'ent',
      icon: '🏢',
      title: t('roleSelect.employer.title'),
      sub: t('roleSelect.employer.sub'),
      steps: [
        t('roleSelect.employer.step1'),
        t('roleSelect.employer.step2'),
        t('roleSelect.employer.step3'),
      ],
      cta: t('roleSelect.enter'),
      to: '/employer/hub',
    },
    SEEKER: {
      role: 'cre',
      icon: '👤',
      title: t('roleSelect.jobseeker.title'),
      sub: t('roleSelect.jobseeker.sub'),
      steps: [
        t('roleSelect.jobseeker.step1'),
        t('roleSelect.jobseeker.step2'),
        t('roleSelect.jobseeker.step3'),
      ],
      cta: t('roleSelect.enter'),
      to: '/jobseeker',
    },
    CREATOR: {
      role: 'cre',
      icon: '🎨',
      title: t('roleSelect.creator.title'),
      sub: t('roleSelect.creator.sub'),
      steps: [
        t('roleSelect.creator.step1'),
        t('roleSelect.creator.step2'),
        t('roleSelect.creator.step3'),
      ],
      cta: t('roleSelect.enter'),
      to: '/creator',
    },
  }
}

export default function RoleSelect() {
  const navigate = useNavigate()
  const { t } = useLang()
  const { EMPLOYER, SEEKER, CREATOR } = useRoleCards(t)
  return (
    <Scene>
      <div className="roleselect">
        <div className="guild-brand">
          <h1 className="guild-logo"><span className="leaf">🍃</span> HireNet</h1>
          <p className="guild-sub">{t('roleSelect.tagline')}</p>
          <div className="guild-pill">{t('roleSelect.pill')}</div>
        </div>

        <div className="rs-board-title">
          <Ribbon color="app-teal" size={22}>{t('roleSelect.chooseIdentity')}</Ribbon>
        </div>

        <div className="role-grid">
          <RoleCard d={EMPLOYER} onEnter={() => navigate(EMPLOYER.to)} />
          <RoleCard d={SEEKER} onEnter={() => navigate(SEEKER.to)} />
          <RoleCard d={CREATOR} onEnter={() => navigate(CREATOR.to)} />
        </div>

        <div className="rs-foot">
          <a
            href="/agents"
            onClick={(e) => { e.preventDefault(); navigate('/agents') }}
          >
            {t('roleSelect.footerLink')} <Icon name="arrow" size={14} />
          </a>
        </div>
      </div>
    </Scene>
  )
}

function RoleCard({ d, onEnter }) {
  return (
    <div className={`role-card ${d.role}`} onClick={onEnter}>
      <div className={`role-ic ${d.role}`}>{d.icon}</div>
      <h2>{d.title}</h2>
      <p className="rc-sub">{d.sub}</p>
      <div className="role-steps">
        {d.steps.map((s, i) => (
          <div className="role-step" key={i}>
            <span className="rs-n">▸</span>
            <span className="rs-t">{s}</span>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="btn btn-primary btn-lg btn-block rc-btn"
        onClick={(e) => { e.stopPropagation(); onEnter() }}
      >
        {d.cta} <Icon name="arrow" size={16} />
      </button>
    </div>
  )
}
