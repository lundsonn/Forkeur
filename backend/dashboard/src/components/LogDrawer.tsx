import { useEffect, useRef, useState } from 'react'
import type { WsMessage } from '../types'

interface Props {
  runId: string | null
  platform: string | null
  onClose: () => void
}

export default function LogDrawer({ runId, platform, onClose }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [done, setDone] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!runId) return
    setLines([])
    setDone(false)

    const token = localStorage.getItem('admin_token') ?? ''
    const ws = new WebSocket(`ws://localhost:8000/ws/${runId}?token=${token}`)
    ws.onmessage = (e) => {
      const msg: WsMessage = JSON.parse(e.data)
      if (msg.type === 'log' && msg.line) {
        setLines(prev => [...prev, msg.line!])
      } else if (msg.type === 'done') {
        setLines(prev => [...prev, `✅ Done — ${msg.records} records saved`])
        setDone(true)
      } else if (msg.type === 'error') {
        setLines(prev => [...prev, `❌ Error: ${msg.msg}`])
        setDone(true)
      }
    }
    return () => ws.close()
  }, [runId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  if (!runId) return null

  return (
    <div className="fixed bottom-0 left-52 right-0 bg-stone-950 border-t border-stone-800 z-50">
      <div className="flex items-center justify-between px-5 py-2.5 border-b border-stone-800">
        <div className="flex items-center gap-2">
          {!done && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />}
          <span className="text-xs font-medium text-stone-400 capitalize">{platform} · {done ? 'complete' : 'live'}</span>
        </div>
        {done && (
          <button onClick={onClose} className="text-xs text-stone-500 hover:text-stone-300 transition-colors">
            Dismiss
          </button>
        )}
      </div>
      <div className="h-36 overflow-y-auto px-5 py-3 font-mono text-xs text-stone-300 leading-5">
        {lines.map((line, i) => <div key={i}>{line}</div>)}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
