import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

const KEY_EDGE =
  'M.312 10.443v14.185c0 2.107 0 3.16.177 4.035a8.894 8.894 0 0 0 6.948 6.948c.875.178 1.929.178 4.036.178h13.022c3.155 0 4.732 0 6.002-.439a8.005 8.005 0 0 0 4.953-4.953c.439-1.27.439-2.847.439-6.002V10.443c0-1.242 0-1.862-.062-2.384A8.894 8.894 0 0 0 28.042.274C27.52.212 26.899.212 25.657.212h-15.18c-3.048 0-4.572 0-5.783.473a6.893 6.893 0 0 0-3.909 3.91C.312 5.804.312 7.35.312 10.442Z'

const GLYPH_A =
  'M14.624 28.082c2.33 0 3.839-1.017 4.609-2.484h.123v2.186h4.147V17.15c0-3.757-3.182-5.338-6.693-5.338-3.777 0-6.262 1.806-6.867 4.68l4.044.329c.298-1.047 1.232-1.817 2.802-1.817 1.489 0 2.34.75 2.34 2.043v.061c0 1.017-1.077 1.15-3.818 1.417-3.12.287-5.923 1.334-5.923 4.855 0 3.12 2.228 4.702 5.236 4.702Zm1.252-3.018c-1.345 0-2.31-.626-2.31-1.827 0-1.232 1.016-1.838 2.556-2.053.955-.134 2.515-.36 3.039-.709v1.674c0 1.652-1.366 2.915-3.285 2.915Z'

const GLYPH_E =
  'M17.281 28.092c3.9 0 6.529-1.899 7.144-4.824L20.381 23c-.441 1.2-1.57 1.827-3.028 1.827-2.187 0-3.572-1.447-3.572-3.798v-.01h10.737v-1.201c0-5.359-3.244-8.007-7.412-8.007-4.64 0-7.647 3.295-7.647 8.16 0 5 2.967 8.12 7.822 8.12Zm-3.5-9.782c.092-1.797 1.457-3.234 3.397-3.234 1.9 0 3.213 1.355 3.223 3.234h-6.62Zm1.652-8.325h3.09l3.13-4.67H17.61l-2.176 4.67Z'

const GLYPH_Z = 'M10.18 27.7h13.41v-3.53h-7.6v-.11l7.33-9.43v-2.88H10.45v3.53h7.54v.11l-7.81 9.67v2.64Z'

function Keycap({ glyph, accent }: { glyph: string; accent?: boolean }) {
  return (
    <svg className="aeza-key" viewBox="0 0 36 36" width="36" height="36" fill="none" aria-hidden="true">
      <path d={KEY_EDGE} fill="var(--key-edge)" />
      <rect x="1.201" y="1.101" width="31.13" height="31.13" rx="6.671" fill="var(--key-face)" />
      <path d={glyph} fill={accent ? 'var(--key-accent)' : 'var(--key-glyph)'} />
    </svg>
  )
}

export function AezaLogo({ to = '/', label = 'Aéza Sentinel' }: { to?: string; label?: string }) {
  const [hover, setHover] = useState(false)
  const [touched, setTouched] = useState(false)
  const rowRef = useRef<HTMLSpanElement>(null)

  function enter() {
    setHover(true)
    setTouched(true)
  }

  function press() {
    rowRef.current?.animate(
      [{ transform: 'scale(1)' }, { transform: 'scale(0.88)', offset: 0.35 }, { transform: 'scale(1)' }],
      { duration: 350, easing: 'ease-out' },
    )
  }

  const state = hover ? 'is-open' : touched ? 'is-closed' : ''

  return (
    <Link
      to={to}
      aria-label={label}
      className={`aeza-logo ${state}`}
      onMouseEnter={enter}
      onMouseLeave={() => setHover(false)}
      onFocus={enter}
      onBlur={() => setHover(false)}
      onPointerDown={press}
    >
      <span className="aeza-logo-row" ref={rowRef}>
        <span className="aeza-tile t-a">
          <Keycap glyph={GLYPH_A} />
        </span>
        <span className="aeza-tile t-e">
          <Keycap glyph={GLYPH_E} />
        </span>
        <span className="aeza-tile t-z">
          <Keycap glyph={GLYPH_Z} />
        </span>
        <span className="aeza-tile t-last">
          <Keycap glyph={GLYPH_A} />
        </span>
      </span>
      <span className="brand-sub">Sentinel</span>
    </Link>
  )
}

export function AezaWordmark() {
  return (
    <span className="aeza-logo is-static" aria-label="Aéza">
      <span className="aeza-logo-row">
        <span className="aeza-tile">
          <Keycap glyph={GLYPH_A} />
        </span>
        <span className="aeza-tile">
          <Keycap glyph={GLYPH_E} />
        </span>
        <span className="aeza-tile">
          <Keycap glyph={GLYPH_Z} />
        </span>
        <span className="aeza-tile">
          <Keycap glyph={GLYPH_A} />
        </span>
      </span>
      <span className="brand-sub">Sentinel</span>
    </span>
  )
}
