"""PoB decoding service — wraps pob_decoder.py for the API layer.

Includes in-memory cache to avoid duplicate decoding for the same pob_code.
"""

import sys
import hashlib
from pathlib import Path

# Add project root to path so we can import pob_decoder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from pob_decoder import decode_pob_code, parse_build_data, PoBDecodeError
from app.models.schemas import (
    BuildInfo, TreeSpec, Gem, SkillSet, Item,
    DecodeResponse, ErrorResponse,
)

# Simple in-memory cache: pob_code_hash -> DecodeResponse
_decode_cache: dict[str, DecodeResponse] = {}
MAX_CACHE_SIZE = 256


def _cache_key(pob_code: str) -> str:
    """Generate a cache key from pob_code."""
    return hashlib.sha256(pob_code.encode()).hexdigest()[:16]


def decode_pob(pob_code: str) -> DecodeResponse | ErrorResponse:
    """Decode a PoB share code into a structured DecodeResponse.

    Results are cached by pob_code hash to avoid duplicate decoding.
    Returns ErrorResponse if decoding or parsing fails.
    """
    # Check cache
    key = _cache_key(pob_code)
    if key in _decode_cache:
        return _decode_cache[key]

    # Decode
    try:
        xml_str = decode_pob_code(pob_code)
    except PoBDecodeError as e:
        return ErrorResponse(error=f"PoB 解码失败: {e.detail}", reason=e.reason)
    except Exception as e:
        return ErrorResponse(error=f"PoB 解码异常: {e}", reason="unknown")

    # Parse
    try:
        raw_data = parse_build_data(xml_str)
    except PoBDecodeError as e:
        return ErrorResponse(error=f"PoB 解析失败: {e.detail}", reason=e.reason)
    except Exception as e:
        return ErrorResponse(error=f"PoB 解析异常: {e}", reason="unknown")

    # Convert to response model
    build_info = BuildInfo(**raw_data.get("build", {}))
    tree_specs = [TreeSpec(**ts) for ts in raw_data.get("treeSpecs", [])]

    skill_sets = []
    for ss in raw_data.get("skillSets", []):
        gems = [Gem(**g) for g in ss.get("gems", [])]
        skill_sets.append(SkillSet(id=ss.get("id"), gems=gems))

    items = [Item(**i) for i in raw_data.get("items", [])]
    player_stats = raw_data.get("playerStats", {})
    config = raw_data.get("config", {})

    result = DecodeResponse(
        build=build_info,
        treeSpecs=tree_specs,
        skillSets=skill_sets,
        items=items,
        playerStats=player_stats,
        config=config,
    )

    # Cache result (evict oldest if full)
    if len(_decode_cache) >= MAX_CACHE_SIZE:
        oldest_key = next(iter(_decode_cache))
        del _decode_cache[oldest_key]
    _decode_cache[key] = result

    return result
