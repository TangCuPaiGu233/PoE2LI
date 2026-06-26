"""Placeholder golden audit script.

This script is intentionally minimal. Real golden-data baselines should be
generated from verified PoE2 builds and stored under backend/tests_golden/.
"""

import json
from app.services.pob_service import decode_pob
from app.models.schemas import DecodeResponse


def audit_sample(code: str) -> dict:
    result = decode_pob(code)
    if isinstance(result, DecodeResponse):
        return {
            "ok": True,
            "build": result.build.model_dump(),
            "playerStats": result.playerStats,
        }
    return {"ok": False, "error": result.error, "reason": result.reason}


if __name__ == "__main__":
    sample = "not-a-pob-code"
    print(json.dumps(audit_sample(sample), ensure_ascii=False))
