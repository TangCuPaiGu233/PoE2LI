"""Skill/Skill_Gems parser — uses generic entity list parser."""
from parser.base_parser import parse_entity_list

def parse_skill_index(html: str) -> dict:
    return parse_entity_list(html, "skill", poe2_tab_only=True)
