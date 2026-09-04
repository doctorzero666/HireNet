import '../styles/board.css'

/**
 * Board — Animal Island style white rounded-corner card
 */
export default function Board({ children, maxWidth = 900 }) {
  return (
    <div className="board" style={{ maxWidth: `${maxWidth}px` }}>
      {children}
    </div>
  )
}
