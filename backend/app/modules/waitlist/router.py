"""The home page waitlist and the contact page: anyone can write; only the super admin reads them."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import CurrentUser, UserDB, require_super_admin
from app.modules.waitlist.models import ContactMessage, WaitlistEntry

router = APIRouter(tags=["waitlist"])
DB = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[CurrentUser, Depends(require_super_admin)]


class WaitlistIn(BaseModel):
    email: EmailStr = Field(max_length=254)
    source: Literal["home"] = "home"
    # Hidden field on the form: people leave it empty, form-filling bots don't.
    website: str = ""


class WaitlistJoined(BaseModel):
    joined: Literal[True] = True


class WaitlistEntryOut(BaseModel):
    model_config = {"from_attributes": True}

    email: str
    source: str
    created_at: datetime


class WaitlistOut(BaseModel):
    total: int
    entries: list[WaitlistEntryOut]


@router.post("/waitlist", response_model=WaitlistJoined, status_code=201)
async def join_waitlist(body: WaitlistIn, db: DB):
    """Always the same answer, so the form can't be used to find out who is on the list."""
    if not body.website:
        await db.execute(
            text(
                "insert into waitlist (id, email, source) values (:id, :email, :source) "
                "on conflict (lower(email)) do nothing"
            ),
            {"id": uuid4(), "email": str(body.email), "source": body.source},
        )
    return WaitlistJoined()


@router.get("/admin/waitlist", response_model=WaitlistOut)
async def waitlist(
    _: Admin,
    db: UserDB,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    total = await db.scalar(select(func.count()).select_from(WaitlistEntry)) or 0
    rows = await db.scalars(
        select(WaitlistEntry).order_by(WaitlistEntry.created_at.desc()).limit(limit).offset(offset)
    )
    return WaitlistOut(total=total, entries=list(rows))


# --- Contact page ---------------------------------------------------------------------------------------------


class ContactMessageIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=254)
    topic: Literal["general", "support", "privacy", "feedback"] = "general"
    message: str = Field(min_length=10, max_length=2000)
    website: str = ""  # hidden field: people leave it empty, form-filling bots don't


class ContactReceived(BaseModel):
    received: Literal[True] = True


class ContactMessageOut(BaseModel):
    model_config = {"from_attributes": True}

    name: str
    email: str
    topic: str
    message: str
    created_at: datetime


class ContactMessageList(BaseModel):
    total: int
    messages: list[ContactMessageOut]


@router.post("/contact", response_model=ContactReceived, status_code=201)
async def contact(body: ContactMessageIn, db: DB):
    """A message for the BrewMyJob team (privacy requests too). Read by the super admin on Admin settings."""
    if not body.website:
        db.add(
            ContactMessage(
                id=uuid4(),
                name=body.name.strip(),
                email=str(body.email),
                topic=body.topic,
                message=body.message.strip(),
            )
        )
    return ContactReceived()


@router.get("/admin/contact", response_model=ContactMessageList)
async def contact_messages(
    _: Admin,
    db: UserDB,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    total = await db.scalar(select(func.count()).select_from(ContactMessage)) or 0
    rows = await db.scalars(
        select(ContactMessage).order_by(ContactMessage.created_at.desc()).limit(limit).offset(offset)
    )
    return ContactMessageList(total=total, messages=list(rows))
