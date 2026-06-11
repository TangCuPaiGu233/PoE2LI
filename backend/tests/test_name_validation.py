"""Tests for English unique name validation."""

from app.services.name_validation import is_concatenated_name


def test_concatenated_mjolner_glue():
    assert is_concatenated_name("MjölnerTorment Club") is True


def test_normal_silent_thunder():
    assert is_concatenated_name("Silent Thunder") is False
