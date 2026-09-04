import patternData from './backendStrings.json'

/**
 * Layer 2 (WP-I18N spec §2) — fixed backend strings.
 *
 * `app/agents/decision_policy.py` (plus `task_analysis.EVALUATION_FALLBACK_REASON`)
 * emits a small, FIXED set of Chinese strings verbatim — they are a UI
 * contract, not LLM prose. `patterns` here is the canonical mirror of those
 * strings, kept in a plain JSON file (`backendStrings.json`) so
 * `tests/test_i18n_backend_strings.py` can load the exact same list from
 * Python and assert every canonical string is matched by exactly one
 * pattern. Do not hand-translate these cards — they must be pattern-matched.
 */

const COMPILED_PATTERNS = patternData.patterns.map((pattern) => ({
  ...pattern,
  regex: pattern.kind === 'regex' ? new RegExp(pattern.source) : null,
}))

/**
 * Translate one fixed backend string into English by pattern match.
 *
 * Returns `text` unchanged when `lang !== 'en'`, when `text` isn't a string,
 * or when nothing matches (LLM-generated prose — task names, JD text — is
 * never touched here; only the fixed decision-policy strings are).
 */
export function translateBackend(text, lang) {
  if (lang !== 'en' || typeof text !== 'string') return text

  for (const pattern of COMPILED_PATTERNS) {
    if (pattern.kind === 'literal') {
      if (text === pattern.source) return pattern.en
      continue
    }
    const match = pattern.regex ? text.match(pattern.regex) : null
    if (match) {
      return pattern.en
        .replace('{name}', match[1] ?? '')
        .replace('{pct}', match[2] ?? '')
    }
  }
  return text
}

export const BACKEND_STRING_PATTERNS = patternData.patterns
