"""Linking catalog jobs to a user: one user_jobs row per user and job, however many times it arrives.

Used by alert emails (ingestion) and by company feeds and job-search APIs (sources). Runs inside the user's
`user_scope`, after `upsert_cards` has stored the cards in the shared catalog.
"""

from uuid import UUID

from sqlalchemy import case, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.parsers import JobCard
from app.modules.catalog.service import CatalogMatch
from app.modules.jobs import duplicates
from app.modules.jobs.models import LEAD_RANK, UserJob


async def link_cards(
    db: AsyncSession,
    user_id: UUID,
    cards: list[JobCard],
    matches: list[CatalogMatch],
    inbound_message_id: UUID | None = None,
) -> list[UUID]:
    """Add or refresh the user's row for each card. Returns the ids of rows that are new to the user (not ones
    merged at once into a job they already have)."""
    added: list[UUID] = []
    seen: list[UUID] = []
    for card, match in zip(cards, matches, strict=True):
        row = {
            "user_id": user_id,
            "job_id": match.job_id,
            "inbound_message_id": inbound_message_id,
            "lead": card.lead,
            "outside_preference": card.outside_preference,
            "apply_url": card.apply_url,
            "card_details": {"card_lines": list(card.card_lines)} if card.card_lines else {},
        }
        stmt = insert(UserJob).values(**row)
        new = stmt.excluded
        set_ = {
            "last_seen_at": func.now(),
            "card_details": new.card_details,
            "apply_url": func.coalesce(new.apply_url, UserJob.apply_url),
            "outside_preference": UserJob.outside_preference & new.outside_preference,
            "lead": _stronger_lead(UserJob.lead, new.lead),
            # A fresh sighting is a sign the job is still open: undo an automatic expiry (one the user chose
            # stays).
            **_revive_if_auto_expired(),
        }
        if inbound_message_id is not None:
            set_["inbound_message_id"] = new.inbound_message_id
        # Seen again: refresh what the latest sighting says, keep the user's status (ignored stays ignored)
        # and the strongest lead. xmax = 0 only on a freshly inserted row.
        result = await db.execute(
            stmt.on_conflict_do_update(index_elements=[UserJob.user_id, UserJob.job_id], set_=set_).returning(
                UserJob.id, literal_column("xmax = 0")
            )
        )
        uj_id, inserted = result.one()
        seen.append(uj_id)
        if inserted:
            added.append(uj_id)
    # A job merged as a duplicate, seen again: the one it was merged into is still being advertised.
    merged_into = select(UserJob.duplicate_of).where(UserJob.id.in_(seen), UserJob.status == "duplicate")
    await db.execute(update(UserJob).where(UserJob.id.in_(merged_into)).values(last_seen_at=func.now()))
    # The same role from another portal or poster: merged when certain, otherwise flagged for the user.
    merged = await duplicates.check(db, user_id, added)
    return [i for i in added if i not in merged]


def _revive_if_auto_expired() -> dict:
    auto = (UserJob.status == "expired") & (UserJob.expired_by == "auto")
    return {
        "status": case((auto, "seen"), else_=UserJob.status),
        "expired_at": case((auto, None), else_=UserJob.expired_at),
        "expired_by": case((auto, None), else_=UserJob.expired_by),
    }


def _rank(lead):
    return case(LEAD_RANK, value=lead, else_=0)


def _stronger_lead(current, incoming):
    return case((_rank(incoming) > _rank(current), incoming), else_=current)
