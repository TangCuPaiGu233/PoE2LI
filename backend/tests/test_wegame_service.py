"""Tests for WeGame share parsing."""

from app.services.wegame_service import (
    extract_wegame_share_id,
    format_wegame_build_summary,
    wegame_to_decode_response,
)

SHARE = "xEirsfy4dp9CjlH7ypenSETLRK6nTQFnOPnlMpc0KipcY1Ie6W7mQADv1ed33hU8"
URL = f"https://www.wegame.com.cn/helper/poe2/#/share/{SHARE}"


def test_extract_wegame_share_id_from_url():
    assert extract_wegame_share_id(URL) == SHARE


def test_extract_wegame_share_id_bare_token():
    assert extract_wegame_share_id(SHARE) == SHARE


def test_extract_wegame_share_id_rejects_pob():
    assert extract_wegame_share_id("eN" + "a" * 40) is None


def test_format_wegame_build_summary_mock():
    data = {
        "share_id": SHARE,
        "role": {
            "name": "TestChar",
            "class_name": "Spirit Walker",
            "level": 88,
            "account_name": "Foo#1234",
        },
        "skills": [
            {"frameTypeId": "Gem", "baseType": "Skill A"},
            {"frameTypeId": "Gem", "baseType": "Skill B"},
        ],
        "equipments": [
            {
                "rarity": "Unique",
                "name": "Unique Flask",
                "typeLine": "Flask",
                "inventoryId": "Flask",
            }
        ],
        "profile": {"skills": [{"total_dps": "12345"}]},
        "skills_dps": [],
        "talent_tree": {"hashes": [1, 2, 3]},
    }
    summary = format_wegame_build_summary(data)
    assert "Spirit Walker" in summary
    assert "Skill A" in summary
    assert "Unique Flask" in summary
    assert "12345" in summary

    decoded = wegame_to_decode_response(data)
    assert decoded.config.get("source") == "wegame"
    assert decoded.build.className == "Spirit Walker"
    assert len(decoded.skillSets[0].gems) == 2