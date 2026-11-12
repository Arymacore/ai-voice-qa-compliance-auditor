"""
storage.py

Saves analysis results (the JSON contract from src/scoring/analysis.py) so the
API and dashboard can list, filter, and reopen them later.

Design: each call is one row. The fields the dashboard filters and sorts on
(status, needs_review, scores, dates) are real columns; the full result is kept
as JSON text in `result_json`, so the contract can grow without schema changes.
SQLAlchemy keeps this portable: SQLite for development, PostgreSQL at
deployment. Set DATABASE_URL and nothing else changes.

DATABASE_URL examples:
    sqlite:///data/calls.db                           (default if unset)
    postgresql+psycopg2://user:pass@host:5432/dbname  (deployment)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import Boolean, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

ROOT = Path(__file__).resolve().parents[1]


class Base(DeclarativeBase):
    pass


class CallRecord(Base):
    __tablename__ = "calls"

    call_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_file: Mapped[str] = mapped_column(Text, default="")
    analyzed_at: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reasons: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    compliance_status: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)
    compliance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tone_flag: Mapped[str | None] = mapped_column(String(15), nullable=True)
    tone_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str] = mapped_column(Text)  # the full contract


def default_url(load_env: bool = True) -> str:
    """DATABASE_URL if set (env or .env file), otherwise a local SQLite file."""
    if load_env:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    path = ROOT / "data" / "calls.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def _record_from_result(result: dict) -> CallRecord:
    call_id = result.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("Cannot store a result without a call_id.")
    compliance = result.get("compliance") or {}
    tone = result.get("tone") or {}
    return CallRecord(
        call_id=call_id,
        source_file=result.get("source_file", ""),
        analyzed_at=result.get("analyzed_at"),
        needs_review=bool(result.get("needs_review", False)),
        review_reasons=json.dumps(result.get("review_reasons", [])),
        compliance_status=compliance.get("status"),
        compliance_score=compliance.get("score"),
        tone_flag=tone.get("flag"),
        tone_score=tone.get("score"),
        error=result.get("error"),
        result_json=json.dumps(result, ensure_ascii=False),
    )


def _combined(compliance_score, tone_score):
    if compliance_score is None:
        return None
    from src.scoring.analysis import combined_score

    return combined_score(compliance_score, tone_score)


def _summary_row(rec: CallRecord) -> dict:
    """Lightweight row for list views: no transcript, no per-rule detail."""
    return {
        "call_id": rec.call_id,
        "source_file": rec.source_file,
        "analyzed_at": rec.analyzed_at,
        "needs_review": rec.needs_review,
        "review_reasons": json.loads(rec.review_reasons),
        "compliance_status": rec.compliance_status,
        "compliance_score": rec.compliance_score,
        "tone_flag": rec.tone_flag,
        "tone_score": rec.tone_score,
        "combined_score": _combined(rec.compliance_score, rec.tone_score),
        "error": rec.error,
    }


class Store:
    def __init__(self, url: str | None = None):
        self.url = url or default_url()
        kwargs = {}
        if self.url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}  # API threads share it
        self.engine = create_engine(self.url, **kwargs)
        Base.metadata.create_all(self.engine)

    @property
    def safe_url(self) -> str:
        """The URL with any password hidden, safe to print."""
        return self.engine.url.render_as_string(hide_password=True)

    def close(self) -> None:
        self.engine.dispose()

    def save(self, result: dict) -> None:
        """Insert a result, or replace the stored one with the same call_id."""
        self.save_many([result])

    def save_many(self, results: list[dict]) -> None:
        records = [_record_from_result(r) for r in results]  # validate everything first
        with Session(self.engine) as session, session.begin():
            for rec in records:
                session.merge(rec)

    def get(self, call_id: str) -> dict | None:
        """The full stored result (including transcript), or None."""
        with Session(self.engine) as session:
            rec = session.get(CallRecord, call_id)
            if rec is None:
                return None
            result = json.loads(rec.result_json)
            if "error" not in result and "combined_score" not in result:
                result["combined_score"] = _combined(rec.compliance_score, rec.tone_score)
            return result

    def list(
        self,
        needs_review: bool | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Summary rows, newest first, optionally filtered."""
        query = select(CallRecord)
        if needs_review is not None:
            query = query.where(CallRecord.needs_review == needs_review)
        if status is not None:
            query = query.where(CallRecord.compliance_status == status)
        query = query.order_by(CallRecord.analyzed_at.desc(), CallRecord.call_id)
        query = query.limit(limit).offset(offset)
        with Session(self.engine) as session:
            return [_summary_row(rec) for rec in session.scalars(query)]

    def delete(self, call_id: str) -> bool:
        with Session(self.engine) as session, session.begin():
            rec = session.get(CallRecord, call_id)
            if rec is None:
                return False
            session.delete(rec)
            return True

    def summary(self) -> dict:
        """Headline numbers for a dashboard header."""
        with Session(self.engine) as session:
            rows = list(session.scalars(select(CallRecord)))
        analyzed = [r for r in rows if r.error is None]
        by_status = {"PASS": 0, "REVIEW": 0, "FAIL": 0}
        for r in analyzed:
            if r.compliance_status in by_status:
                by_status[r.compliance_status] += 1
        return {
            "total": len(rows),
            "analyzed": len(analyzed),
            "errors": len(rows) - len(analyzed),
            "by_status": by_status,
            "needs_review": sum(r.needs_review for r in analyzed),
            "tone_review": sum(r.tone_flag == "REVIEW" for r in analyzed),
        }