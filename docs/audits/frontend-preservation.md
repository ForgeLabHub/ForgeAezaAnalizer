# Frontend preservation record

Date: 2026-10-24. Branch `feat/deployment-readiness`.
Scope: `frontend/` (React 18 + TypeScript + Vite SPA).

This file records the interface as it exists so later changes can be checked
against it. The rule for this iteration was: **keep the existing product, fix
defects, do not redesign.** Nothing in this document authorises a new visual
language, a second interface, or the removal of a working screen.

## 1. Stack (unchanged)

| Item | Value | Where |
| --- | --- | --- |
| Framework | React 18.3 | `frontend/package.json` |
| Language | TypeScript ~5.6 | `frontend/tsconfig.json` |
| Bundler | Vite 5.4 | `frontend/vite.config.ts` |
| Routing | react-router-dom 6.28 | `frontend/src/App.tsx` |
| Styling | one hand-written stylesheet, CSS custom properties | `frontend/src/styles.css` (1678 lines) |
| Icons | inline SVG only (no icon font) | `components/`, `pages/` |
| Test runner | none configured | `package.json` has no `test` script |

No dependency was added or removed in this iteration.

## 2. Screens and their purpose

| Route | Component | Purpose | Primary API |
| --- | --- | --- | --- |
| `/login` | `pages/LoginPage.tsx` | email + password sign-in | `POST /api/v1/auth/login`, `GET /api/v1/auth/me` |
| `/` | `pages/DashboardPage.tsx` | headline metrics, risk distribution, top exposure, upcoming renewals | `GET /api/v1/analytics/summary` |
| `/customers` | `pages/CustomersPage.tsx` | sortable, filterable, searchable customer table | `GET /api/v1/customers`, `GET /api/v1/export/customers.csv` |
| `/customers/:id` | `pages/CustomerDetailPage.tsx` | one customer: services, factor explanations, recommendations | `GET /api/v1/customers/{id}`, `.../recommendations` |
| `/actions` | `pages/ActionCenterPage.tsx` | work queues / priority view | `GET /api/v1/priority` |
| `/what-if` | `pages/WhatIfPage.tsx` | compare parameter scenarios against the baseline without persisting | `POST /api/v1/scenarios/compare` |
| `/settings` | `pages/SettingsPage.tsx` | edit weights, thresholds, horizon, window; reset to defaults | `GET/PATCH /api/v1/model/settings`, `POST .../reset` |

Shared components: `components/ui.tsx` (`RiskBadge`, `StatusBadge`, `ScoreBar`,
`ScoreCell`, `Metric`, `EmptyState`, `Loading`, `ErrorBox`, `BarChart`,
`formatEur`, `formatDateTime`, `formatDate`, `formatDays`),
`components/AezaLogoDropdown.tsx`, `components/Playbooks.tsx`.
Data access is centralised in `lib/api.ts`; session state in `lib/auth.tsx`;
theme in `lib/theme.tsx`.

## 3. Visual language to preserve

Defined as CSS custom properties at the top of `styles.css`:

- **Neutrals** `--n-0` … `--n-900`, a slightly warm off-white canvas (`--canvas`).
- **One brand accent** — Aéza orange `--brand-500: #ff6b00`, used for primary
  actions and the logo; `--brand-gradient` and `--brand-glow` used sparingly.
- **A three-step risk scale** kept distinct from the brand accent:
  low green, medium amber, high red, plus a neutral `na` tone.
- **Dark theme** through `:root[data-theme='dark']`; the choice is applied in
  `index.html` before first paint to avoid a light flash.
- Typeface Inter (Google Fonts), heavy tight headings, rounded surfaces,
  pill-shaped controls.
- Responsive breakpoints at **1100 px, 720 px, 520 px**.

Preservation rules applied:

1. Do not introduce a second colour system or a template theme.
2. Do not replace the stylesheet with a UI framework.
3. Keep the customer table inside `.table-wrap`; page-level horizontal overflow
   at narrow widths is a regression (the header wraps at ≤720 px).
4. Keep the existing page composition and navigation order.
5. New states must reuse the existing `Loading`, `ErrorBox`, `EmptyState`,
   `Metric`, and badge components rather than inventing parallel ones.

## 4. Per-screen behaviour contract

For every screen the following states were checked during the walkthrough
(see `final-project-completion.md` §"End-to-end verification" for the evidence):

| Screen | loading | empty | error | success | offline |
| --- | --- | --- | --- | --- | --- |
| Login | button shows `Вход…`, disabled | n/a | `ErrorBox` with the server detail | redirect to `/` | "Не удалось связаться с сервером…" from `api.ts` |
| Dashboard | `Loading` | `EmptyState` when no customers | `ErrorBox` | metrics + chart + tables | error surfaced, spinner stops |
| Customers | `Loading` | `EmptyState` | `ErrorBox` | table, sort arrows, pagination | error surfaced |
| Customer detail | `Loading` | n/a | `ErrorBox` | factors, services, recommendations | error surfaced |
| Action Center | `Loading` | `EmptyState` | `ErrorBox` | queues by category | error surfaced |
| What-if | `Loading` | n/a | `ErrorBox` | baseline vs scenario comparison | error surfaced |
| Settings | `Loading` | n/a | `ErrorBox` | toast `Настройки сохранены, аналитика пересчитана.` | error surfaced |

`lib/api.ts` maps a network failure to `ApiError(0, 'Не удалось связаться с
сервером…')`, and every page renders `err.detail` for `ApiError` and a page
specific fallback otherwise. No page swallows an error into a fake success.

## 5. Known constraints (recorded, not fixed here)

- **No frontend test runner.** `package.json` has no `test` script and no
  vitest/jest/playwright dependency. The UI is verified by the manual browser
  walkthrough documented in `docs/demo.md` and by the production build. Adding a
  runner is a deliberate follow-up, not a defect fixed in this iteration.
- **Live refresh.** A coefficient change made on `/settings` re-fetches that
  page's own summary. Propagation to other open tabs is handled by a small
  authenticated poll (`lib/live.tsx`, `LiveProvider` / `useLiveGeneration`)
  rather than the backend SSE route, because `EventSource` cannot send the
  bearer header and putting the token in the query string would leak it into
  access logs. The case lets the author choose the mechanism.
- **Token storage.** The access token is kept in `localStorage`
  (`aeza.token`). This matches the existing product; moving to an HttpOnly
  cookie is a security decision outside this iteration's scope.

## 6. Change log for this iteration (design-neutral)

| Change | File | Reason |
| --- | --- | --- |
| Session restore clears an invalid token | `lib/auth.tsx` (existing behaviour, verified) | avoids a stuck "Проверка сессии…" state |
| No visual/composition changes | — | preservation rule |

Any future change that alters composition, palette, typography, or navigation
must be justified in its commit message by a concrete defect and must stay
inside the visual language described in §3.
