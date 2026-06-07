"""Pydantic schemas for API request/response."""

from pydantic import BaseModel, Field


class DecodeRequest(BaseModel):
    """Request body for POST /api/builds/decode — pure decode, no storage."""
    pob_code: str = Field(..., min_length=1, description="PoB share code starting with eN")


class CreateBuildRequest(BaseModel):
    """Request body for POST /api/builds — decode + store + generate homework."""
    pob_code: str = Field(..., min_length=1, description="PoB share code or pobb.in URL")
    league: str | None = Field(None, description="League name (e.g. 'Standard')")
    game_version: str | None = Field(None, description="Game version (e.g. '0.1')")


class AdminImportRequest(BaseModel):
    """Request body for batch importing builds by admin."""
    codes: list[str] = Field(..., description="List of PoB share codes or pobb.in URLs")
    league: str | None = Field(None, description="League name")
    game_version: str | None = Field(None, description="Game version")


class ChatRequest(BaseModel):
    """Request body for Q&A (RAG) against a specific build."""
    build_id: int = Field(..., description="ID of the build to ask questions about")
    question: str = Field(..., min_length=2, description="User's question")


class ChatResponse(BaseModel):
    """Response body for Q&A."""
    answer: str
    context_used: list[str] = []


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


class BuildSummary(BaseModel):
    """Response for GET /api/builds (list) and POST /api/builds (create)."""
    id: int
    status: str
    league: str | None = None
    game_version: str | None = None
    build: BuildInfo = BuildInfo()


class BuildDetail(BuildSummary):
    """Response for GET /api/builds/{id} — includes full data + homework."""
    treeSpecs: list[TreeSpec] = []
    skillSets: list[SkillSet] = []
    items: list[Item] = []
    playerStats: dict[str, int | float | str] = {}
    homework: dict | None = None
    created_at: str | None = None


class ErrorResponse(BaseModel):
    """Structured error response with machine-readable reason."""
    error: str
    reason: str | None = None
