"""Entity mention + tooltip API."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.entity_catalog_service import (
    catalog_stats,
    get_entity_profile,
    icon_local_path,
    profile_to_tooltip,
)
from app.services.entity_icon_service import (
    proxy_icon_bytes,
    resolve_icon_url,
    resolve_local_icon,
)
from app.services.entity_tooltip import find_mentions, get_tooltip, _resolve_entity

router = APIRouter(prefix="/api/entities", tags=["entities"])


class MentionsRequest(BaseModel):
    text: str = Field(..., max_length=20000)


class MentionsResponse(BaseModel):
    mentions: list[dict]


@router.post("/mentions", response_model=MentionsResponse)
def post_mentions(body: MentionsRequest):
    return MentionsResponse(mentions=find_mentions(body.text))


@router.get("/icon")
def get_entity_icon(name: str = Query(..., min_length=1, max_length=200)):
    resolved = _resolve_entity(name)
    if not resolved:
        raise HTTPException(status_code=404, detail="entity_not_found")
    label, name_en, etype = resolved
    url = resolve_icon_url(name_en, etype, name_cn=label, allow_fetch=False)
    return {"name_en": name_en, "type": etype, "icon_url": url}


def _media_type(path: Path) -> str:
    if path.suffix.lower() == ".webp":
        return "image/webp"
    return "image/png"


@router.get("/icon-image")
def get_entity_icon_image(name: str = Query(..., min_length=1, max_length=200)):
    """Serve entity icon via backend (catalog → local cache → poecdn proxy)."""
    profile = get_entity_profile(name)
    if profile:
        local = icon_local_path(profile)
        if local:
            return FileResponse(
                local,
                media_type=_media_type(local),
                headers={"Cache-Control": "public, max-age=604800"},
            )
        if profile.icon_url:
            body, media = proxy_icon_bytes(profile.icon_url)
            if body:
                return Response(
                    content=body,
                    media_type=media or "image/png",
                    headers={"Cache-Control": "public, max-age=604800"},
                )

    resolved = _resolve_entity(name)
    if not resolved:
        raise HTTPException(status_code=404, detail="entity_not_found")
    label, name_en, etype = resolved
    local = resolve_local_icon(name_en, etype, name_cn=label)
    if local:
        return FileResponse(
            local,
            media_type=_media_type(local),
            headers={"Cache-Control": "public, max-age=604800"},
        )
    url = resolve_icon_url(name_en, etype, name_cn=label, allow_fetch=False)
    if not url:
        url = resolve_icon_url(name_en, etype, name_cn=label, allow_fetch=True)
    if url:
        body, media = proxy_icon_bytes(url)
        if body:
            return Response(
                content=body,
                media_type=media or "image/png",
                headers={"Cache-Control": "public, max-age=604800"},
            )
    raise HTTPException(status_code=404, detail="no_icon")


@router.get("/tooltip")
def get_entity_tooltip(
    name: str = Query(..., min_length=1, max_length=200),
    lang: str = Query("cn", pattern="^(cn|en)$"),
    db: Session = Depends(get_db),
):
    profile = get_entity_profile(name)
    if profile:
        return profile_to_tooltip(profile, lang=lang)
    tip = get_tooltip(db, name, lang=lang)
    if not tip:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return tip


@router.get("/catalog-status")
def get_catalog_status():
    return catalog_stats()
