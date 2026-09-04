#!/usr/bin/env node
/**
 * WP-I18N — fails the build when `en.json` and `zh.json` don't carry the
 * exact same set of dotted keys. A key present in one dictionary and missing
 * from the other is either a silent English string in the Chinese demo or a
 * `useLang().t()` call that renders the raw key.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const I18N_DIR = path.join(__dirname, '..', 'src', 'i18n')

function flattenKeys(obj, prefix = '') {
  const keys = []
  for (const [key, value] of Object.entries(obj)) {
    const dotted = prefix ? `${prefix}.${key}` : key
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      keys.push(...flattenKeys(value, dotted))
    } else {
      keys.push(dotted)
    }
  }
  return keys
}

function loadKeySet(filename) {
  const raw = readFileSync(path.join(I18N_DIR, filename), 'utf-8')
  return new Set(flattenKeys(JSON.parse(raw)))
}

const en = loadKeySet('en.json')
const zh = loadKeySet('zh.json')

const missingInZh = [...en].filter((k) => !zh.has(k)).sort()
const missingInEn = [...zh].filter((k) => !en.has(k)).sort()

if (missingInZh.length || missingInEn.length) {
  if (missingInZh.length) {
    console.error(`Keys in en.json but missing from zh.json (${missingInZh.length}):`)
    for (const k of missingInZh) console.error(`  - ${k}`)
  }
  if (missingInEn.length) {
    console.error(`Keys in zh.json but missing from en.json (${missingInEn.length}):`)
    for (const k of missingInEn) console.error(`  - ${k}`)
  }
  process.exit(1)
}

console.log(`i18n:check OK — ${en.size} keys, identical in en.json and zh.json`)
