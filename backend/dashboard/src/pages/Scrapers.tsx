import { useEffect, useState } from 'react'
import type { ScraperStatus } from '../types'
import { getScraperStatus, triggerRun } from '../api'
import ScraperCard from '../components/ScraperCard'
import LogDrawer from '../components/LogDrawer'

export default function Scrapers() {
  const [statuses, setStatuses] = useState<ScraperStatus[]>([])
  const [runningPlatform, setRunningPlatform] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const load = async () => {
    const data = await getScraperStatus()
    setStatuses(data)
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
            isRunning={runningPlatform === s.platform}
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
