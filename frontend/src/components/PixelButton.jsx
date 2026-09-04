import '../styles/nav.css'

/**
 * PixelButton — Island style button (maps to island-ref's .btn system)
 * variant: 'gold' (btn-primary) | 'soft' (btn-soft) | 'wood' (btn-ghost) | 'danger' (btn-danger-ghost)
 * size:    'md' (default) | 'lg' (maps to .btn-lg)
 */
export default function PixelButton({
  children,
  variant = 'gold',
  size = 'md',
  onClick,
  type = 'button',
  disabled = false,
}) {
  const classes = ['pixel-btn', `pixel-btn--${variant}`]
  if (size === 'lg') classes.push('pixel-btn--lg')
  return (
    <button
      type={type}
      className={classes.join(' ')}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  )
}
