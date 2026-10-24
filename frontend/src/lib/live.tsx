import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api, getToken } from './api'

/**
 * The published-analysis generation the server last reported.
 *
 * Pages re-fetch when this number changes, which is what makes a coefficient
 * edit on the settings page appear on the dashboard without a manual reload —
 * an explicit acceptance criterion of the case ("обновляются автоматически,
 * без ручной перезагрузки страницы").
 *
 * Why polling rather than the SSE endpoint the backend already exposes:
 * ``EventSource`` cannot set the ``Authorization`` header, and the SSE route
 * reads the bearer token from that header. The only way to use it from the
 * browser would be to put the token in the query string, which writes a
 * credential into access logs. The case lets the author choose the mechanism,
 * so a small authenticated poll is the honest trade: no token leakage, no new
 * dependency, same observable behaviour. The interval matches the server's own
 * recalculation cadence.
 */
const LiveContext = createContext<number>(0)

const POLL_MS = 5000

export function LiveProvider({ children }: { children: ReactNode }) {
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    let disposed = false
    let timer: number | null = null
    let last: number | null = null

    async function tick() {
      if (disposed) return
      if (getToken()) {
        try {
          const summary = await api.summary()
          const current = Number(summary.generation ?? 0)
          if (!disposed && current && current !== last) {
            last = current
            setGeneration(current)
          }
        } catch {
          // A transient failure must not stop the loop; the next tick retries.
        }
      }
      if (!disposed) timer = window.setTimeout(tick, POLL_MS)
    }

    void tick()
    return () => {
      disposed = true
      if (timer) window.clearTimeout(timer)
    }
  }, [])

  return <LiveContext.Provider value={generation}>{children}</LiveContext.Provider>
}

/**
 * Runs ``reload`` once per new generation.
 *
 * ``reload`` lives in a ref so callers can pass an inline closure without
 * resubscribing, and the generation is de-duplicated so a page that mounts
 * late does not fire a redundant refresh for a version it already rendered.
 */
export function useLiveGeneration(reload: () => void | Promise<void>): number {
  const generation = useContext(LiveContext)
  const reloadRef = useRef(reload)
  reloadRef.current = reload
  const seenRef = useRef<number | null>(null)

  useEffect(() => {
    if (generation === 0 || seenRef.current === generation) return
    seenRef.current = generation
    void reloadRef.current()
  }, [generation])

  return generation
}

/** Current generation, for pages that only need to display it. */
export function useGeneration(): number {
  return useContext(LiveContext)
}
