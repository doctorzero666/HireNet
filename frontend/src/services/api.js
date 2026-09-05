const API_BASE = '/api'
const TOKEN_KEY = 'hn_token'

/* Two identity layers:
   1. JWT (Phase 2 / U6) — stored in localStorage, attached as Bearer header.
      When present, this is the source of truth; the demo identity is dropped
      from outgoing requests so the server never sees mixed signals.
   2. Demo identity (legacy) — held in module state and persisted as a cookie
      via POST /api/demo/identity. Still functional when no JWT is present.
*/
let currentJwtToken = (typeof localStorage !== 'undefined')
  ? localStorage.getItem(TOKEN_KEY)
  : null
let currentIdentityId = null

export function getJwtToken() { return currentJwtToken }
export function hasJwtToken() { return !!currentJwtToken }

export function getCurrentIdentityId() {
  return currentIdentityId
}

function buildHeaders(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra }
  if (currentJwtToken) {
    /* JWT wins: never co-send X-Demo-Identity, server treats it as spoof
       attempt anyway but cleaner to omit. */
    h['Authorization'] = `Bearer ${currentJwtToken}`
  } else if (currentIdentityId) {
    h['X-Demo-Identity'] = currentIdentityId
  }
  return h
}

/* ── Request language (WP-I18N-2 / D-A) ──────────────────────────────────
   The backend now localises everything it serialises — seed data, decision
   strings, MCP demo content — from the `lang` the request carries, instead
   of the client pattern-matching Chinese back into English afterwards. So
   EVERY request states its language: `?lang=` on the URL (the only place a
   GET can put it) and `lang` in the body for POSTs that take one.

   `setApiLang` is called by <LanguageProvider> whenever the toggle moves,
   so this module never has to import React state. Until it is called,
   `currentLang` is null and requests go out exactly as they did before —
   which the backend reads as "unlabelled", i.e. today's Chinese default. */
let currentLang = null

export function setApiLang(lang) {
  currentLang = (lang === 'en' || lang === 'zh') ? lang : null
}

export function getApiLang() { return currentLang }

/* `${API_BASE}${path}` with `lang` appended. Used for every request, GET and
   POST alike, so a route can always read the language off the query string
   even when its body is schema-validated and cannot carry extra keys. */
function apiUrl(path) {
  if (!currentLang) return `${API_BASE}${path}`
  return `${API_BASE}${path}${path.includes('?') ? '&' : '?'}lang=${currentLang}`
}

/* Body-level `lang` for POSTs. An explicit per-call value always wins, so
   the analyze routes can still pin a session's language independently of
   the toggle's current position. */
function withLang(body) {
  if (!currentLang || (body && body.lang !== undefined)) return body
  return { ...body, lang: currentLang }
}

export async function startAnalysis(message, lang) {
  const body = { message }
  if (lang) body.lang = lang
  const res = await fetch(apiUrl('/analyze/start'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang(body)),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function replyAnalysis(sessionId, message, lang) {
  const body = { session_id: sessionId, message }
  if (lang) body.lang = lang
  const res = await fetch(apiUrl('/analyze/reply'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang(body)),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function runDecision(sessionId) {
  const res = await fetch(apiUrl('/analyze/decide'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang({ session_id: sessionId })),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── JobSeeker endpoints ── */

export async function fetchJobs() {
  const res = await fetch(apiUrl('/jobs'), { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function fetchCandidates() {
  const res = await fetch(apiUrl('/candidates'), { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function fetchCandidateProfile(candidateId) {
  const res = await fetch(apiUrl(`/candidates/${candidateId}/profile`), {
    headers: buildHeaders(),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function applyToJob({ candidate_id, job_design }) {
  /* Hits /api/apply (NOT /api/candidate-match — that endpoint scores a
     candidate across all jobs and never records an application). The backend
     returns { application, cover_letter: {...} } with cover_letter as a
     dict; ApplicationResult reads cover_letter / match_score / reason at the
     top level, so we flatten before returning. */
  const res = await fetch(apiUrl('/apply'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang({ candidate_id, job_design })),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `API error: ${res.status}`)
  }
  const data = await res.json()
  const letter = data.cover_letter || {}
  const matchPoints = Array.isArray(letter.key_match_points)
    ? letter.key_match_points
    : []
  return {
    application: data.application,
    cover_letter: letter.cover_letter || '',
    subject: letter.subject || '',
    match_score: letter.match_score,
    reason: matchPoints.join('；'),
    key_match_points: matchPoints,
  }
}

/* ── Demo identity ── */

export async function fetchIdentities() {
  const res = await fetch(apiUrl('/demo/identities'), { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const data = await res.json()
  if (data?.current?.id && !currentIdentityId) {
    // Seed module state from server's view (cookie-resolved) on first load
    currentIdentityId = data.current.id
  }
  return data
}

export async function setIdentity(identityId) {
  const res = await fetch(apiUrl('/demo/identity'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang({ identity_id: identityId })),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const data = await res.json()
  currentIdentityId = identityId
  return data
}

/* ── JD publish + candidate analyze ── */

export async function publishJob({
  jd,
  job_id,
  company,
  job_title,
  required_skills,
  nice_to_have_skills,
  core_responsibilities,
  salary_range,
  work_type,
}) {
  /* Forward all structured fields the JD agent produces, not just the
     markdown blob. Without these, the candidate-side cover-letter generator
     gets no signal (empty required_skills) and JobDetail falls back to the
     plain JD text — the structured "requirements" / "key skills" sections
     render empty. Undefined fields are dropped so the backend still accepts
     a JD that lacks an LLM-derived structure. */
  const payload = { jd, job_id, company, job_title }
  if (Array.isArray(required_skills)) payload.required_skills = required_skills
  if (Array.isArray(nice_to_have_skills)) payload.nice_to_have_skills = nice_to_have_skills
  if (Array.isArray(core_responsibilities)) payload.core_responsibilities = core_responsibilities
  if (salary_range && typeof salary_range === 'object') payload.salary_range = salary_range
  if (typeof work_type === 'string' && work_type) payload.work_type = work_type

  const res = await fetch(apiUrl('/jobs/publish'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang(payload)),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `API error: ${res.status}`)
  }
  return res.json()
}

export async function analyzeCandidate(profile) {
  const res = await fetch(apiUrl('/candidate/analyze'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang({ profile })),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `API error: ${res.status}`)
  }
  return res.json()
}

/* ── Pact lifecycle ── */

export async function createPact({ task_id, agent_name, creator_id, asset_id, amount, currency }) {
  const payload = { task_id, agent_name, amount, currency: currency || 'USD' }
  if (creator_id) payload.creator_id = creator_id
  /* asset_id pins which SkillAsset gets billed. When omitted, the backend
     falls back to JOB_DESIGN_ASSET_ID (a stub creator). Demo flow passes the
     bootstrapped customer-service Agent's asset_id so royalty lands on
     zhang_ai, not the Phase 1 stub. */
  if (asset_id) payload.asset_id = asset_id
  const res = await fetch(apiUrl('/pact/create'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang(payload)),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Pact create failed: ${res.status}`)
  }
  return res.json()
}

export async function approvePact(pactId) {
  const res = await fetch(apiUrl(`/pact/approve/${pactId}`), {
    method: 'POST',
    headers: buildHeaders(),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Pact approve failed: ${res.status}`)
  }
  return res.json()
}

export async function settlePact(pactId) {
  /* Two-step settle on the legacy rails: pact/settle creates the agent_run +
     accrued ledger rows; royalty/settle then drives the settlement provider to
     produce a real tx_hash. Backend pact/settle returns no tx_hash there, so
     without the second call there's nothing to surface on the Etherscan card.

     On the x402 rail (Stage 2 / WP-E) pact/settle pays the creator at
     invocation time and returns tx_hash + explorer_url itself; the second call
     is then skipped — the run is already 'settling' and /royalty/settle
     answers 409 for it. */
  const pactRes = await fetch(apiUrl(`/pact/settle/${pactId}`), {
    method: 'POST',
    headers: buildHeaders(),
  })
  if (!pactRes.ok) {
    const body = await pactRes.json().catch(() => ({}))
    throw new Error(body.error || `Pact settle failed: ${pactRes.status}`)
  }
  const pact = await pactRes.json()

  let tx_hash = pact.tx_hash || null
  /* Which rail settled it — decides the block explorer when the backend did
     not hand us an explorer_url (ExecutionPage.explorerHref). */
  let settlement_method = null
  if (!tx_hash && pact.run_id) {
    /* tx_hash is decorative — if the provider hiccups we still let the
       caller render royalty splits from the pact-settle response. */
    try {
      const royRes = await fetch(apiUrl('/royalty/settle'), {
        method: 'POST',
        headers: buildHeaders(),
        body: JSON.stringify(withLang({ run_id: pact.run_id })),
      })
      if (royRes.ok) {
        const roy = await royRes.json()
        tx_hash = roy.tx_hash || null
        settlement_method = roy.settlement_method || null
      }
    } catch { /* swallow — caller still gets royalty_splits */ }
  }

  return {
    run_id: pact.run_id,
    royalty_splits: pact.royalty_splits,
    amount: pact.amount,
    currency: pact.currency,
    agent_name: pact.agent_name,
    task_id: pact.task_id,
    tx_hash,
    settlement_method,
    /* explorer_url / settled_amount exist only on the x402 rail, where the
       backend settles the pact through a paid invocation. Null everywhere else
       so consumers only ever see one shape. settled_amount is what was actually
       paid (dollars); `amount` stays the amount the pact was created for. */
    explorer_url: pact.explorer_url || null,
    settled_amount: pact.settled_amount ?? null,
    /* mcp_result is the tool invocation result; null when the asset has no
       endpoint_url, error dict on failure, success dict with preview/total/tool
       on a real MCP call. */
    mcp_result: pact.mcp_result || null,
  }
}

/* Demo bootstrap exposes a single preset "Customer Service Script Generator"
   Agent — modal pulls asset_id / creator / wallet from here so the Pact
   settle lands on zhang_ai instead of the JOB_DESIGN_ASSET_ID fallback.
   Returns null on 404 (e.g. TESTING path) so callers can gracefully degrade
   to hardcoded demo data. */
export async function fetchDemoAgent() {
  const res = await fetch(apiUrl('/demo/agent'), { headers: buildHeaders() })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* Idempotent settle trigger. Modal calls it as part of settlePact's two-step
   flow; ExecutionPage's accept-delivery button also calls it so a preset/refreshed run
   without tx_hash still surfaces one on user sign-off. */
export async function settleRoyalty(runId) {
  const res = await fetch(apiUrl('/royalty/settle'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(withLang({ run_id: runId })),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Royalty settle failed: ${res.status}`)
  }
  return res.json()
}

/* ── SkillAsset registration ── */

export async function registerSkillAsset({
  name, description, type, endpoint_url, wallet_address,
  price_amount, price_currency, io_schema, split_rule,
}) {
  /* Required by app/schemas/skill_asset.json: name, description, type
     (lowercase enum), io_schema (object), price_amount (int basis points),
     price_currency, split_rule (must sum to 10000). Server computes
     content_hash + assigns creator_id from the Phase 1 stub, so we don't
     send them. endpoint_url + wallet_address are optional and may be null. */
  const payload = {
    name,
    description,
    type,
    price_amount,
    price_currency: price_currency || 'USD',
    io_schema: io_schema || {},
    split_rule: split_rule || { creator: 7000, platform: 2000, tax: 1000 },
  }
  if (endpoint_url) payload.endpoint_url = endpoint_url
  if (wallet_address) payload.wallet_address = wallet_address

  /* URL-only `lang`: this body is schema-validated
     (app/services/skill_registration.py rejects unknown fields with a 400),
     so it must stay exactly the registration payload. */
  const res = await fetch(apiUrl('/skills/register'), {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Register failed: ${res.status}`)
  }
  return res.json()
}

export async function fetchSkillsList() {
  /* Returns { skills: [{ id, name, description, type, creator_id,
     creator_name, price_amount (USD basis points), price_currency,
     mcp_endpoint, call_count, created_at }, …] } — the Agent World index. */
  const res = await fetch(apiUrl('/skills/list'), { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── Creator earnings ── */

export async function fetchCreatorEarnings() {
  const res = await fetch(apiUrl('/creator/earnings'), { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function fetchCreatorLedger() {
  /* Per-run ledger view. Returns { creator_id, entries, settled_totals,
     accrued_totals }. entries are sorted newest-first by created_at. */
  const res = await fetch(apiUrl('/creator/ledger'), { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── Phase 2 / U6: JWT auth ── */

export async function login(user_id, password) {
  const res = await fetch(apiUrl('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withLang({ user_id, password })),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Login failed: ${res.status}`)
  }
  const data = await res.json()
  currentJwtToken = data.token
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, data.token)
  }
  return data
}

export function logout() {
  currentJwtToken = null
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY)
  }
}

export async function fetchMe() {
  /* Returns { user } or throws on 401 — caller decides whether to redirect. */
  const res = await fetch(apiUrl('/auth/me'), { headers: buildHeaders() })
  if (!res.ok) {
    if (res.status === 401) {
      logout()  // stale / invalid token — clear it
    }
    throw new Error(`auth/me failed: ${res.status}`)
  }
  return res.json()
}
