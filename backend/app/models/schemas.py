"""Pydantic schemas for API request/response."""

from pydantic import BaseModel, Field


class DecodeRequest(BaseModel):
    """Request body for POST /api/builds/decode."""
    pob_code: str = Field(..., min_length=1, description="PoB share code starting with eN")
    league: str | None = Field(None, description="League name (e.g. 'Standard')")
    game_version: str | None = Field(None, description="Game version (e.g. '0.1')")


class BuildInfo(BaseModel):
    """Basic build metadata from PoB XML."""
    level: str | None = None
    className: str | None = None
    ascendClassName: str | None = None
    targetVersion: str | None = None


class TreeSpec(BaseModel):
    """A passive tree specification."""
    title: str = ""
    classId: str | None = None
    ascendClassId: str | None = None
    nodes: list[int] = []


class Gem(BaseModel):
    """A skill gem or support gem."""
    nameSpec: str | None = None
    skillId: str | None = None
    level: int = 0
    quality: int = 0
    enabled: bool = True
    slot: str = "unknown"


class SkillSet(BaseModel):
    """A collection of gem setups."""
    id: str | None = None
    gems: list[Gem] = []


class Item(BaseModel):
    """An equipped item."""
    id: str | None = None
    raw: str = ""
    rarity: str = ""
    name: str = ""
    baseName: str = ""
    slot: str | None = None


class DecodeResponse(BaseModel):
    """Response body for POST /api/builds/decode."""
    build: BuildInfo = BuildInfo()
    treeSpecs: list[TreeSpec] = []
    skillSets: list[SkillSet] = []
    items: list[Item] = []
    playerStats: dict[str, int | float | str] = {}
    config: dict[str, str] = {}


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
