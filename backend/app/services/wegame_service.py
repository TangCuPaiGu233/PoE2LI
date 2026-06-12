"""WeGame PoE2 helper share link fetch and mapping to DecodeResponse."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from app.models.schemas import (
    BuildInfo,
    DecodeResponse,
    ErrorResponse,
    Gem,
    Item,
    SkillSet,
    TreeSpec,
)

WEGAME_BASE = "https://www.wegame.com.cn"
WEGAME_API_PREFIX = "/api/v1/wegame.pallas.poe2.Profile/"
WEGAME_SHARE_PATH_RE = re.compile(
    r"wegame\.com\.cn/helper/poe2(?:/[^#\s]*)?#/share/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
WEGAME_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,}$")

_RARITY_TO_POB = {
    "Unique": "UNIQUE",
    "Rare": "RARE",
    "Magic": "MAGIC",
    "Normal": "NORMAL",
}


def extract_wegame_share_id(text: str) -> str | None:
    """Extract share token from WeGame URL or bare alphanumeric token."""
    raw = (text or "").strip(" `\n\r\t")
    if not raw:
        return None

    m = WEGAME_SHARE_PATH_RE.search(raw)
    if m:
        return m.group(1)

    m2 = re.search(
        r"wegame\.com\.cn/helper/poe2[^\s]*/share/([A-Za-z0-9_-]+)",
        raw,
        re.IGNORECASE,
    )
    if m2:
        return m2.group(1)

    if raw.startswith("eN"):
        return None
    if WEGAME_BARE_TOKEN_RE.match(raw):
        return raw
    return None


def _api_post(path: str, payload: dict[str, Any]) -> dict[str, Any] | ErrorResponse:
    url = WEGAME_BASE + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": "PoE2LI/1.0 (WeGame share reader)",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return ErrorResponse(
                    error=f"WeGame API 请求失败 (HTTP {resp.status})",
                    reason="fetch_failed",
                )
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        return ErrorResponse(
            error=f"WeGame API HTTP 错误: {e.code} {detail}".strip(),
            reason="http_error",
        )
    except urllib.error.URLError as e:
        return ErrorResponse(
            error=f"WeGame 网络错误: {e.reason}",
            reason="network_error",
        )
    except json.JSONDecodeError as e:
        return ErrorResponse(
            error=f"WeGame 响应解析失败: {e}",
            reason="parse_failed",
        )
    except Exception as e:
        return ErrorResponse(
            error=f"WeGame 请求异常: {e}",
            reason="unknown_error",
        )

    result = data.get("result") or {}
    if result.get("error_code", 0) != 0:
        msg = result.get("error_message") or "unknown"
        return ErrorResponse(
            error=f"WeGame API 错误: {msg}",
            reason="api_error",
        )
    return data


def fetch_wegame_build(share_id: str) -> dict[str, Any] | ErrorResponse:
    """Fetch role, gear, skills, tree, and DPS summary for a share token."""
    share_id = share_id.strip()
    role_resp = _api_post(
        WEGAME_API_PREFIX + "GetRoleInfo",
        {"share_code": share_id, "area": 0},
    )
    if isinstance(role_resp, ErrorResponse):
        return role_resp

    role = role_resp.get("role")
    if not role:
        return ErrorResponse(error="WeGame 分享无效或已过期", reason="invalid_share")

    ctx = {
        "share_code": share_id,
        "area": role.get("area", 0),
        "openid": role.get("openid"),
        "role_id": role.get("role_id"),
        "from_src": "share",
    }

    endpoints: list[tuple[str, str]] = [
        ("skills", "GetSkills"),
        ("equipments", "GetEquipments"),
        ("talent_tree", "GetTalentTree"),
        ("skills_dps", "GetSkillsDps"),
    ]
    out: dict[str, Any] = {
        "share_id": share_id,
        "role": role,
    }

    for key, ep in endpoints:
        resp = _api_post(WEGAME_API_PREFIX + ep, dict(ctx))
        if isinstance(resp, ErrorResponse):
            return resp
        if key == "talent_tree":
            out[key] = resp.get("talent_tree") or {}
        elif key == "skills_dps":
            out[key] = resp.get("skills_dps") or []
        else:
            out[key] = resp.get(key) or []

    profile_resp = _api_post(
        WEGAME_API_PREFIX + "GetRoleProfile",
        {"share_code": share_id},
    )
    if isinstance(profile_resp, ErrorResponse):
        return profile_resp
    out["profile"] = profile_resp

    key_resp = _api_post(WEGAME_API_PREFIX + "GetRoleKeyData", dict(ctx))
    if isinstance(key_resp, ErrorResponse):
        out["key_data"] = {}
    else:
        out["key_data"] = key_resp.get("data") or {}

    summary_resp = _api_post(WEGAME_API_PREFIX + "GetRoleSummary", dict(ctx))
    if isinstance(summary_resp, ErrorResponse):
        out["role_summary"] = {}
    else:
        out["role_summary"] = {
            "title": summary_resp.get("summary_title") or "",
            "content": summary_resp.get("summary_content") or "",
            "time_bd": summary_resp.get("time_bd") or "",
        }

    return out



def _item_raw(eq: dict[str, Any]) -> str:
    rarity = _RARITY_TO_POB.get(eq.get("rarity") or "", "RARE")
    lines = [f"Rarity: {rarity}"]
    name = (eq.get("name") or "").strip()
    type_line = (eq.get("typeLine") or eq.get("baseType") or "").strip()
    if name:
        lines.append(name)
    if type_line:
        lines.append(type_line)
    for key in ("implicitMods", "explicitMods", "craftedMods"):
        for mod in eq.get(key) or []:
            if mod:
                lines.append(str(mod))
    return "\n".join(lines)


def _equipped_items(equipments: list[dict[str, Any]]) -> list[Item]:
    items: list[Item] = []
    for eq in equipments:
        inv = eq.get("inventoryId") or ""
        if inv in ("", "Stash", "Stash2", "Stash3") or inv.startswith("Stash"):
            continue
        rarity = _RARITY_TO_POB.get(eq.get("rarity") or "", "RARE")
        name = (eq.get("name") or "").strip()
        base = (eq.get("typeLine") or eq.get("baseType") or "").strip()
        items.append(
            Item(
                id=str(eq.get("id") or ""),
                raw=_item_raw(eq),
                rarity=rarity,
                name=name,
                baseName=base,
                slot=inv,
            )
        )
    return items

def _skill_gems(skills: list[dict[str, Any]]) -> list[Gem]:
    gems: list[Gem] = []
    for sk in skills:
        if sk.get("frameTypeId") != "Gem" and sk.get("support"):
            continue
        name = (sk.get("baseType") or sk.get("name") or "").strip()
        if not name:
            continue
        gems.append(
            Gem(
                nameSpec=name,
                level=int(sk.get("ilvl") or 0),
                enabled=True,
                slot=sk.get("inventoryId") or "unknown",
            )
        )
        for sock in sk.get("socketedItems") or []:
            sname = (sock.get("baseType") or sock.get("name") or "").strip()
            if sname:
                gems.append(
                    Gem(
                        nameSpec=sname,
                        level=int(sock.get("ilvl") or 0),
                        enabled=True,
                        slot=sk.get("inventoryId") or "unknown",
                    )
                )
    return gems


def _int_from_wegame(value: Any) -> int | None:
    if value is None or value == "":
        return None
    digits = re.sub(r"[^\d]", "", str(value).split("/")[0])
    return int(digits) if digits else None


def _stats_from_key_data(key_data: dict[str, Any]) -> dict[str, int | float | str]:
    """Panel survival/output stats from GetRoleKeyData (matches WeGame share page)."""
    stats: dict[str, int | float | str] = {}
    life = _int_from_wegame(key_data.get("life"))
    if life is not None:
        stats["Life"] = life
    mana = _int_from_wegame(key_data.get("mana"))
    if mana is not None:
        stats["Mana"] = mana

    defense = key_data.get("defense_attr") or {}
    es = _int_from_wegame(defense.get("value"))
    if es is not None:
        stats["EnergyShield"] = es

    resist = key_data.get("resist_attr") or {}
    for src, dst in (
        ("fire_resistance", "FireResist"),
        ("cold_resistance", "ColdResist"),
        ("lightning_resistance", "LightningResist"),
        ("chaos_resistance", "ChaosResist"),
    ):
        raw = resist.get(src)
        if raw:
            stats[dst] = str(raw).strip()

    abilities = key_data.get("abilities") or {}
    for src, dst in (
        ("strength", "Strength"),
        ("dexterity", "Dexterity"),
        ("intelligence", "Intelligence"),
    ):
        val = _int_from_wegame(abilities.get(src))
        if val is not None:
            stats[dst] = val

    return stats


def _player_stats(data: dict[str, Any]) -> dict[str, int | float | str]:
    stats: dict[str, int | float | str] = {}
    stats.update(_stats_from_key_data(data.get("key_data") or {}))

    profile = data.get("profile") or {}
    dps_values: list[float] = []
    for sk in profile.get("skills") or []:
        raw_dps = sk.get("total_dps")
        if raw_dps is None or raw_dps == "":
            continue
        try:
            dps_values.append(float(str(raw_dps).replace(",", "")))
        except ValueError:
            pass
    if dps_values:
        stats["TotalDPS"] = int(max(dps_values))

    for row in data.get("skills_dps") or []:
        try:
            val = float(row.get("dps") or 0)
            if val > float(stats.get("TotalDPS") or 0):
                stats["TotalDPS"] = int(val)
        except (TypeError, ValueError):
            pass

    role = data.get("role") or {}
    if role.get("level") is not None:
        stats["Level"] = int(role["level"])
    return stats

def wegame_to_decode_response(data: dict[str, Any]) -> DecodeResponse:
    """Map aggregated WeGame API payload to DecodeResponse."""
    role = data.get("role") or {}
    tree = data.get("talent_tree") or {}
    hashes = tree.get("hashes") or []

    build = BuildInfo(
        level=str(role.get("level") or ""),
        className=role.get("class_name"),
        ascendClassName=None,
        targetVersion=None,
    )

    tree_specs = [
        TreeSpec(
            title="WeGame passive tree",
            nodes=[int(h) for h in hashes if h is not None],
        )
    ]

    gems = _skill_gems(data.get("skills") or [])
    skill_sets = [SkillSet(id="wegame", gems=gems)] if gems else []

    items = _equipped_items(data.get("equipments") or [])
    player_stats = _player_stats(data)

    role_summary = data.get("role_summary") or {}
    config = {
        "source": "wegame",
        "share_id": data.get("share_id") or "",
        "role_name": role.get("name") or "",
        "account_name": role.get("account_name") or "",
        "bd_title": role_summary.get("title") or "",
        "wegame_ai_summary": role_summary.get("content") or "",
    }

    return DecodeResponse(
        build=build,
        treeSpecs=tree_specs,
        skillSets=skill_sets,
        items=items,
        playerStats=player_stats,
        config=config,
    )


def format_wegame_build_summary(data: dict[str, Any]) -> str:
    """Human-readable summary from raw WeGame fetch payload."""
    role = data.get("role") or {}
    lines = [
        "source: WeGame share",
        f"character: {role.get('name') or '?'}",
        f"class: {role.get('class_name') or '?'}",
        f"level: {role.get('level') or '?'}",
        f"account: {role.get('account_name') or '?'}",
    ]

    role_summary = data.get("role_summary") or {}
    if role_summary.get("title"):
        lines.append(f"bd_title: {role_summary['title']}")

    stats = _player_stats(data)
    panel_bits = []
    for label, key in (
        ("Life", "Life"),
        ("Mana", "Mana"),
        ("ES", "EnergyShield"),
        ("FireRes", "FireResist"),
        ("ColdRes", "ColdResist"),
        ("LightningRes", "LightningResist"),
        ("ChaosRes", "ChaosResist"),
        ("DPS", "TotalDPS"),
    ):
        if stats.get(key):
            panel_bits.append(f"{label}={stats[key]}")
    if panel_bits:
        lines.append("panel: " + ", ".join(panel_bits))

    skill_names = []
    for sk in data.get("skills") or []:
        if sk.get("frameTypeId") == "Gem":
            nm = sk.get("baseType") or sk.get("name")
            if nm:
                skill_names.append(str(nm))
    if skill_names:
        lines.append("skills: " + ", ".join(list(dict.fromkeys(skill_names))[:12]))

    uniques = [
        f"{eq.get('name')}({eq.get('typeLine') or eq.get('baseType') or ''})"
        for eq in (data.get("equipments") or [])
        if eq.get("rarity") == "Unique" and eq.get("name")
    ]
    if uniques:
        lines.append("unique_items: " + ", ".join(uniques[:10]))

    return "\n".join(lines)