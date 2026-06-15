"""Tests for CN entity resolution."""

from app.services.entity_resolver import resolve_all_entities


def test_twisted_necklace_resolves_to_distorted_amulet():
  ents = resolve_all_entities("\u626d\u66f2\u9879\u94fe\u90fd\u80fd\u63d0\u4f9b\u4ec0\u4e48\u8bcd\u6761")
  names = [e[0] for e in ents]
  assert "Distorted Amulet" in names
  assert "Twisted Amulet" not in names
  assert "Twisted Empyrean" not in names


def test_jibian_necklace_resolves_to_twisted_amulet():
  ents = resolve_all_entities("\u7578\u53d8\u9879\u94fe\u6d82\u6cb9")
  names = [e[0] for e in ents]
  assert "Twisted Amulet" in names
