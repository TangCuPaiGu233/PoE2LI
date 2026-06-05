"""PoB decoding service — wraps pob_decoder.py for the API layer."""

import sys
from pathlib import Path

# Add project root to path so we can import pob_decoder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from pob_decoder import decode_pob_code, parse_build_data, PoBDecodeError
from app.models.schemas import (
    BuildInfo, TreeSpec, Gem, SkillSet, Item,
    DecodeResponse, ErrorResponse,
)


def decode_pob(pob_code: str) -> DecodeResponse | ErrorResponse:
    """Decode a PoB share code into a structured DecodeResponse.

    Returns ErrorResponse if decoding or parsing fails.
    """
    try:
        xml_str = decode_pob_code(pob_code)
    except PoBDecodeError as e:
        return ErrorResponse(error=f"PoB 解码失败 ({e.reason}): {e.detail}")
    except Exception as e:
        return ErrorResponse(error=f"PoB 解码异常: {e}")

    try:
        raw_data = parse_build_data(xml_str)
    except PoBDecodeError as e:
        return ErrorResponse(error=f"PoB 解析失败 ({e.reason}): {e.detail}")
    except Exception as e:
        return ErrorResponse(error=f"PoB 解析异常: {e}")

    # Convert raw dicts to Pydantic models
    build_info = BuildInfo(**raw_data.get("build", {}))

    tree_specs = [TreeSpec(**ts) for ts in raw_data.get("treeSpecs", [])]

    skill_sets = []
    for ss in raw_data.get("skillSets", []):
        gems = [Gem(**g) for g in ss.get("gems", [])]
        skill_sets.append(SkillSet(id=ss.get("id"), gems=gems))

    items = [Item(**i) for i in raw_data.get("items", [])]

    player_stats = raw_data.get("playerStats", {})
    config = raw_data.get("config", {})

    return DecodeResponse(
        build=build_info,
        treeSpecs=tree_specs,
        skillSets=skill_sets,
        items=items,
        playerStats=player_stats,
        config=config,
    )
