import { useEffect, useState } from 'react'
import type { ScraperStatus } from '../types'
import { getScraperStatus, triggerRun, stopRun } from '../api'
import ScraperCard from '../components/ScraperCard'
import LogDrawer from '../components/LogDrawer'

export default function Scrapers() {
  const [statuses, setStatuses] = useState<ScraperStatus[]>([])
  const [runningPlatform, setRunningPlatform] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const load = async () => {
    const data = await getScraperStatus()
    setStatuses(data)
    // Update running platform from status (handles page refresh)
    const running = data.find(s => s.status === 'running')
    if (running && !activeRunId) {
      setRunningPlatform(running.platform)
    } else if (!running) {
      setRunningPlatform(null)
    }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleRun = async (platform: string) => {
    setRunningPlatform(platform)
    try {
      const { run_id } = await triggerRun(platform)
      setActiveRunId(run_id)
    } catch (e) {
      alert(String(e))
      setRunningPlatform(null)
    }
  }

  const handleStop = async (platform: string) => {
    try {
      await stopRun(platform)
      setRunningPlatform(null)
      await load()
    } catch (e) {
      alert(String(e))
    }
  }

  const handleClose = () => {
    setActiveRunId(null)
    setRunningPlatform(null)
    load()
  }

  return (
    <div className="pb-52">
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Scrapers</h1>
      <div className="grid grid-cols-3 gap-4">
        {statuses.map(s => (
          <ScraperCard
            key={s.platform}
            status={s}
            onRun={() => handleRun(s.platform)}
            onStop={() => handleStop(s.platform)}
            isRunning={s.status === 'running'}
          />
        ))}
      </div>
      <LogDrawer
        runId={activeRunId}
        platform={runningPlatform}
        onClose={handleClose}
      />
    </div>
  )
}
