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

export async function startAnalysis(message) {
  const res = await fetch(`${API_BASE}/analyze/start`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ message }),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function replyAnalysis(sessionId, message) {
  const res = await fetch(`${API_BASE}/analyze/reply`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function runDecision(sessionId) {
  const res = await fetch(`${API_BASE}/analyze/decide`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── JobSeeker endpoints ── */

export async function fetchJobs() {
  const res = await fetch(`${API_BASE}/jobs`, { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function fetchCandidates() {
  const res = await fetch(`${API_BASE}/candidates`, { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function fetchCandidateProfile(candidateId) {
  const res = await fetch(`${API_BASE}/candidates/${candidateId}/profile`, {
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
  const res = await fetch(`${API_BASE}/apply`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ candidate_id, job_design }),
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

export async function matchCandidatesForJob(jobId) {
  const res = await fetch(`${API_BASE}/match-candidates`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ job_id: jobId }),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── Demo identity ── */

export async function fetchIdentities() {
  const res = await fetch(`${API_BASE}/demo/identities`, { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const data = await res.json()
  if (data?.current?.id && !currentIdentityId) {
    // Seed module state from server's view (cookie-resolved) on first load
    currentIdentityId = data.current.id
  }
  return data
}

export async function setIdentity(identityId) {
  const res = await fetch(`${API_BASE}/demo/identity`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ identity_id: identityId }),
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

  const res = await fetch(`${API_BASE}/jobs/publish`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `API error: ${res.status}`)
  }
  return res.json()
}

export async function analyzeCandidate(profile) {
  const res = await fetch(`${API_BASE}/candidate/analyze`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ profile }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `API error: ${res.status}`)
  }
  return res.json()
}

/* ── Pact lifecycle ── */

export async function createPact({ task_id, agent_name, creator_id, amount, currency }) {
  const payload = { task_id, agent_name, amount, currency: currency || 'USD' }
  if (creator_id) payload.creator_id = creator_id
  const res = await fetch(`${API_BASE}/pact/create`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Pact create failed: ${res.status}`)
  }
  return res.json()
}

export async function approvePact(pactId) {
  const res = await fetch(`${API_BASE}/pact/approve/${pactId}`, {
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
  /* Two-step settle: pact/settle creates the agent_run + accrued ledger
     rows; royalty/settle then drives the settlement provider to produce a
     real tx_hash. Backend pact/settle never returns tx_hash, so without the
     second call there's nothing to surface on the Etherscan card. */
  const pactRes = await fetch(`${API_BASE}/pact/settle/${pactId}`, {
    method: 'POST',
    headers: buildHeaders(),
  })
  if (!pactRes.ok) {
    const body = await pactRes.json().catch(() => ({}))
    throw new Error(body.error || `Pact settle failed: ${pactRes.status}`)
  }
  const pact = await pactRes.json()

  let tx_hash = null
  if (pact.run_id) {
    /* tx_hash is decorative — if the provider hiccups we still let the
       caller render royalty splits from the pact-settle response. */
    try {
      const royRes = await fetch(`${API_BASE}/royalty/settle`, {
        method: 'POST',
        headers: buildHeaders(),
        body: JSON.stringify({ run_id: pact.run_id }),
      })
      if (royRes.ok) {
        const roy = await royRes.json()
        tx_hash = roy.tx_hash || null
      }
    } catch (_) { /* swallow — caller still gets royalty_splits */ }
  }

  return {
    run_id: pact.run_id,
    royalty_splits: pact.royalty_splits,
    amount: pact.amount,
    currency: pact.currency,
    agent_name: pact.agent_name,
    task_id: pact.task_id,
    tx_hash,
    /* mcp_result is the post-billing tool invocation result; null when the
       asset has no endpoint_url, error dict on failure, success dict with
       preview/total/tool on a real MCP call. */
    mcp_result: pact.mcp_result || null,
  }
}

/* ── SkillAsset registration ── */

export async function registerSkillAsset({
  name, description, type, endpoint_url,
  price_amount, price_currency, io_schema, split_rule,
}) {
  /* Required by app/schemas/skill_asset.json: name, description, type
     (lowercase enum), io_schema (object), price_amount (int basis points),
     price_currency, split_rule (must sum to 10000). Server computes
     content_hash + assigns creator_id from the Phase 1 stub, so we don't
     send them. endpoint_url is optional and may be null. */
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

  const res = await fetch(`${API_BASE}/skills/register`, {
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

/* ── Creator earnings ── */

export async function fetchCreatorEarnings() {
  const res = await fetch(`${API_BASE}/creator/earnings`, { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function fetchCreatorLedger() {
  /* Per-run ledger view. Returns { creator_id, entries, settled_totals,
     accrued_totals }. entries are sorted newest-first by created_at. */
  const res = await fetch(`${API_BASE}/creator/ledger`, { headers: buildHeaders() })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── Phase 2 / U6: JWT auth ── */

export async function login(user_id, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id, password }),
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
  const res = await fetch(`${API_BASE}/auth/me`, { headers: buildHeaders() })
  if (!res.ok) {
    if (res.status === 401) {
      logout()  // stale / invalid token — clear it
    }
    throw new Error(`auth/me failed: ${res.status}`)
  }
  return res.json()
}
