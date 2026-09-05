import { useEffect, useState } from 'react'
import { fetchIdentities, setIdentity, hasJwtToken } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

/**
 * IdentitySwitcher — bottom-left floating capsule for Demo identity switching.
 * Mounts once at App level; subscribes its own state to /api/demo/identities.
 *
 * Visual: half-transparent rounded pill with the current avatar + name.
 *         Clicking opens a stacked list of the 4 demo identities; pick one
 *         and we POST /api/demo/identity, then reload to let every page
 *         re-fetch with the new caller_id.
 *
 * Phase 2 / U6: when a JWT is present, identity is real — switching makes no
 * sense, and the capsule is hidden entirely. Demo mode lights it back up.
 */
export default function IdentitySwitcher() {
  const { t, lang } = useLang()
  const ROLE_LABELS = {
    enterprise: t('identitySwitcher.roles.enterprise'),
    creator: t('identitySwitcher.roles.creator'),
    jobseeker: t('identitySwitcher.roles.jobseeker'),
  }
  const [open, setOpen] = useState(false)
  const [identities, setIdentities] = useState([])
  const [current, setCurrent] = useState(null)
  const [error, setError] = useState('')
  const [switching, setSwitching] = useState(false)
  const jwtActive = hasJwtToken()

  // Identity name/role fields are localised server-side, so re-fetch when
  // the language toggle moves. No dedicated loading indicator on this
  // floating capsule — the previous identities stay displayed until the
  // re-fetch resolves.
  useEffect(() => {
    if (jwtActive) return  // skip fetch when real auth is in play
    let cancelled = false
    fetchIdentities()
      .then((data) => {
        if (cancelled) return
        setIdentities(data?.identities ?? [])
        setCurrent(data?.current ?? null)
        setError('')
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || t('identitySwitcher.errors.loadFailed'))
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jwtActive, lang])

  if (jwtActive) return null

  async function handlePick(identity) {
    if (switching) return
    setSwitching(true)
    setError('')
    try {
      await setIdentity(identity.id)
      setCurrent(identity)
      setOpen(false)
      // Force-refresh so every page picks up the new identity from its own data fetch.
      window.location.reload()
    } catch (e) {
      setError(e.message || t('identitySwitcher.errors.switchFailed'))
      setSwitching(false)
    }
  }

  const displayName = current?.name ?? t('identitySwitcher.anonymous')
  const displayAvatar = current?.avatar ?? '👤'
  const roleLabel = ROLE_LABELS[current?.role] ?? ''

  return (
    <div style={WRAPPER_STYLE}>
      {open && (
        <div style={PANEL_STYLE} role="dialog" aria-label={t('identitySwitcher.switchIdentity')}>
          <div style={PANEL_HEADER_STYLE}>{t('identitySwitcher.switchIdentity')}</div>
          {identities.map((it) => {
            const active = current?.id === it.id
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => handlePick(it)}
                disabled={switching}
                style={{
                  ...ROW_STYLE,
                  background: active ? 'var(--primary-bg)' : 'rgba(255,255,255,0.7)',
                  borderColor: active ? '#b8ece6' : 'var(--border-soft)',
                  cursor: switching ? 'wait' : 'pointer',
                }}
              >
                <span style={ROW_AVATAR_STYLE}>{it.avatar}</span>
                <span style={{ flex: 1, textAlign: 'left' }}>
                  <span style={ROW_NAME_STYLE}>{it.name}</span>
                  <span style={ROW_ROLE_STYLE}>{ROLE_LABELS[it.role] ?? it.role}</span>
                </span>
                {active && <span style={{ fontWeight: 800, color: 'var(--primary-active)' }}>✓</span>}
              </button>
            )
          })}
          {error && <div style={ERROR_STYLE}>{error}</div>}
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={CAPSULE_STYLE}
        title={t('identitySwitcher.switchIdentity')}
      >
        <span style={CAPSULE_AVATAR_STYLE}>{displayAvatar}</span>
        <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
          <span style={CAPSULE_NAME_STYLE}>{displayName}</span>
          {roleLabel && <span style={CAPSULE_ROLE_STYLE}>{roleLabel}</span>}
        </span>
        <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--text-secondary)' }}>
          {open ? '▾' : '▴'}
        </span>
      </button>
    </div>
  )
}

const WRAPPER_STYLE = {
  position: 'fixed',
  left: 18,
  bottom: 18,
  zIndex: 9000,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-start',
  gap: 10,
  pointerEvents: 'none',
}

const CAPSULE_STYLE = {
  pointerEvents: 'auto',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 10,
  padding: '8px 14px 8px 8px',
  borderRadius: 'var(--pill)',
  background: 'rgba(255, 255, 255, 0.78)',
  backdropFilter: 'blur(6px)',
  WebkitBackdropFilter: 'blur(6px)',
  border: '1.5px solid var(--border-soft)',
  boxShadow: 'var(--elev-base)',
  fontFamily: 'var(--font)',
  fontWeight: 700,
  color: 'var(--text)',
  cursor: 'pointer',
  transition: 'transform 0.2s ease, box-shadow 0.2s ease',
}

const CAPSULE_AVATAR_STYLE = {
  width: 32,
  height: 32,
  borderRadius: '50%',
  background: 'var(--app-teal)',
  display: 'grid',
  placeItems: 'center',
  fontSize: 18,
  border: '2px solid rgba(255,255,255,0.85)',
  boxShadow: 'var(--elev-sm)',
}

const CAPSULE_NAME_STYLE = {
  fontSize: 13,
  fontWeight: 800,
  lineHeight: 1.2,
  color: 'var(--text)',
}

const CAPSULE_ROLE_STYLE = {
  fontSize: 10.5,
  fontWeight: 700,
  color: 'var(--text-muted)',
  letterSpacing: '0.04em',
}

const PANEL_STYLE = {
  pointerEvents: 'auto',
  background: 'rgba(255, 255, 255, 0.92)',
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
  border: '1.5px solid var(--border-soft)',
  borderRadius: 18,
  boxShadow: 'var(--elev-base)',
  padding: '12px 12px',
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  minWidth: 240,
}

const PANEL_HEADER_STYLE = {
  fontSize: 11,
  fontWeight: 800,
  color: 'var(--text-muted)',
  letterSpacing: '0.06em',
  padding: '2px 6px 4px',
  borderBottom: '1px dashed var(--border-soft)',
  marginBottom: 4,
}

const ROW_STYLE = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '8px 10px',
  border: '1.5px solid var(--border-soft)',
  borderRadius: 12,
  fontFamily: 'var(--font)',
  fontWeight: 700,
  color: 'var(--text)',
  transition: 'background 0.15s ease',
}

const ROW_AVATAR_STYLE = {
  width: 30,
  height: 30,
  borderRadius: '50%',
  background: 'var(--app-yellow)',
  display: 'grid',
  placeItems: 'center',
  fontSize: 17,
  border: '2px solid rgba(255,255,255,0.85)',
  flex: '0 0 auto',
}

const ROW_NAME_STYLE = {
  display: 'block',
  fontSize: 13,
  fontWeight: 800,
  color: 'var(--text)',
  lineHeight: 1.25,
}

const ROW_ROLE_STYLE = {
  display: 'block',
  fontSize: 10.5,
  fontWeight: 700,
  color: 'var(--text-muted)',
  letterSpacing: '0.04em',
  marginTop: 1,
}

const ERROR_STYLE = {
  fontSize: 11.5,
  fontWeight: 700,
  color: 'var(--warning-active)',
  padding: '4px 6px',
}
