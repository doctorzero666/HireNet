import '../styles/scene.css'

/**
 * Scene — full-screen Animal Island style background container
 */
export default function Scene({ children }) {
  return (
    <div className="scene">
      {[...Array(10)].map((_, i) => (
        <span
          key={i}
          className="fleaf"
          aria-hidden="true"
          style={{
            left: `${5 + i * 10}%`,
            animationDelay: `${i * 1.2}s`,
            fontSize: `${12 + (i % 3) * 6}px`,
            animationDuration: `${9 + (i % 3) * 2.5}s`,
          }}
        >
          🍃
        </span>
      ))}
      <div className="scene__content">{children}</div>
    </div>
  )
}
