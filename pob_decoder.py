"""PoB Code Decoder — Phase 1: PoB in, structured JSON out."""

import base64
import zlib
import xml.etree.ElementTree as ET
import json
import sys
from typing import Any


def decode_pob_code(code: str) -> str:
    """Decode a PoB share code into XML string.

    Steps:
    1. Restore URL-safe base64 chars (- → +, _ → /)
    2. Add padding if needed
    3. Base64 decode
    4. Zlib decompress (zlib wrapper first, raw deflate fallback)
    """
    # Restore URL-safe base64
    code = code.replace("-", "+").replace("_", "/")

    # Add padding
    code += "=" * (-len(code) % 4)

    # Base64 decode
    raw = base64.b64decode(code)

    # Try zlib wrapper first, then raw deflate
    try:
        xml_str = zlib.decompress(raw)
    except zlib.error:
        xml_str = zlib.decompress(raw, -zlib.MAX_WBITS)

    return xml_str.decode("utf-8")


def parse_build_data(xml_str: str) -> dict[str, Any]:
    """Parse PoB XML into structured BuildData."""
    root = ET.fromstring(xml_str)

    build_data: dict[str, Any] = {}

    # --- Build info ---
    build = root.find("Build")
    if build is not None:
        build_data["build"] = {
            "level": build.get("level"),
            "className": build.get("className"),
            "ascendClassName": build.get("ascendClassName"),
            "targetVersion": build.get("targetVersion"),
        }

    # --- Skills (gem setups) ---
    # PoB has two formats: SkillSet > Skill > Gem, or top-level Skill > Gem
    skills_node = root.find("Skills")
    skill_sets: list[dict] = []
    if skills_node is not None:
        # Format 1: SkillSet > Skill > Gem
        for skill_spec in skills_node.findall("SkillSet"):
            skill_set: dict[str, Any] = {
                "id": skill_spec.get("id"),
                "gems": [],
            }
            for skill in skill_spec.findall("Skill"):
                slot = skill.get("slot", "unknown")
                for gem in skill.findall("Gem"):
                    gem_data = {
                        "nameSpec": gem.get("nameSpec"),
                        "skillId": gem.get("skillId"),
                        "level": gem.get("level"),
                        "quality": gem.get("quality"),
                        "enabled": gem.get("enabled", "true") == "true",
                        "slot": slot,
                    }
                    skill_set["gems"].append(gem_data)
            skill_sets.append(skill_set)

        # Format 2: top-level Skills > Skill > Gem
        for skill in skills_node.findall("Skill"):
            skill_set = {
                "id": skill.get("slot", "unknown"),
                "gems": [],
            }
            for gem in skill.findall("Gem"):
                gem_data = {
                    "nameSpec": gem.get("nameSpec"),
                    "skillId": gem.get("skillId"),
                    "level": gem.get("level"),
                    "quality": gem.get("quality"),
                    "enabled": gem.get("enabled", "true") == "true",
                }
                skill_set["gems"].append(gem_data)
            if skill_set["gems"]:
                skill_sets.append(skill_set)

    build_data["skillSets"] = skill_sets

    # --- Tree (passive talents) ---
    # PoB stores nodes in a `nodes` ATTRIBUTE (comma-separated), not a child element
    tree_node = root.find("Tree")
    tree_specs: list[dict] = []
    if tree_node is not None:
        for spec in tree_node.findall("Spec"):
            nodes_text = spec.get("nodes", "")
            tree_spec = {
                "title": spec.get("title", ""),
                "classId": spec.get("classId"),
                "ascendClassId": spec.get("ascendClassId"),
                "nodes": [int(n) for n in nodes_text.split(",") if n.strip()],
            }
            tree_specs.append(tree_spec)
    build_data["treeSpecs"] = tree_specs

    # --- Items ---
    # PoB has two formats:
    #   1. Items > Item (inline item text)
    #   2. Items > ItemSet > Slot (references to Item by id)
    items_node = root.find("Items")
    items: list[dict] = []
    item_map: dict[str, dict] = {}  # id -> parsed item

    if items_node is not None:
        # First pass: collect all Item elements
        for item in items_node.findall("Item"):
            item_text = item.text or ""
            lines = item_text.strip().split("\n")
            item_data = {
                "id": item.get("id"),
                "raw": item_text.strip(),
                "rarity": lines[0].replace("Rarity: ", "").strip() if lines else "",
                "name": lines[1].strip() if len(lines) > 1 else "",
                "baseName": lines[2].strip() if len(lines) > 2 else "",
            }
            items.append(item_data)
            item_map[item.get("id")] = item_data

        # Second pass: collect slots from ItemSet
        for item_set in items_node.findall("ItemSet"):
            for slot in item_set.findall("Slot"):
                slot_name = slot.get("name")
                item_id = slot.get("itemId")
                if item_id and item_id != "0" and item_id in item_map:
                    item_map[item_id]["slot"] = slot_name

    build_data["items"] = items

    # --- Player stats (from Build > PlayerStat) ---
    # These are pre-computed by PoB — NEVER recalculate
    build_elem = root.find("Build")
    player_stats: dict[str, Any] = {}
    if build_elem is not None:
        for ps in build_elem.findall("PlayerStat"):
            stat = ps.get("stat")
            value = ps.get("value")
            if stat and value:
                # Try to convert to number
                try:
                    value = float(value) if "." in value else int(value)
                except (ValueError, TypeError):
                    pass
                player_stats[stat] = value
    build_data["playerStats"] = player_stats

    # --- Config (placeholder values) ---
    config_node = root.find("Config")
    config: dict[str, Any] = {}
    if config_node is not None:
        for cs in config_node.findall("ConfigSet"):
            for ph in cs.findall("Placeholder"):
                config[ph.get("name")] = ph.get("number")
    if config:
        build_data["config"] = config

    return build_data


def main():
    if len(sys.argv) > 1:
        code = sys.argv[1].strip()
    else:
        # Use the provided test code
        code = "eNqtW9t34jYTf27_Cg7PJPH90pO0hwBJaHOhQJLdfekRtgB_ETZryyT0r_9Gkm1srnLSfWBteX4zo5FmNCMpl398LEhjheMkiMKrpnquNBs49CI_CGdXzefxzZnT_OP3Xy8HiM6fptdpQNgX7fdff7nkLw2PoCR5RAt81RyicIbjZgMlHg79zubDYxTiZsOboxh5FMf3eIVJO6XRQ-TDVxqn8HUV4Hfx3n8YPA3HzcYCBeEo8t4wvY2jdAnKNRsUxTNMX3J1lX-gjTB2V03LaIJWv1wOCFrjeEQRbawQSYGhcu5oqqaYzUYCrVfNNnQXzXAXLeC3eVEPdZ3GCT0BVc9tR8txoyXG_kHSgv0gxr3pFHs0WOFOHNDOHIXeYRH6uVtAJci1Mu1DSmiwJAGM1SF6280Bdyd5q-eGpeuOras5ZhxRRLqD0WHbVikjWoP5a0Dn1wRsekzAflh_FgYU18cNoiCJwlodkiLupISAN0nRDnGC4xWiwXFFdjvQiRaTIDxurkLKAwpRJ0qoHOUAx-DptBZghL0IgkNdGTWR98EUy1PW6kcGqKvN5_rRG8nS1Wb8OYWGEPfkKEdRSo5Saq5R0NLDoUi3c6ou_jhMVQSsfiihXBevIuZKEg4dB5OUHo5-jmGfq6atmKqiGoZRiQO9u8FhR1VNvYj983USeIg8oI9gkS4g5I7RGz6snG25m6k1m9MQgsgnsDdBjD8B60TEl4WVewnLSJTIAi2lFAWC8A6FftvzUkgg1hKji-K3ECeJbFSF4HgKUe4Ic-fTCzqs-95vjLQfetJsn8M400gaMgTvZanJhBxZohVlv5QsCMiFsCGe4TATt5aD3GPszW9hAIfoiA_pm2yJhXyJ2MJsy0iP2XaLq4xpFWU_4pSZVPvcKiNrWopB5CxV0nC0DCCXk6es1_9tjPRE6YU4nq1H8wATvx51bq8OWh4OQ05lCpThx6bCAXm1BqkMlRusyqIpJ03diFuh5NgCZWxZQpDLGWGFfHwiqd_MTQy5di3EII7-x-oYUg8G3SCkPuKT0rp4ShgsYkMIy6c0QlZAO15EaSwZygSx1ODluYIoQYfYTz25RKaoLq8JFNWy3ShQ3Ni1oG1KkffWjfxZvRGthajqN0qXS4hYzBNOMDgzlXIaBHlAIJPUbmifwI-PRaqSAJYwyQrY0NYQUCSBslK2AKdEKZUUTrorG-JTAtRzxdgZ0QcIlQtYc_gGykN0eDUxSnsoCYZRHyI_SJMHTOFdYkyhCpcqjjmhZGk_iN6hy3O2XXVYBX0fNWTIEqrEOPx3Lc2_Qi4loBf6kGyDLaVlbCM2Yq7T6TRpeNFigug9zIarZrMxgbb8GdL6BGcvAjEOFrDsJEkXUdTws1rtBcUBCqnKNwK3GjXemGAUe3PG6QYRMoHow9hvWjP-lxd865I9PUYUJ0wka81fLjtROA1mDSQ24_jLCFMmgmtXtDQCP2_kpvHwHNwXx40wXUxwzHUK-Q7oothy6wYwv2E4aHuxiFg4yeb1AQZKzsHHiyi8ieLFiEXV5BjILkA4xIt1tlJEhPAN2qPicmBnHkA0PSnJrErajqQHQBXM9uallKDtiCoF2hsl9yO3pG1Hvf0g1zL3yyvvFstBWf_qo5j5T6N0x9rt3WnYnqk8omkYYpa3w3Qm6-PzWNnFd9KYOcJuxXBA8f3WHeS7CDIoZthaAGbTEwBHsaqYcup3yq3ZzlvAAlkniuN0yVLRTrwGzyti7gEO5q492VY1hBaf-20nSmHpxGR6lItqV6dQpeqQngivEGDj9XMiNxd0ZScA1Jh-ozmkoKcj07ZvVNPmY0htVz0GfMWI7xCdFr3FoAth41R4K3qXBLOAPE15PiAxCQqjeBEscTIrQ1W30tlU_QXsFn6g4jq5hrFtmLLjsuO6bJ2_KJZSviyLN_Y4jjF-CfB7498oWtyLAz4oeNnbt6umZZ67FkxdzdJ12zBF-3eeEuvnlmuyzVhD0VlqMo_eWbaSK-3hJD9wFGnBiMZ5VtBfLKOYNvAH-2-AYrq-ak4RScTIcZWylIDVbEU2wF7EKWjf5wdtYeQzKZplO1bL1F1LaWmOYbc0VdetlmHpqtOyFFCyZenQhZZpubrZ0hUFaAzXcq2W7tiK3VJVzXBapqFqdks3VMCqlgHMLNvWWqZiaS40gxng14BvQKKCDM1RWobhAInuqIbeAjvYINsBc7U0wwQaVdFsHVpAhRYwcYyW7toqKKmZBvA1TLeluYYNv4ajmS1gYiigngstpmWZast0VIV9dYGXAx0wDFvXQVHFdVn3TAe6oWlKyzFcvWXBV4CopqWCNMN1WrqmG6C65loG01EHclMDfVXHcbSWAcoBSxhXsINimmAZF7rQMm2mo-nqtgWiDR166do6cDAtx2FK6i3VdKGThmVp0GDawExTVBVaHFAKTAOUYHjLAZaGwrTUFFAbugD9sCwYFc1SwfomGJGR2yDbNDSmE0QTGBtHddmmCz8tQfG6vTnmZiMfBiQ_-gZ3X_dDiuMQEfapciTOGsALKZvhm3Nsk513JwBZi_on4Ykxpy8x0rJc83l4zx9-mVO6TH67uHh_fz9fIjqPpvgjIPgcku2LJYBhsp4lb5DLnTF5F234dz3rt8daECjJ7P5OffxOn-zkdTpb6Atf_eb0Z-Tfh9h5fFzNX-bt8fVS-fBe757-VrXH28dx_y-3TwZnfvpqDL7ZTtR_1UbuLJjczf735K392dl41sN_D_zR2b3bmSR3_Z-Wq6hP6k1y3euPdFt1yNLt_Hn27Xu3RwY_37Ve2FmuOj-N0J8s7vQ5VAXv3zS7M4xodP3j7eyH_f1tgH48vdm6_dLr0u735796t6u_Js_dnz_I-D58GdtqO74-m3zcQteuuHEucutcitsDSRabWBEaB77I9-G9Tak428k_QFHx8SiclxU1cfYs5p9wCTEjhWOIWSHcQ_hz7iQbfxauUvZnMQ1LflN2auFCfF6LWZh5Nfde4UncqSruxLw_83vuNcL7xcwVXiN8SviXiAoiOHGvER5R9hruF8JpRIQSTi2cRsQN4TUirHEfyxyTO40IJyJk8fjXbAQhzS2bjcZFZTguL1gY5YsAi7PsYcSmbQJjMkWw9tzifBkIoQYqjsqaeURmxFmNVoL8nSISsDjOnTOBuA6NyfUaSvhiGSg33rActHpkLpaQdLkUdOP1kvWifX8vvtzjGfLWjEG-WIhFIdMnqxBF1Sl6xJcaCoBji5PoFSPLO5UmWJzTQiKyjELezHrFxWWEmbSDtA0aUIL5ViYzULPsJX0f3IavXTzQQHDPV-0_8TsmDdESgKDBBCg3AzkiEeXtWWAToBsIXW-N-ghtP2KfiixYb-komiQZ8JW1yiBrktZZ2LdWN9uQSWFaA3CHyaIWIFNKqwG5jvx1Iytb5FG3JFpBglpHTETr0A-hGqplXA7Q6gL0GgDw91oCGH2t6REvavFn9HX4s825Ra0eC4RWG1FHq2tMPjPDG6N3tPyEux7CXV5kgZSHax6k-XYgIp5YpfrhMqV7qjYW2P8RzRknQQlJBL9H2bu56XXG_ZdeUU4FifcP2wNlVx4zyEicRzW8iBC0hGI6X1F4WM9WFHYEBStPOkkE9VWTlUn8YxdTFJBEittdUXNXeHE-d9V6_AQnXvsHLAyUGfWglnrP9iKonErsFuCuMkITdmjK9oTlLMWL2gorcRTVgQS7dGB7nAur-6tMWItcV6CSRGTLtFmb9FCzREMYb9colCUhkC8F08CTN_DmJmfVNtVrNcd58IuXVbxokgGLa5RVdNYmZVV-e3PLqqJNan5hD62raNEkAy4O_KsMiuYovCvuYhzn1CO4HRB2rrU1so9RyCc7BIyCQIbhA4SSrGasMnxiu4H5FxlORUGU7HhP3i5lK3Y9qmqmzYWpE31ht38q0NJ9oFNeH-x4bOWKzIlhKW9CV0PZ7oWW46yyk4IKE9EmOQxZHlYZgvJtghM9ybZwq52o3CY54Sg85LZXUeDvRovtj19myK8U_Ad6sUsD_wGb4lqIFC9es2x5S9Z2EC4KvEPoZxqwivVrTJi_fY0Dc7uvceBJoBR6uJOGDI8mHxtkfja9I3iGk0_ji3PsT3MQp-2fhvPNf-nQDzOW7xzsif3Fp6_xYsd8XTDJca_YdOqEVhKxQ56XWChrdVT4v7h9vCe0la8lf4URLON3svniQU7FXZg7jAj7O5SIfI3h_uvXR4fgIC92mTFdotDPuT3VydIPWy-iCTDlVzS67NJk8iUte_wMbsPn8iIv5y75GU9jNI_e2_6Kzcgx2LfYx2v4OKFBiLIFmLDd_eUSh37pVOjyYufv4v4PueqFEw=="

    print(f"[1/3] Decoding PoB code ({len(code)} chars)...")
    xml_str = decode_pob_code(code)
    print(f"[1/3] OK Decoded to {len(xml_str)} bytes of XML")

    print("[2/3] Parsing XML...")
    build_data = parse_build_data(xml_str)
    print(f"[2/3] OK Parsed successfully")

    # Summary
    binfo = build_data.get("build", {})
    print(f"\n{'='*50}")
    print(f"Build Summary")
    print(f"{'='*50}")
    print(f"Class:      {binfo.get('className')} / {binfo.get('ascendClassName')}")
    print(f"Level:      {binfo.get('level')}")
    print(f"Version:    {binfo.get('targetVersion')}")
    print(f"Tree Specs: {len(build_data.get('treeSpecs', []))}")
    for ts in build_data.get("treeSpecs", []):
        print(f"  - {ts.get('title', 'untitled')}: {len(ts.get('nodes', []))} nodes")
    print(f"Skill Sets: {len(build_data.get('skillSets', []))}")
    for ss in build_data.get("skillSets", [])[:5]:
        gems = ss.get("gems", [])
        gem_names = [g.get("nameSpec") or g.get("skillId") for g in gems if g.get("enabled")]
        print(f"  - Set {ss.get('id')}: {', '.join(gem_names[:4])}{'...' if len(gem_names) > 4 else ''}")
    print(f"Items:      {len(build_data.get('items', []))}")
    for item in build_data.get("items", [])[:5]:
        print(f"  - [{item.get('rarity')}] {item.get('name')}")

    # Output full JSON
    output_path = "test_build_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(build_data, f, ensure_ascii=False, indent=2)
    print(f"\n[3/3] OK Full JSON saved to {output_path}")


if __name__ == "__main__":
    main()
