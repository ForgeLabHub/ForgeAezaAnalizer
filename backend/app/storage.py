from __future__ import annotations

from sqlalchemy import String, cast, func, or_, select, update

from core import Analysis, NotReadyError, ResourceNotFoundError, State
from backend.app.db import AnalysisRow, AuditRow, CurrentRow, CustomerRow, Database, ModelRow, ObservationRow, ServiceIndexRow, SourceRow

EMPTY_SOURCE = {"accounts": [], "services": [], "transactions": []}


class Storage:
    def __init__(self, database: Database):
        self.database = database

    def load(self) -> State:
        with self.database.sessions() as session:
            current = session.get(CurrentRow, 1)
            if current is None or not current.generation:
                return State(0, 0, 0, EMPTY_SOURCE, {})
            analysis = session.get(AnalysisRow, current.generation)
            source = session.get(SourceRow, analysis.source_version)
            model = session.get(ModelRow, analysis.model_version)
            return State(analysis.generation, source.version, model.version, source.payload,
                model.payload, source.captured_at, analysis.as_of, analysis.calculated_at)

    def publish(self, previous: State, candidate: State, result: Analysis, actor: str) -> bool:
        with self.database.transaction() as session:
            changed = session.execute(update(CurrentRow).where(
                CurrentRow.id == 1, CurrentRow.generation == previous.generation,
            ).values(generation=candidate.generation, source_version=candidate.source_version,
                model_version=candidate.model_version))
            if not changed.rowcount:
                return False
            source_changed = previous.source_version != candidate.source_version
            model_changed = previous.model_version != candidate.model_version
            if source_changed:
                session.add(SourceRow(version=candidate.source_version,
                    captured_at=candidate.captured_at, payload=candidate.source))
            if model_changed:
                session.add(ModelRow(version=candidate.model_version,
                    created_at=candidate.calculated_at, payload=candidate.settings))
            session.flush()
            session.add(AnalysisRow(generation=candidate.generation, source_version=candidate.source_version,
                model_version=candidate.model_version, as_of=candidate.as_of,
                calculated_at=candidate.calculated_at, summary=result.summary))
            session.flush()
            for customer in result.customers:
                session.add(CustomerRow(generation=candidate.generation, customer_id=customer["id"],
                    email=customer["email"].lower(), risk_score=customer["riskScore"],
                    risk_category=customer["riskCategory"], balance=customer["balance"]["cents"],
                    total_replenished=customer["totalReplenished"]["cents"], payload=customer))
                session.add_all(ServiceIndexRow(generation=candidate.generation, service_id=item["id"],
                    customer_id=customer["id"], status=item["status"]) for item in customer["services"])
            if source_changed:
                before = {item["id"]: item["status"] for item in previous.source["services"]}
                after = {item["id"]: item["status"] for item in candidate.source["services"]}
                for service_id in sorted(before.keys() | after.keys()):
                    if service_id not in before or before.get(service_id) != after.get(service_id):
                        session.add(ObservationRow(source_version=candidate.source_version, service_id=service_id,
                            previous_status=before.get(service_id), status=after.get(service_id),
                            observed_at=candidate.captured_at, previous_observed_at=previous.captured_at))
            session.add(AuditRow(generation=candidate.generation, actor=actor,
                action="source" if source_changed else "model" if model_changed else "clock",
                created_at=candidate.calculated_at))
        return True

    @staticmethod
    def _generation(session, generation: int | None) -> int:
        if generation is not None:
            if session.get(AnalysisRow, generation) is None:
                raise ResourceNotFoundError("Версия расчёта не найдена")
            return generation
        current = session.get(CurrentRow, 1)
        if not current or not current.generation:
            raise NotReadyError("Расчёт ещё не опубликован")
        return current.generation

    def summary(self, generation: int | None = None) -> dict:
        with self.database.sessions() as session:
            return session.get(AnalysisRow, self._generation(session, generation)).summary

    def customers(self, *, generation=None, search=None, risk_category=None,
                  service_status=None, sort_by="riskScore", sort_dir="desc", page=1, page_size=25) -> dict:
        with self.database.sessions() as session:
            generation = self._generation(session, generation)
            statement = select(CustomerRow).where(CustomerRow.generation == generation)
            if search and search.strip():
                needle = search.strip().lower().replace("/", "//").replace("%", "/%").replace("_", "/_")
                statement = statement.where(or_(CustomerRow.email.like(f"%{needle}%", escape="/"),
                    cast(CustomerRow.customer_id, String).like(f"%{needle}%", escape="/")))
            if risk_category:
                statement = statement.where(CustomerRow.risk_category == risk_category)
            if service_status:
                statement = statement.where(select(ServiceIndexRow.service_id).where(
                    ServiceIndexRow.generation == generation,
                    ServiceIndexRow.customer_id == CustomerRow.customer_id,
                    ServiceIndexRow.status == service_status).exists())
            total = session.scalar(select(func.count()).select_from(statement.subquery()))
            column = {"id": CustomerRow.customer_id, "email": CustomerRow.email,
                "riskScore": CustomerRow.risk_score, "balance": CustomerRow.balance,
                "totalReplenished": CustomerRow.total_replenished}[sort_by]
            order = column.desc() if sort_dir == "desc" else column.asc()
            rows = session.scalars(statement.order_by(column.is_(None), order, CustomerRow.customer_id.asc()
                ).offset((page - 1) * page_size).limit(page_size)).all()
            detail_keys = {"services", "reasons", "recommendations", "renewalDetails"}
            return {"items": [{key: value for key, value in row.payload.items() if key not in detail_keys} for row in rows],
                "page": page, "pageSize": page_size, "total": total,
                "pages": max(1, (total + page_size - 1) // page_size), "sortBy": sort_by, "sortDir": sort_dir,
                **session.get(AnalysisRow, generation).summary["version"]}

    def customer(self, customer_id: int, generation=None) -> dict:
        with self.database.sessions() as session:
            generation = self._generation(session, generation)
            row = session.get(CustomerRow, (generation, customer_id))
            if row is None:
                raise ResourceNotFoundError(f"Клиент {customer_id} не найден")
            return {**row.payload, **session.get(AnalysisRow, generation).summary["version"]}

    def model(self, generation=None) -> dict:
        with self.database.sessions() as session:
            generation = self._generation(session, generation)
            analysis = session.get(AnalysisRow, generation)
            row = session.get(ModelRow, analysis.model_version)
            return {"settings": row.payload, "updatedAt": row.created_at.isoformat(), **analysis.summary["version"]}

    def source(self, generation=None) -> dict:
        with self.database.sessions() as session:
            generation = self._generation(session, generation)
            analysis = session.get(AnalysisRow, generation)
            row = session.get(SourceRow, analysis.source_version)
            return {"counts": {key: len(value) for key, value in row.payload.items()},
                "capturedAt": row.captured_at.isoformat(), **analysis.summary["version"]}

    def observations(self, *, service_id: int | None = None, limit: int = 100) -> list[dict]:
        with self.database.sessions() as session:
            statement = select(ObservationRow)
            if service_id is not None:
                statement = statement.where(ObservationRow.service_id == service_id)
            rows = session.scalars(statement.order_by(ObservationRow.source_version.desc(),
                ObservationRow.service_id).limit(limit))
            return [{"sourceVersion": row.source_version, "serviceId": row.service_id,
                "previousStatus": row.previous_status, "status": row.status,
                "observedAt": row.observed_at.isoformat(),
                "previousObservedAt": row.previous_observed_at.isoformat() if row.previous_observed_at else None,
                "eventAt": None} for row in rows]
