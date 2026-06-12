/**
 * Icon — Island-style rounded line SVG set, ported from island shared.jsx
 * Usage: <Icon name="arrow" size={16} />
 */
const PATHS = {
  arrow:    <path d="M5 12h14M13 6l6 6-6 6" />,
  paperclip:<path d="M21 9.5l-9.5 9.5a4.5 4.5 0 0 1-6.4-6.4l9.2-9.2a3 3 0 0 1 4.3 4.3L9.3 16.3a1.5 1.5 0 0 1-2.1-2.1l8.2-8.2" />,
  upload:   <g><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" /></g>,
  lock:     <g><rect x="4.5" y="10.5" width="15" height="10" rx="3" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" /></g>,
  shield:   <path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6l7-3z" />,
  check:    <path d="M5 12.5l4.5 4.5L19 7" />,
  checkCircle: <g><circle cx="12" cy="12" r="9" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></g>,
  spark:    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />,
  chart:    <g><path d="M4 20V4" /><path d="M4 20h16" /><rect x="7" y="11" width="3" height="6" rx="1" /><rect x="12.5" y="7" width="3" height="10" rx="1" /></g>,
  doc:      <g><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /></g>,
  warning:  <g><path d="M12 4l9 16H3l9-16z" /><path d="M12 10v4M12 17.5v.2" /></g>,
  rocket:   <g><path d="M14 4c3 0 6 3 6 6-2 0-4 .5-5.5 2L11 15l-2-2 3-3.5C13.5 8 13 6 14 4z" /><path d="M9 15l-3 3M6 12l-2 2 4 4 2-2" /></g>,
  download: <g><path d="M12 4v11M7 11l5 4 5-4" /><path d="M5 20h14" /></g>,
  eye:      <g><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.7" /></g>,
  plus:     <path d="M12 5v14M5 12h14" />,
  grid:     <g><rect x="4" y="4" width="7" height="7" rx="2.2" /><rect x="13" y="4" width="7" height="7" rx="2.2" /><rect x="4" y="13" width="7" height="7" rx="2.2" /><rect x="13" y="13" width="7" height="7" rx="2.2" /></g>,
  bot:      <g><rect x="5" y="8" width="14" height="11" rx="4" /><path d="M12 8V4M9 4h6" /><circle cx="9.5" cy="13" r="1.1" fill="currentColor" stroke="none" /><circle cx="14.5" cy="13" r="1.1" fill="currentColor" stroke="none" /></g>,
  list:     <g><path d="M8 6h12M8 12h12M8 18h12" /><circle cx="4" cy="6" r="1.1" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="4" cy="18" r="1.1" fill="currentColor" stroke="none"/></g>,
  pulse:    <path d="M3 12h4l2.5-7 4 14L16 12h5" />,
  settings: <g><circle cx="12" cy="12" r="3" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8" /></g>,
  refresh:  <g><path d="M4 12a8 8 0 0 1 13.7-5.6L20 8" /><path d="M20 4v4h-4" /><path d="M20 12a8 8 0 0 1-13.7 5.6L4 16" /><path d="M4 20v-4h4" /></g>,
  user:     <g><circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" /></g>,
  file:     <g><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /><path d="M10 13h6M10 16.5h6" /></g>,
  coins:    <g><ellipse cx="9" cy="7" rx="5.5" ry="2.6" /><path d="M3.5 7v4c0 1.4 2.5 2.6 5.5 2.6M14.5 11.4c0-1.4-2.5-2.6-5.5-2.6" /><ellipse cx="15" cy="14" rx="5.5" ry="2.6" /><path d="M9.5 14v3c0 1.4 2.5 2.6 5.5 2.6s5.5-1.2 5.5-2.6v-3" /></g>,
  target:   <g><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /></g>,
  clock:    <g><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></g>,
  trend:    <g><path d="M4 16l5-5 3 3 7-7" /><path d="M15 7h4v4" /></g>,
  edit:     <g><path d="M4 20h4L18.7 9.3a1.9 1.9 0 0 0-2.7-2.7L5 17.3 4 20z" /><path d="M14.5 8.5l3 3" /></g>,
  pause:    <g><rect x="7" y="5" width="3.2" height="14" rx="1.6" /><rect x="14" y="5" width="3.2" height="14" rx="1.6" /></g>,
  star:     <path d="M12 4l2.3 4.7 5.2.8-3.8 3.7.9 5.2L12 16.7 7.4 18.1l.9-5.2L4.5 9.5l5.2-.8L12 4z" />,
  globe:    <g><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17" /><path d="M12 3.5c2.6 2.4 2.6 14.6 0 17M12 3.5c-2.6 2.4-2.6 14.6 0 17" /></g>,
  server:   <g><rect x="4" y="4" width="16" height="7" rx="2.8" /><rect x="4" y="13" width="16" height="7" rx="2.8" /><circle cx="7.8" cy="7.5" r="1" fill="currentColor" stroke="none" /><circle cx="7.8" cy="16.5" r="1" fill="currentColor" stroke="none" /></g>,
  link:     <g><path d="M9.5 14.5l5-5" /><path d="M11.5 7l1-1a3.5 3.5 0 0 1 5 5l-1 1" /><path d="M12.5 17l-1 1a3.5 3.5 0 0 1-5-5l1-1" /></g>,
  clipboard:<g><rect x="5" y="5" width="14" height="16" rx="3" /><rect x="8.5" y="3" width="7" height="3.6" rx="1.8" /><path d="M9 12h6M9 16h4" /></g>,
  dollar:   <g><path d="M12 3v18" /><path d="M16 7c0-1.7-1.8-2.8-4-2.8S8 5.3 8 7s1.8 2.4 4 3 4 1.4 4 3.2-1.8 2.8-4 2.8-4-1.1-4-2.8" /></g>,
  leaf:     <g><path d="M5 19c0-8 6-13 14-13 0 8-6 13-14 13z" /><path d="M5 19c3-5 6-7 10-8.5" /></g>,
  sprout:   <g><path d="M12 21v-7" /><path d="M12 14c0-3-2.5-5-5.5-5 0 3 2.5 5 5.5 5z" /><path d="M12 12c0-3 2.5-5 5.5-5 0 3-2.5 5-5.5 5z" /></g>,
}

export default function Icon({ name, size = 18, className = '', style }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`ic ${className}`.trim()}
      style={style}
    >
      {PATHS[name] || null}
    </svg>
  )
}
