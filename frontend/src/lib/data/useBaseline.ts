import { useEffect, useState } from 'react'
import type { BaselineMetricId, BaselineProfile, HistorySeries, HistoryWindow } from '@/lib/model/baseline'
import { getDataSource } from './index'
import { useSession } from './session'

/** Result tagged with what it answered, so a result for another crew or window is never shown. */
interface Tagged<T> {
  key: string
  value: T
}

/** The active crew member's baseline, or null while it loads. */
export function useBaseline(): BaselineProfile | null {
  const crewId = useSession((state) => state.activeCrew?.crewId ?? null)
  const [result, setResult] = useState<Tagged<BaselineProfile> | null>(null)

  useEffect(() => {
    if (!crewId) return
    let active = true
    getDataSource()
      .getBaseline(crewId)
      .then((value) => {
        if (active) setResult({ key: crewId, value })
      })
      .catch((error: unknown) => console.warn('baseline unavailable', error))
    return () => {
      active = false
    }
  }, [crewId])

  return result && result.key === crewId ? result.value : null
}

/** One metric over one window for the active crew member, or null while it loads. */
export function useHistory(metric: BaselineMetricId, window: HistoryWindow): HistorySeries | null {
  const crewId = useSession((state) => state.activeCrew?.crewId ?? null)
  const key = `${crewId}|${metric}|${window}`
  const [result, setResult] = useState<Tagged<HistorySeries> | null>(null)

  useEffect(() => {
    if (!crewId) return
    let active = true
    getDataSource()
      .history(crewId, metric, window)
      .then((value) => {
        if (active) setResult({ key, value })
      })
      .catch((error: unknown) => console.warn('history unavailable', error))
    return () => {
      active = false
    }
  }, [crewId, metric, window, key])

  return result && result.key === key ? result.value : null
}
