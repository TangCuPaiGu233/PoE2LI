"""Generic parser factory — creates entity-type-aware parsers from base_parser."""
from parser.base_parser import parse_entity_list


def make_parser(entity_type: str):
    """Return a parse function for the given entity type."""
    def parse(html: str) -> dict:
        return parse_entity_list(html, entity_type, poe2_tab_only=True)
    return parse
