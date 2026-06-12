"""Tests for English unique name validation."""

from app.services.name_validation import (
    is_concatenated_name,
    resolve_unique_name,
    _longest_canon_prefix,
)


def test_concatenated_mjolner_glue():
    assert is_concatenated_name("MjölnerTorment Club") is True


def test_normal_silent_thunder():
    assert is_concatenated_name("Silent Thunder") is False


def test_longest_canon_prefix():
    canon = frozenset({"Sadist's Mercy", "Mjölner"})
    assert _longest_canon_prefix("Sadist's MercyFlanged Mace", canon) == "Sadist's Mercy"


def test_resolve_uses_path_when_index_dirty(monkeypatch):
    from app.services import name_validation as nv

    monkeypatch.setattr(
        nv,
        "known_unique_names",
        lambda: frozenset({"Sadist's Mercy"}),
    )
    assert resolve_unique_name(
        "Sadist's MercyFlanged Mace",
        "Sadists_Mercy",
        None,
    ) == "Sadist's Mercy"
