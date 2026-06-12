import { useStream } from '../hooks/useStream'

/**
 * StreamText — typewriter span with blinking cursor
 */
export default function StreamText({ text, speed = 18, start = true, onDone }) {
  const { out, done } = useStream(text, { speed, start, onDone })
  return (
    <span>
      {out}
      {!done && start && <span className="cursor" />}
    </span>
  )
}
