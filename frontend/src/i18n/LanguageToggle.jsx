import { useLang } from './LanguageProvider'

/**
 * LanguageToggle — small EN / (target language) switch.
 *
 * Shows the language you would switch TO (per the WP-I18N spec): the Chinese
 * language name while the UI is in English, "EN" while it is in Chinese.
 * Rendered inside NavBar for every page that has one, and as a
 * fixed-position instance from App.jsx for the three pages (RoleSelect,
 * Login, EmployerHub) that don't.
 *
 * The target-language label comes from the `languageNames` dictionary key
 * (identical value in en.json and zh.json — it names a language, it isn't
 * translated) rather than a literal in this file: every CJK character in the
 * frontend must live in a JSON dictionary, never in a .jsx/.js source file.
 */
export default function LanguageToggle({ className = '', style }) {
  const { lang, setLang, t } = useLang()
  const nextLang = lang === 'en' ? 'zh' : 'en'

  return (
    <button
      type="button"
      className={`lang-toggle ${className}`.trim()}
      style={style}
      onClick={() => setLang(nextLang)}
      aria-label={t('common.languageToggle.ariaLabel')}
      title={t('common.languageToggle.ariaLabel')}
    >
      {t(`languageNames.${nextLang}`)}
    </button>
  )
}
