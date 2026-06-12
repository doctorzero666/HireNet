import '../styles/board.css'

/**
 * Board — Animal Island 风格白色圆角卡片
 */
export default function Board({ children, maxWidth = 900 }) {
  return (
    <div className="board" style={{ maxWidth: `${maxWidth}px` }}>
      {children}
    </div>
  )
}
