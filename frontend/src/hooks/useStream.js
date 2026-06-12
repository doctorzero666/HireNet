import { useState, useEffect, useRef } from 'react'

/**
 * useStream — typewriter effect, ported from island shared.jsx
 */
export function useStream(text, { speed = 18, start = true, onDone } = {}) {
  const [out, setOut] = useState('')
  const [done, setDone] = useState(false)
  const [trackedText, setTrackedText] = useState(text)
  const [trackedStart, setTrackedStart] = useState(start)
  const onDoneRef = useRef(onDone)
  const timerRef = useRef(null)

  useEffect(() => {
    onDoneRef.current = onDone
  })

  if (trackedText !== text || trackedStart !== start) {
    setTrackedText(text)
    setTrackedStart(start)
    setOut('')
    setDone(false)
  }

  useEffect(() => {
    if (!start) return undefined
    let i = 0
    const tick = () => {
      i += Math.random() < 0.3 ? 2 : 1
      if (i >= text.length) {
        setOut(text)
        setDone(true)
        onDoneRef.current?.()
        return
      }
      setOut(text.slice(0, i))
      timerRef.current = setTimeout(tick, speed + Math.random() * speed)
    }
    timerRef.current = setTimeout(tick, 120)
    return () => {
      clearTimeout(timerRef.current)
    }
  }, [text, start, speed])

  return { out, done }
}
