import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { ApiError, api, setGenerationListener } from './api'
import { useAuth } from './auth'
import { formatDateTime } from '../components/ui'
import type { VersionInfo } from '../types'

interface AnalysisContextValue {
  liveVersion: VersionInfo | null
  maxGeneration: number | null
  sseConnected: boolean
  pinnedGeneration: number | null
  activeGeneration: number | undefined
  refreshKey: number
  setPinnedGeneration: (generation: number | null) => void
  notifyMutation: (next?: Partial<VersionInfo>) => void
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null)

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const { email } = useAuth()
  const [liveVersion, setLiveVersion] = useState<VersionInfo | null>(null)
  const [maxGeneration, setMaxGeneration] = useState<number | null>(null)
  const [sseConnected, setSseConnected] = useState(false)
  const [pinnedGeneration, setPinnedGeneration] = useState<number | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const knownGenRef = useRef<number | null>(null)
  const lastEventIdRef = useRef<number | null>(null)

  useEffect(() => {
    if (!email) {
      setLiveVersion(null)
      setMaxGeneration(null)
      setSseConnected(false)
      setPinnedGeneration(null)
      knownGenRef.current = null
      lastEventIdRef.current = null
      return
    }

    setGenerationListener((gen) => {
      if (knownGenRef.current === null) {
        knownGenRef.current = gen
      }
      setMaxGeneration((prev) => (prev === null || gen > prev ? gen : prev))
    })

    return () => {
      setGenerationListener(null)
    }
  }, [email])

  useEffect(() => {
    if (!email) return

    const controller = new AbortController()
    let active = true

    async function runStream() {
      let attempt = 0
      while (active && !controller.signal.aborted) {
        try {
          await api.streamEvents({
            lastEventId: lastEventIdRef.current,
            signal: controller.signal,
            onOpen: () => {
              if (!active) return
              attempt = 0
              setSseConnected(true)
            },
            onUpdate: (eventId, version) => {
              if (!active) return
              lastEventIdRef.current = eventId
              const prevGen = knownGenRef.current
              knownGenRef.current =
                prevGen === null ? version.generation : Math.max(prevGen, version.generation)
              setLiveVersion(version)
              setMaxGeneration((prev) =>
                prev === null || version.generation > prev ? version.generation : prev,
              )
              if (prevGen !== null && version.generation !== prevGen) {
                setRefreshKey((k) => k + 1)
              }
            },
          })
        } catch (err) {
          if (!active || controller.signal.aborted) break
          if (err instanceof ApiError && err.status === 401) break
        }

        if (!active || controller.signal.aborted) break
        setSseConnected(false)
        attempt += 1
        const delayMs = Math.min(8000, 1500 * attempt)
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, delayMs)
          controller.signal.addEventListener(
            'abort',
            () => {
              clearTimeout(timer)
              resolve()
            },
            { once: true },
          )
        })
      }
    }

    void runStream()

    return () => {
      active = false
      controller.abort()
      setSseConnected(false)
    }
  }, [email])

  const notifyMutation = useCallback((next?: Partial<VersionInfo>) => {
    if (next && typeof next.generation === 'number') {
      knownGenRef.current = next.generation
      lastEventIdRef.current = next.generation
      setMaxGeneration((prev) =>
        prev === null || next.generation! > prev ? next.generation! : prev,
      )
      if (
        next.sourceVersion !== undefined &&
        next.modelVersion !== undefined &&
        next.capturedAt !== undefined &&
        next.asOf !== undefined &&
        next.calculatedAt !== undefined
      ) {
        setLiveVersion(next as VersionInfo)
      }
    }
    setRefreshKey((k) => k + 1)
  }, [])

  const activeGeneration = pinnedGeneration ?? undefined

  const value = useMemo<AnalysisContextValue>(
    () => ({
      liveVersion,
      maxGeneration,
      sseConnected,
      pinnedGeneration,
      activeGeneration,
      refreshKey,
      setPinnedGeneration,
      notifyMutation,
    }),
    [
      liveVersion,
      maxGeneration,
      sseConnected,
      pinnedGeneration,
      activeGeneration,
      refreshKey,
      notifyMutation,
    ],
  )

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>
}

export function useAnalysis(): AnalysisContextValue {
  const ctx = useContext(AnalysisContext)
  if (!ctx) throw new Error('useAnalysis must be used inside AnalysisProvider')
  return ctx
}

export function GenerationControl() {
  const { liveVersion, maxGeneration, sseConnected, pinnedGeneration, setPinnedGeneration } =
    useAnalysis()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const latest = liveVersion?.generation ?? maxGeneration
  const generations: number[] = []
  if (latest && latest >= 1) {
    const start = Math.max(1, latest - 19)
    for (let g = latest; g >= start; g -= 1) {
      generations.push(g)
    }
  }

  return (
    <div className="gen-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`gen-pill${pinnedGeneration !== null ? ' is-pinned' : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={
          pinnedGeneration !== null
            ? `Зафиксировано поколение #${pinnedGeneration}`
            : sseConnected
              ? 'Подключён поток обновлений SSE'
              : 'Ожидание потока обновлений SSE'
        }
      >
        <span
          className={`gen-dot ${
            pinnedGeneration !== null ? 'pinned' : sseConnected ? 'live' : 'idle'
          }`}
          aria-hidden="true"
        />
        <span>
          {pinnedGeneration !== null
            ? `#${pinnedGeneration} · Архив`
            : latest
              ? `#${latest} · Live`
              : 'Live'}
        </span>
      </button>

      {open ? (
        <div className="gen-popover" role="dialog" aria-label="Версия расчёта">
          <div className="gen-popover-head">
            <strong>Версия расчёта</strong>
            <span className={`badge ${sseConnected ? 'risk-low' : 'neutral'}`}>
              {sseConnected ? 'SSE подключён' : 'SSE переподкл.'}
            </span>
          </div>

          {liveVersion ? (
            <dl className="kv gen-kv">
              <dt>Актуальное поколение</dt>
              <dd className="mono">#{liveVersion.generation}</dd>
              <dt>Версия снимка / модели</dt>
              <dd className="mono">
                s{liveVersion.sourceVersion} / m{liveVersion.modelVersion}
              </dd>
              {liveVersion.asOf ? (
                <>
                  <dt>Момент оценки (asOf)</dt>
                  <dd className="mono">{formatDateTime(liveVersion.asOf)}</dd>
                </>
              ) : null}
              {liveVersion.calculatedAt ? (
                <>
                  <dt>Рассчитано</dt>
                  <dd className="mono">{formatDateTime(liveVersion.calculatedAt)}</dd>
                </>
              ) : null}
            </dl>
          ) : null}

          <div className="field" style={{ marginTop: 10 }}>
            <label htmlFor="gen-select">Режим просмотра</label>
            <select
              id="gen-select"
              className="select"
              value={pinnedGeneration === null ? 'live' : String(pinnedGeneration)}
              onChange={(e) => {
                const val = e.target.value
                setPinnedGeneration(val === 'live' ? null : Number(val))
                setOpen(false)
              }}
            >
              <option value="live">
                Актуальное поколение{latest ? ` (#${latest}, автообновление)` : ''}
              </option>
              {generations.map((g) => (
                <option key={g} value={String(g)}>
                  Поколение #{g} {g === latest ? '(текущее, фикс.)' : '(история)'}
                </option>
              ))}
            </select>
            <span className="hint">
              Позволяет просматривать предыдущие опубликованные поколения расчёта (?generation=N).
            </span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
