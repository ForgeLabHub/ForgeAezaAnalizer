import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { NavLink, useLocation } from 'react-router-dom'

interface PillRect {
  x: number
  y: number
  w: number
  h: number
  visible: boolean
}

interface HoverPillState extends PillRect {
  sliding: boolean
}

const EMPTY_RECT: PillRect = { x: 0, y: 0, w: 0, h: 0, visible: false }
const EMPTY_HOVER: HoverPillState = { ...EMPTY_RECT, sliding: false }

function escapeSelectorAttr(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
    return CSS.escape(value)
  }
  return value.replace(/(["\\])/g, '\\$1')
}

export function useSlidingPill(activeKey: string | null) {
  const containerRef = useRef<HTMLElement | null>(null)
  const prevKeyRef = useRef<string | null | undefined>(undefined)
  const animUntilRef = useRef(0)

  const [activeRect, setActiveRect] = useState<PillRect>(EMPTY_RECT)
  const [activeSliding, setActiveSliding] = useState(false)
  const [pulseKey, setPulseKey] = useState(0)

  const [hover, setHover] = useState<HoverPillState>(EMPTY_HOVER)

  const measureActive = useCallback(
    (slide: boolean) => {
      const container = containerRef.current
      if (!container || activeKey === null) {
        setActiveSliding(false)
        setActiveRect((prev) => (prev.visible ? { ...prev, visible: false } : prev))
        return null
      }
      const target = container.querySelector<HTMLElement>(
        `[data-pill-key="${escapeSelectorAttr(activeKey)}"]`,
      )
      if (!target) {
        setActiveSliding(false)
        setActiveRect((prev) => (prev.visible ? { ...prev, visible: false } : prev))
        return null
      }
      const next: PillRect = {
        x: target.offsetLeft,
        y: target.offsetTop,
        w: target.offsetWidth,
        h: target.offsetHeight,
        visible: true,
      }
      setActiveSliding(slide)
      setActiveRect((prev) =>
        prev.x === next.x &&
        prev.y === next.y &&
        prev.w === next.w &&
        prev.h === next.h &&
        prev.visible === next.visible
          ? prev
          : next,
      )
      return target
    },
    [activeKey],
  )

  useLayoutEffect(() => {
    const prevKey = prevKeyRef.current
    const isInitial = prevKey === undefined
    const shouldSlide = !isInitial && prevKey !== null && activeKey !== null && prevKey !== activeKey
    prevKeyRef.current = activeKey

    if (shouldSlide) {
      animUntilRef.current = performance.now() + 420
      setPulseKey((k) => k + 1)
    }

    const target = measureActive(shouldSlide)
    if (shouldSlide && target && containerRef.current) {
      const box = containerRef.current
      if (box.scrollWidth > box.clientWidth) {
        target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
      }
    }
  }, [activeKey, measureActive])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const sync = () => {
      const inFlight = performance.now() < animUntilRef.current
      measureActive(inFlight)
    }

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(sync) : null
    if (ro) {
      ro.observe(container)
      container.querySelectorAll<HTMLElement>('[data-pill-key]').forEach((el) => ro.observe(el))
    }

    window.addEventListener('resize', sync)
    let cancelled = false
    if (typeof document !== 'undefined' && 'fonts' in document) {
      void document.fonts.ready.then(() => {
        if (!cancelled) sync()
      })
    }

    return () => {
      cancelled = true
      ro?.disconnect()
      window.removeEventListener('resize', sync)
    }
  }, [activeKey, measureActive])

  const onItemEnter = useCallback((el: HTMLElement) => {
    const x = el.offsetLeft
    const y = el.offsetTop
    const w = el.offsetWidth
    const h = el.offsetHeight
    setHover((prev) => ({
      x,
      y,
      w,
      h,
      visible: true,
      sliding: prev.visible,
    }))
  }, [])

  const onContainerLeave = useCallback(() => {
    setHover((prev) => (prev.visible ? { ...prev, visible: false } : prev))
  }, [])

  return {
    containerRef,
    activeRect,
    activeSliding,
    pulseKey,
    hoverRect: hover,
    hoverSliding: hover.sliding,
    onItemEnter,
    onContainerLeave,
  }
}

function pillInlineStyle(rect: PillRect): CSSProperties {
  return {
    width: `${rect.w}px`,
    height: `${rect.h}px`,
    transform: `translate3d(${rect.x}px, ${rect.y}px, 0)`,
  }
}

export interface SlidingNavItem {
  to: string
  label: ReactNode
  end?: boolean
}

export function SlidingNav({ items }: { items: SlidingNavItem[] }) {
  const location = useLocation()
  const activeItem = items.find((item) =>
    item.end
      ? location.pathname === item.to
      : location.pathname === item.to || location.pathname.startsWith(`${item.to}/`),
  )
  const activeKey = activeItem?.to ?? null

  const {
    containerRef,
    activeRect,
    activeSliding,
    pulseKey,
    hoverRect,
    hoverSliding,
    onItemEnter,
    onContainerLeave,
  } = useSlidingPill(activeKey)

  return (
    <nav
      className="app-nav"
      ref={(node) => {
        containerRef.current = node
      }}
      onMouseLeave={onContainerLeave}
    >
      <span
        aria-hidden="true"
        className={`sliding-pill-hover nav-pill-hover${hoverRect.visible ? ' is-visible' : ''}${
          hoverSliding ? ' is-sliding' : ''
        }`}
        style={pillInlineStyle(hoverRect)}
      />
      <span
        aria-hidden="true"
        className={`sliding-pill-active nav-pill-active${activeRect.visible ? ' is-visible' : ''}${
          activeSliding ? ' is-sliding' : ''
        }`}
        style={pillInlineStyle(activeRect)}
      >
        <span
          key={pulseKey}
          className={`sliding-pill-surface${pulseKey > 0 ? ' is-pulsing' : ''}`}
        />
      </span>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          data-pill-key={item.to}
          onMouseEnter={(e) => onItemEnter(e.currentTarget)}
          onFocus={(e) => onItemEnter(e.currentTarget)}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

export interface SlidingTabItem<T extends string> {
  value: T
  label: ReactNode
  disabled?: boolean
}

export function SlidingTabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  variant = 'brand',
  size = 'md',
  className = '',
}: {
  items: ReadonlyArray<SlidingTabItem<T>>
  value: T | null
  onChange: (value: T) => void
  ariaLabel: string
  variant?: 'brand' | 'surface' | 'subtle'
  size?: 'md' | 'sm'
  className?: string
}) {
  const {
    containerRef,
    activeRect,
    activeSliding,
    pulseKey,
    hoverRect,
    hoverSliding,
    onItemEnter,
    onContainerLeave,
  } = useSlidingPill(value)

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const enabled = items.filter((item) => !item.disabled)
    if (enabled.length < 2) return
    const currentIndex = enabled.findIndex((item) => item.value === value)
    const step = e.key === 'ArrowRight' ? 1 : -1
    const nextIndex =
      currentIndex === -1
        ? 0
        : (currentIndex + step + enabled.length) % enabled.length
    const nextItem = enabled[nextIndex]
    if (!nextItem) return
    e.preventDefault()
    onChange(nextItem.value)
    const btn = containerRef.current?.querySelector<HTMLButtonElement>(
      `[data-pill-key="${escapeSelectorAttr(nextItem.value)}"]`,
    )
    btn?.focus()
  }

  const classes = [
    'tabs',
    'tabs-sliding',
    `tabs-${variant}`,
    size === 'sm' ? 'tabs-sm' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      ref={(node) => {
        containerRef.current = node
      }}
      className={classes}
      role="tablist"
      aria-label={ariaLabel}
      onMouseLeave={onContainerLeave}
      onKeyDown={onKeyDown}
    >
      <span
        aria-hidden="true"
        className={`sliding-pill-hover tabs-pill-hover${hoverRect.visible ? ' is-visible' : ''}${
          hoverSliding ? ' is-sliding' : ''
        }`}
        style={pillInlineStyle(hoverRect)}
      />
      <span
        aria-hidden="true"
        className={`sliding-pill-active tabs-pill-active${activeRect.visible ? ' is-visible' : ''}${
          activeSliding ? ' is-sliding' : ''
        }`}
        style={pillInlineStyle(activeRect)}
      >
        <span
          key={pulseKey}
          className={`sliding-pill-surface${pulseKey > 0 ? ' is-pulsing' : ''}`}
        />
      </span>
      {items.map((item) => {
        const isActive = value === item.value
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={item.disabled}
            data-pill-key={item.value}
            className={isActive ? 'active' : ''}
            onClick={() => onChange(item.value)}
            onMouseEnter={(e) => {
              if (!item.disabled) onItemEnter(e.currentTarget)
            }}
            onFocus={(e) => {
              if (!item.disabled) onItemEnter(e.currentTarget)
            }}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

function getRouteRank(pathname: string): number {
  if (pathname === '/') return 0
  if (pathname.startsWith('/priority')) return 1
  if (pathname === '/customers') return 2
  if (pathname.startsWith('/customers/')) return 2.5
  if (pathname.startsWith('/settings')) return 3
  return 0
}

export function PageStage({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navRef = useRef<{ pathname: string; dir: -1 | 0 | 1 }>({
    pathname: location.pathname,
    dir: 0,
  })

  if (navRef.current.pathname !== location.pathname) {
    const prevRank = getRouteRank(navRef.current.pathname)
    const nextRank = getRouteRank(location.pathname)
    const dir: -1 | 0 | 1 = nextRank > prevRank ? 1 : nextRank < prevRank ? -1 : 0
    navRef.current = { pathname: location.pathname, dir }
  }

  return (
    <>
      <div key={`wash-${location.pathname}`} className="page-wash" aria-hidden="true" />
      <main
        className="page"
        style={{ '--enter-dir': navRef.current.dir } as CSSProperties}
      >
        <div key={location.pathname} className="page-stage">
          {children}
        </div>
      </main>
    </>
  )
}

export function Collapsible({
  open,
  children,
  className = '',
}: {
  open: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={`collapsible${open ? ' is-open' : ''}${className ? ` ${className}` : ''}`}
      aria-hidden={!open}
    >
      <div className="collapsible-inner">{children}</div>
    </div>
  )
}
