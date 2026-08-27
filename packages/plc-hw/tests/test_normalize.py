"""Normalisation: value formatting and filesystem-safe slugs."""

from __future__ import annotations

import enum

from plc_hw.normalize import (
    DEFAULT_VOLATILE,
    disambiguate,
    format_value,
    slugify,
    strip_order_number_prefix,
)


def test_default_volatile_list_is_explicit_and_minimal() -> None:
    assert DEFAULT_VOLATILE == ("InstallationDate",)


def test_volatile_filtering_never_catches_monitoring_time() -> None:
    # A suffix heuristic on "Time" would drop the very parameter this tool exists
    # for. The list is explicit; assert the trap stays shut.
    assert "F_Monitoring_Time" not in DEFAULT_VOLATILE
    assert not any(name.endswith("Time") for name in DEFAULT_VOLATILE)


def test_format_value_renders_enums_by_name() -> None:
    class Mode(enum.Enum):
        FAST = 1

    assert format_value(Mode.FAST) == "FAST"


def test_format_value_keeps_scalars_and_stringifies_the_rest() -> None:
    assert format_value(True) is True
    assert format_value(150) == 150
    assert format_value("V2.0") == "V2.0"
    assert format_value(None) is None
    assert format_value(object()).startswith("<")


def test_format_value_makes_floats_stable() -> None:
    assert format_value(0.1 + 0.2) == 0.30000000000000004


def test_strip_order_number_prefix() -> None:
    assert strip_order_number_prefix("OrderNumber:6ES7 136-6BA01-0CA0") == "6ES7 136-6BA01-0CA0"
    assert strip_order_number_prefix("System:Device.ET200SP") == "System:Device.ET200SP"


def test_slugify_replaces_every_character_windows_forbids() -> None:
    assert slugify('a/b\\c:d*e?f"g<h>i|j') == "a-b-c-d-e-f-g-h-i-j"


def test_slugify_collapses_runs_and_trims() -> None:
    assert slugify("ET200SPMod.el.F-DQ4x24VDC/2A_2_1") == "ET200SPMod-el-F-DQ4x24VDC-2A_2_1"
    assert slugify("  spaced  name  ") == "spaced-name"


def test_slugify_never_returns_empty() -> None:
    assert slugify("///") == "item"


def test_disambiguate_resolves_case_insensitive_collisions() -> None:
    # NTFS is case-insensitive: without this, the second file overwrites the first.
    assert disambiguate(["Motor", "motor", "Pump"]) == ["Motor", "motor-2", "Pump"]


def test_disambiguate_is_deterministic_on_order() -> None:
    assert disambiguate(["a", "A", "a"]) == ["a", "A-2", "a-3"]


def test_disambiguate_generated_suffix_does_not_collide_with_an_existing_slug() -> None:
    # A generated `<stem>-<N>` suffix must not collide with a slug that already
    # exists elsewhere in the list -- if it does, two entries end up with the
    # same output name and one silently overwrites the other on NTFS.
    assert disambiguate(["Y-3", "Y", "Y"]) == ["Y-3", "Y", "Y-4"]


def test_disambiguate_outputs_are_always_unique_and_same_length_as_input() -> None:
    cases = [
        ["Y-3", "Y", "Y"],
        ["a", "A", "a", "A"],
        ["x", "x", "x", "x-2"],
    ]
    for slugs in cases:
        result = disambiguate(slugs)
        assert len(result) == len(slugs)
        lowered = [slug.lower() for slug in result]
        assert len(set(lowered)) == len(lowered)
