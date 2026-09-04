import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Scene from '../components/Scene'
import Board from '../components/Board'
import NavBar from '../components/NavBar'
import SectionLabel from '../components/SectionLabel'
import PixelButton from '../components/PixelButton'
import { registerSkillAsset } from '../services/api'
import { useLang } from '../i18n/LanguageProvider'

const INPUT_STYLE = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg-content)',
  border: '2.5px solid var(--border-light)',
  borderRadius: 'var(--pill)',
  height: 44,
  padding: '0 18px',
  fontSize: 14,
  fontWeight: 500,
  color: 'var(--text-body)',
  outline: 'none',
  transition: 'all 0.25s var(--ease)',
}

const TEXTAREA_STYLE = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg-content)',
  border: '2.5px solid var(--border-light)',
  borderRadius: 'var(--r)',
  padding: '11px 16px',
  fontSize: 14,
  fontWeight: 500,
  color: 'var(--text-body)',
  outline: 'none',
  resize: 'vertical',
  minHeight: 74,
  lineHeight: 1.6,
  transition: 'all 0.25s var(--ease)',
}

const LABEL_STYLE = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  fontSize: 13,
  fontWeight: 700,
  color: 'var(--text)',
  marginBottom: 8,
}

const FIELD_WRAP = { marginBottom: 16 }

/* Frontend mirror of mcp_client.py's allowlist: scheme check only. The
   backend's SSRF allowlist is the real defense for server-side calls; this
   probe runs in the user's own browser, so we reject obviously invalid /
   non-http URLs and let the network layer report the rest. */
function validateProbeUrl(raw, t) {
  if (!raw) return { ok: false, error: t('agentRegister.errors.missingMcpUrl') }
  let parsed
  try {
    parsed = new URL(raw)
  } catch {
    return { ok: false, error: t('agentRegister.errors.invalidUrl') }
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, error: t('agentRegister.errors.unsupportedProtocol', { protocol: parsed.protocol }) }
  }
  return { ok: true, probeUrl: raw.replace(/\/+$/, '') + '/mcp/tools/list' }
}

/* Accept both REST-flavoured ({ tools: [...] }) and JSON-RPC
   ({ result: { tools: [...] } }) shapes — mcp_client.py wraps either. */
function extractTools(data) {
  const direct = Array.isArray(data?.tools) ? data.tools : null
  const wrapped = Array.isArray(data?.result?.tools) ? data.result.tools : null
  return direct || wrapped || []
}

export default function AgentRegister() {
  const navigate = useNavigate()
  const { t } = useLang()
  const [form, setForm] = useState({
    name: '',
    description: '',
    type: 'skill',
    price: '',
    wallet: '',
    mcpEndpointUrl: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  const onChange = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const handleTestConnection = async () => {
    if (testing) return
    setTestResult(null)
    const check = validateProbeUrl(form.mcpEndpointUrl.trim(), t)
    if (!check.ok) {
      setTestResult({ ok: false, error: check.error })
      return
    }
    setTesting(true)
    try {
      const res = await fetch(check.probeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
      if (!res.ok) {
        setTestResult({ ok: false, error: `HTTP ${res.status}` })
        return
      }
      const data = await res.json().catch(() => null)
      if (!data) {
        setTestResult({ ok: false, error: t('agentRegister.errors.invalidJsonResponse') })
        return
      }
      setTestResult({ ok: true, tools: extractTools(data) })
    } catch (err) {
      setTestResult({ ok: false, error: err?.message || t('agentRegister.errors.connectionFailed') })
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    if (!form.name.trim() || !form.description.trim()) {
      alert(t('agentRegister.errors.missingNameOrDescription'))
      return
    }
    /* schema requires price_amount as a non-negative integer in basis
       points. The form takes whole-dollar floats — round to nearest cent. */
    const priceDollars = Number(form.price) || 0
    const price_amount = Math.max(0, Math.round(priceDollars * 100))

    /* wallet is optional. Trim + tolerate empty so the backend's
       _normalize_wallet_address sees a real null instead of "".  When set,
       the backend re-validates shape and 400s on garbage, so no need to
       block submission client-side for malformed input. */
    const wallet_address = form.wallet.trim() || null

    setSubmitting(true)
    try {
      const result = await registerSkillAsset({
        name: form.name.trim(),
        description: form.description.trim(),
        type: form.type,
        endpoint_url: form.mcpEndpointUrl.trim() || null,
        wallet_address,
        price_amount,
        price_currency: 'USD',
      })
      alert(`📜 ${t('agentRegister.registerSuccess', { id: result.skill_id })}`)
      navigate('/creator')
    } catch (err) {
      alert(`❌ ${t('agentRegister.registerFailed', { message: err?.message || t('agentRegister.errors.unknownError') })}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleFocus = (e) => {
    e.target.style.borderColor = 'var(--focus-yellow)'
  }

  const handleBlur = (e) => {
    e.target.style.borderColor = 'var(--border-light)'
  }

  return (
    <Scene>
      <Board maxWidth={600}>
        <NavBar role="creator" />

        <div style={{ marginTop: 8 }}>
          <SectionLabel>⚒️ {t('agentRegister.title')}</SectionLabel>
        </div>

        <p style={{
          textAlign: 'center',
          fontSize: 14,
          color: 'var(--text-muted)',
          fontWeight: 600,
          lineHeight: 1.65,
          marginTop: 12,
          marginBottom: 20,
        }}>
          {t('agentRegister.subtitle')}
        </p>

        <form onSubmit={handleSubmit}>
          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>{t('agentRegister.fields.name')}</label>
            <input
              type="text"
              value={form.name}
              onChange={onChange('name')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder={t('agentRegister.fields.namePlaceholder')}
              style={INPUT_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>{t('agentRegister.fields.description')}</label>
            <textarea
              value={form.description}
              onChange={onChange('description')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder={t('agentRegister.fields.descriptionPlaceholder')}
              rows={4}
              style={TEXTAREA_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>{t('agentRegister.fields.type')}</label>
            <select
              value={form.type}
              onChange={onChange('type')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              style={INPUT_STYLE}
            >
              <option value="skill">Skill</option>
              <option value="agent">Agent</option>
              <option value="endpoint">Endpoint</option>
            </select>
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>{t('agentRegister.fields.price')}</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={form.price}
              onChange={onChange('price')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder={t('agentRegister.fields.pricePlaceholder')}
              style={INPUT_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>{t('agentRegister.fields.wallet')}</label>
            <input
              type="text"
              value={form.wallet}
              onChange={onChange('wallet')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder="0x..."
              style={INPUT_STYLE}
            />
          </div>

          <div style={FIELD_WRAP}>
            <label style={LABEL_STYLE}>🔌 MCP Endpoint URL</label>
            <input
              type="url"
              value={form.mcpEndpointUrl}
              onChange={onChange('mcpEndpointUrl')}
              onFocus={handleFocus}
              onBlur={handleBlur}
              placeholder="http://localhost:5002"
              style={INPUT_STYLE}
            />
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginTop: 8,
              flexWrap: 'wrap',
            }}>
              <PixelButton
                variant="soft"
                onClick={handleTestConnection}
                disabled={testing || !form.mcpEndpointUrl.trim()}
              >
                {testing ? `⏳ ${t('agentRegister.probing')}` : `🔍 ${t('agentRegister.testConnection')}`}
              </PixelButton>
              <div style={{ fontSize: 11, color: 'var(--text-disabled)', fontWeight: 600, flex: 1, minWidth: 200 }}>
                {t('agentRegister.mcpHint')}
              </div>
            </div>
            {testResult && (
              <div style={{
                marginTop: 12,
                padding: '12px 14px',
                borderRadius: 'var(--r)',
                background: testResult.ok ? 'rgba(111, 186, 44, 0.10)' : 'rgba(224, 90, 90, 0.10)',
                border: `2.5px solid ${testResult.ok ? 'var(--success)' : 'var(--error)'}`,
                fontSize: 13,
                color: 'var(--text-body)',
              }}>
                {testResult.ok ? (
                  <>
                    <div style={{ fontWeight: 700, marginBottom: testResult.tools.length ? 8 : 0 }}>
                      ✅ {t('agentRegister.toolsFound', { count: testResult.tools.length })}
                    </div>
                    {testResult.tools.length === 0 && (
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                        {t('agentRegister.noToolsDeclared')}
                      </div>
                    )}
                    {testResult.tools.map((tool, i) => {
                      /* Coerce in case the MCP server returns non-string
                         values — React throws on object children. */
                      const name = typeof tool?.name === 'string' ? tool.name : '?'
                      const desc = typeof tool?.description === 'string' ? tool.description : ''
                      return (
                        <div key={`${name}-${i}`} style={{
                          marginTop: i === 0 ? 0 : 6,
                          fontSize: 12,
                          lineHeight: 1.55,
                        }}>
                          <code style={{ fontWeight: 700, color: 'var(--text)' }}>
                            {name}
                          </code>
                          {desc && (
                            <span style={{ color: 'var(--text-muted)' }}> — {desc}</span>
                          )}
                        </div>
                      )
                    })}
                  </>
                ) : (
                  <div style={{ fontWeight: 600 }}>❌ {testResult.error}</div>
                )}
              </div>
            )}
          </div>

          <div style={{
            display: 'flex',
            justifyContent: 'center',
            gap: 14,
            marginTop: 24,
            flexWrap: 'wrap',
          }}>
            <PixelButton variant="gold" type="submit" disabled={submitting}>
              {submitting ? `⌛ ${t('agentRegister.submitting')}` : `📜 ${t('agentRegister.submit')}`}
            </PixelButton>
            <PixelButton variant="wood" onClick={() => navigate('/creator')}>
              ◂ {t('agentPerformance.backToWorkshop')}
            </PixelButton>
          </div>
        </form>
      </Board>
    </Scene>
  )
}
