import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import en from './en.json'
import zh from './zh.json'

/**
 * WP-I18N — bilingual UI provider.
 *
 * Default language is English (demo audience is Australia); the choice
 * persists in localStorage("hirenet.lang") and is read/written inside
 * try/catch since a private-browsing tab (or a locked-down embed) can throw
 * on localStorage access — losing the preference must never crash the app.
 */

const STORAGE_KEY = 'hirenet.lang'
const DEFAULT_LANG = 'en'
const DICTIONARIES = { en, zh }

const LanguageContext = createContext(null)

function readStoredLang() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'zh') return stored
  } catch {
    // localStorage unavailable — fall back to the default silently.
  }
  return DEFAULT_LANG
}

function writeStoredLang(lang) {
  try {
    window.localStorage.setItem(STORAGE_KEY, lang)
  } catch {
    // Persistence is a nice-to-have; losing it must not break the toggle.
  }
}

function resolveKey(dict, key) {
  return key
    .split('.')
    .reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), dict)
}

function interpolate(template, vars) {
  if (!vars || typeof template !== 'string') return template
  return template.replace(/\{(\w+)\}/g, (match, name) => (
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match
  ))
}

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(readStoredLang)

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((next) => {
    if (next !== 'en' && next !== 'zh') return
    setLangState(next)
    writeStoredLang(next)
  }, [])

  const t = useCallback((key, vars) => {
    const dict = DICTIONARIES[lang] ?? DICTIONARIES[DEFAULT_LANG]
    const value = resolveKey(dict, key)
    if (value !== undefined) return interpolate(value, vars)
    // Missing key in the active dictionary: fall back to the default
    // language rather than leaking the raw key into the UI.
    const fallback = resolveKey(DICTIONARIES[DEFAULT_LANG], key)
    return fallback !== undefined ? interpolate(fallback, vars) : key
  }, [lang])

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  )
}

// Co-located with the Provider on purpose (context + its hook belong
// together); this only affects Vite's Fast Refresh granularity, not
// correctness, so the rule is disabled for this one export.
// eslint-disable-next-line react-refresh/only-export-components
export function useLang() {
  const ctx = useContext(LanguageContext)
  if (!ctx) {
    throw new Error('useLang() must be called inside a <LanguageProvider>')
  }
  return ctx
}
