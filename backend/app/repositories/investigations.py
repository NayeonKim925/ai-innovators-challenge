"""In-process storage for investigation results and expert reviews (2-A).

★ 왜 DB가 아니라 in-memory인가 ★
`pyproject.toml`에는 아직 어떤 DB 드라이버도 없다 (sqlalchemy/alembic 등 없음).
`docs/IMPLEMENTATION_PLAN.md` 트랙 D는 최종적으로 SQLite/PostgreSQL 도입을
목표로 하지만(M2 DoD), 이번 2단계 범위(#14/#15)는 "검토·보고서 API가 실제로
동작한다"는 것을 코드로 보이는 것이다. `app.main`의 `/api/health`가 스스로
밝히는 `deployment: "local-research"` 그대로, 프로세스 생명주기 동안만
유지되는 저장소로 이 범위는 충분하다. 서버를 재시작하면 저장된 조사/검토가
사라진다는 건 알려진 한계이며, 후속 트랙 D 작업(DB 도입)에서 교체될 대상이다.
이 파일의 경로(`backend/app/repositories/investigations.py`)는 IMPLEMENTATION_PLAN.md
트랙 D 표에 이미 예고돼 있던 그대로다.
"""

from __future__ import annotations

from ..domain import InvestigationResult, StoredReview


class InvestigationNotFoundError(LookupError):
    """Raised when a caller references an investigation id that was never stored."""


class InMemoryInvestigationRepository:
    """Keyed by the opaque investigation id minted at `POST .../investigations` time."""

    def __init__(self) -> None:
        self._results: dict[str, InvestigationResult] = {}
        self._reviews: dict[str, list[StoredReview]] = {}

    def save(self, investigation_id: str, result: InvestigationResult) -> None:
        self._results[investigation_id] = result
        self._reviews.setdefault(investigation_id, [])

    def replace(self, investigation_id: str, result: InvestigationResult) -> None:
        if investigation_id not in self._results:
            raise InvestigationNotFoundError(investigation_id)
        self._results[investigation_id] = result

    def get(self, investigation_id: str) -> InvestigationResult | None:
        return self._results.get(investigation_id)

    def add_review(self, investigation_id: str, review: StoredReview) -> StoredReview:
        if investigation_id not in self._results:
            raise InvestigationNotFoundError(investigation_id)
        self._reviews[investigation_id].append(review)
        return review

    def list_reviews(self, investigation_id: str) -> list[StoredReview]:
        return list(self._reviews.get(investigation_id, []))
