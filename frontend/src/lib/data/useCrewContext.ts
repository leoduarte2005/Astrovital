import { useEffect, useState } from 'react'
import type { CrewContext } from '@/lib/model/crewContext'
import { getDataSource } from './index'
import { useSession } from './session'

/**
 * The active crew member's context, or null while it loads. A result for another crew member is never
 * returned: switching crew shows null until the new context arrives (hot-swap isolation).
 */
export function useCrewContext(): CrewContext | null {
  const crewId = useSession((state) => state.activeCrew?.crewId ?? null)
  const [result, setResult] = useState<CrewContext | null>(null)

  useEffect(() => {
    if (!crewId) return
    let active = true
    getDataSource()
      .getCrewContext(crewId)
      .then((value) => {
        if (active) setResult(value)
      })
      .catch((error: unknown) => console.warn('crew context unavailable', error))
    return () => {
      active = false
    }
  }, [crewId])

  return result && result.crewId === crewId ? result : null
}
