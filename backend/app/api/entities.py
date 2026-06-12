"""Entity mention + tooltip API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.entity_tooltip import find_mentions, get_tooltip

router = APIRouter(prefix="/api/entities", tags=["entities"])


class MentionsRequest(BaseModel):
    text: str = Field(..., max_length=20000)


class MentionsResponse(BaseModel):
    mentions: list[dict]


@router.post("/mentions", response_model=MentionsResponse)
def post_mentions(body: MentionsRequest):
    return MentionsResponse(mentions=find_mentions(body.text))


@router.get("/tooltip")
def get_entity_tooltip(
    name: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
):
    tip = get_tooltip(db, name)
    if not tip:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return tip
