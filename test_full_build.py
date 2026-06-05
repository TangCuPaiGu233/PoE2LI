"""Generate a test PoB XML with full data (items, skills, tree) and encode it."""

import base64
import zlib
import json
from pob_decoder import decode_pob_code, parse_build_data

# A minimal but complete PoB XML structure
TEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
	<Build className="Marauder" ascendClassName="Juggernaut" level="90" targetVersion="0_1">
		<PlayerStat value="50000" stat="TotalDPS"/>
		<PlayerStat value="4500" stat="Life"/>
		<PlayerStat value="1200" stat="Mana"/>
		<PlayerStat value="300" stat="Str"/>
		<PlayerStat value="150" stat="Dex"/>
		<PlayerStat value="100" stat="Int"/>
		<PlayerStat value="25000" stat="TotalEHP"/>
		<PlayerStat value="85" stat="FireResist"/>
		<PlayerStat value="85" stat="ColdResist"/>
		<PlayerStat value="85" stat="LightningResist"/>
		<PlayerStat value="75" stat="ChaosResist"/>
	</Build>
	<Tree activeSpec="1">
		<Spec classId="1" ascendClassId="1" title="Endgame" nodes="26786,53960,2847,21336,46318,60505,63526,56935,30047,49696,38707,11248,54127"/>
	</Tree>
	<Skills activeSkillSet="1" defaultGemLevel="normalMaximum" defaultGemQuality="20">
		<SkillSet id="1">
			<Skill slot="Body Armour">
				<Gem nameSpec="Cyclone" skillId="Cyclone" level="20" quality="20" enabled="true"/>
				<Gem nameSpec="Melee Physical Damage" skillId="MeleePhysicalDamageSupport" level="20" quality="20" enabled="true"/>
				<Gem nameSpec="Brutality" skillId="BrutalitySupport" level="20" quality="20" enabled="true"/>
				<Gem nameSpec="Infused Channelling" skillId="InfusedChannellingSupport" level="20" quality="20" enabled="true"/>
				<Gem nameSpec="Impale" skillId="ImpaleSupport" level="20" quality="20" enabled="true"/>
				<Gem nameSpec="Fortify" skillId="FortifySupport" level="20" quality="20" enabled="true"/>
			</Skill>
			<Skill slot="Weapon 1">
				<Gem nameSpec="Ancestral Warchief" skillId="AncestralWarchief" level="20" quality="20" enabled="true"/>
				<Gem nameSpec="Multiple Totems" skillId="MultipleTotemsSupport" level="20" quality="20" enabled="true"/>
			</Skill>
		</SkillSet>
	</Skills>
	<Items activeItemSet="1">
		<Item id="1">Rarity: RARE
Eagle Grip
Vaal Gauntlets
Armour: 320
Requires Level 63, 100 Str
+80 to maximum Life
+45% to Fire Resistance
+35% to Cold Resistance
+20% increased Attack Speed
</Item>
		<Item id="2">Rarity: UNIQUE
Kaom's Heart
Glorious Plate
Armour: 550
Requires Level 68, 191 Str
+500 to maximum Life
Has no Sockets
30% of Fire Damage is taken as Physical Damage
</Item>
		<Item id="3">Rarity: RARE
Onslaught Strike
Vaal Axe
Physical Damage: 320-480
Critical Strike Chance: 5.00%
Attacks per Second: 1.35
Requires Level 64, 158 Str, 76 Dex
+25% to Global Critical Strike Multiplier
Adds 45 to 80 Physical Damage
+30% to Fire Resistance
</Item>
		<ItemSet id="1" title="Default">
			<Slot itemId="1" name="Gloves"/>
			<Slot itemId="2" name="Body Armour"/>
			<Slot itemId="3" name="Weapon 1"/>
		</ItemSet>
	</Items>
</PathOfBuilding2>"""

def main():
    print("=== Testing PoB Decoder with Full Data ===\n")

    # Encode the test XML into a PoB share code
    xml_bytes = TEST_XML.encode("utf-8")
    compressed = zlib.compress(xml_bytes)
    code = base64.b64encode(compressed).decode("utf-8")
    # Make URL-safe
    code = code.replace("+", "-").replace("/", "_").rstrip("=")

    print(f"[1] Generated test share code ({len(code)} chars)")
    print(f"    Starts with: {code[:20]}...")

    # Decode and parse
    print(f"\n[2] Decoding...")
    xml_str = decode_pob_code(code)
    print(f"    OK: {len(xml_str)} bytes")

    print(f"\n[3] Parsing...")
    build_data = parse_build_data(xml_str)

    # Print results
    binfo = build_data.get("build", {})
    print(f"\n{'='*50}")
    print(f"Build Summary")
    print(f"{'='*50}")
    print(f"Class:   {binfo.get('className')} / {binfo.get('ascendClassName')}")
    print(f"Level:   {binfo.get('level')}")

    # Tree
    tree = build_data.get("treeSpecs", [])
    print(f"\nTree Specs: {len(tree)}")
    for ts in tree:
        print(f"  - {ts.get('title', 'untitled')}: {len(ts.get('nodes', []))} nodes")

    # Skills
    skills = build_data.get("skillSets", [])
    print(f"\nSkill Sets: {len(skills)}")
    for ss in skills:
        gems = ss.get("gems", [])
        # Group by slot for display
        slots: dict[str, list] = {}
        for g in gems:
            slot = g.get("slot", "unknown")
            slots.setdefault(slot, []).append(g)
        print(f"  Set {ss.get('id')}: {len(gems)} gems across {len(slots)} slots")
        for slot, slot_gems in slots.items():
            print(f"    [{slot}]:")
            for g in slot_gems:
                name = g.get("nameSpec") or g.get("skillId")
                print(f"      - {name} (Lv{g.get('level')}, Q{g.get('quality')})")

    # Items
    items = build_data.get("items", [])
    print(f"\nItems: {len(items)}")
    for item in items:
        slot = item.get("slot", "unequipped")
        print(f"  - [{item.get('rarity')}] {item.get('name')} ({slot})")

    # Player Stats
    ps = build_data.get("playerStats", {})
    print(f"\nKey Stats:")
    for k in ["TotalDPS", "Life", "Mana", "Str", "Dex", "Int", "TotalEHP"]:
        if k in ps:
            print(f"  {k}: {ps[k]}")

    # Save
    with open("test_full_build_data.json", "w", encoding="utf-8") as f:
        json.dump(build_data, f, ensure_ascii=False, indent=2)
    print(f"\n[4] Full JSON saved to test_full_build_data.json")

    # Verify
    assert len(tree) == 1
    assert len(tree[0]["nodes"]) == 13
    assert len(skills) == 1
    assert len(skills[0]["gems"]) == 8  # 6 from Body Armour + 2 from Weapon 1
    assert len(items) == 3
    assert items[0]["slot"] == "Gloves"
    assert items[1]["slot"] == "Body Armour"
    assert items[2]["slot"] == "Weapon 1"
    assert ps["TotalDPS"] == 50000
    assert ps["Life"] == 4500
    print("\n[5] ALL ASSERTIONS PASSED!")

if __name__ == "__main__":
    main()
