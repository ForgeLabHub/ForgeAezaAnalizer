import { AIAnalystPanel } from '../components/AIAnalystPanel'

/**
 * Dedicated AI Analyst page. The panel is the same component embedded in the
 * customer card, so the portfolio view and the per-customer view cannot drift
 * apart. No separate application or design system is introduced.
 */
export default function AIAnalystPage() {
  return (
    <div className="page-body">
      <div className="page-head">
        <div>
          <h1>AI-аналитик</h1>
          <p className="muted">
            Объяснения строятся на данных Risk Engine через backend-инструменты и локальную
            документацию (RAG). Баллы и суммы модель не пересчитывает — она их объясняет.
          </p>
        </div>
      </div>
      <AIAnalystPanel />
    </div>
  )
}
