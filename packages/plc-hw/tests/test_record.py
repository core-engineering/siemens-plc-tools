"""Recording a source, replaying it, and scrubbing it before it is committed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plc_hw.record import (
    PRESERVED_STRUCTURAL_CHANNELS,
    FixtureError,
    RecordingSource,
    ReplaySource,
    anonymise,
    load_fixture,
    save_fixture,
)
from plc_hw.testing import build_fake_source
from plc_hw.walk import walk_project


def _record() -> dict[str, object]:
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    return recorder.fixture()


def test_replaying_a_recording_reproduces_the_snapshot() -> None:
    assert walk_project(ReplaySource(_record())) == walk_project(build_fake_source())


def test_a_fixture_round_trips_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    save_fixture(_record(), path)
    assert walk_project(ReplaySource(load_fixture(path))) == walk_project(build_fake_source())


def test_saved_fixtures_are_stable_across_runs(tmp_path: Path) -> None:
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    save_fixture(_record(), first)
    save_fixture(_record(), second)
    assert first.read_bytes() == second.read_bytes()


def test_load_fixture_reports_a_missing_file_clearly(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(FixtureError, match=r"missing\.json.*does not exist"):
        load_fixture(path)


def test_load_fixture_reports_invalid_json_clearly(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    with pytest.raises(FixtureError, match=r"bad\.json.*not valid JSON"):
        load_fixture(path)


def test_load_fixture_rejects_a_non_mapping_top_level_value(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(FixtureError, match=r"array\.json.*not a mapping"):
        load_fixture(path)


def test_replay_source_reports_a_missing_key_clearly() -> None:
    fixture = _record()
    del fixture["safety_signatures"]
    with pytest.raises(FixtureError, match="missing required key 'safety_signatures'"):
        ReplaySource(fixture)


def test_replay_source_reports_a_mistyped_key_clearly() -> None:
    fixture = _record()
    fixture["subnets"] = "not-a-list"
    with pytest.raises(FixtureError, match="'subnets' must be a list, got str"):
        ReplaySource(fixture)


def test_replay_source_validates_before_any_replay_happens() -> None:
    # "Do not defer to a KeyError at first use; a fixture that is wrong should
    # say so when it is loaded, not halfway through a walk."
    fixture = _record()
    del fixture["devices"]
    with pytest.raises(FixtureError, match="missing required key 'devices'"):
        ReplaySource(fixture)


def test_anonymising_removes_every_original_name() -> None:
    # Deviation from the brief, unrelated to Correction 2: the brief's own loop also
    # checked "F-DI" and "project-A", but both are unsatisfiable by the brief's own
    # design, not just under the corrected allow-list:
    #
    # - "F-DI" is the module's TIA name, and it is also a literal substring of its
    #   TypeName ("F-DI 8x24VDC HF"). TypeName values must survive verbatim -- the
    #   brief's own SCRUBBED_VALUE_ATTRIBUTES never listed TypeName either, and
    #   Correction 2's PRESERVED_VALUE_ATTRIBUTES explicitly keeps it. Removing "F-DI"
    #   from the text would mean scrubbing TypeName, which test_anonymising_preserves_
    #   what_the_walker_is_tested_on (kept verbatim from the brief) requires literally
    #   ("F-DI 8x24VDC HF" must appear). The two assertions cannot both hold; verified
    #   empirically that the brief's own uncorrected reference implementation fails
    #   this same check, so this is pre-existing, not introduced here.
    # - "project-A" is both the neutral project name build_fake_source() happens to use
    #   and the fixed placeholder anonymise() always substitutes, so it is inherently
    #   present in the output regardless of what the original project name was.
    #
    # Replaced with "Rail" (an item name with no such collision) and an explicit check
    # that the project name is normalised to the fixed placeholder.
    fixture, mapping = anonymise(_record())
    text = json.dumps(fixture)
    for original in ("IO_STATION_1", "PLC_MAIN", "Rail"):
        assert original not in text
    assert fixture["project_name"] == "project-A"
    assert mapping["IO_STATION_1"].startswith("device-")


def test_anonymising_preserves_what_the_walker_is_tested_on() -> None:
    fixture, _ = anonymise(_record())
    text = json.dumps(fixture)
    for kept in ("F-DI 8x24VDC HF", "6ES7 136-6BA01-0CA0", "V2.0", "65534", "150"):
        assert kept in text


def test_an_anonymised_fixture_still_replays() -> None:
    fixture, _ = anonymise(_record())
    snapshot = walk_project(ReplaySource(fixture))
    module = snapshot.devices[0].items[0].children[0]
    assert module.order_number == "6ES7 136-6BA01-0CA0"
    assert module.attributes["SomeParameter"] == 150
    # Correction 2: attribute_error reasons are pseudonymised under the
    # allow-list, so the literal reason from the fake source no longer
    # survives anonymisation. What must survive is that the pseudonym is
    # stable and distinct from other reasons -- checked below in
    # test_anonymising_scrubs_attribute_error_reasons.
    assert module.unreadable[0].reason.startswith("reason-")


def test_anonymising_scrubs_identifying_attribute_values() -> None:
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    fixture = recorder.fixture()
    key = "IO_STATION_1/Rail/F-DI"
    fixture["attributes"][key]["Comment"] = "SITE-TAG-0001"
    fixture["attributes"][key]["Label"] = "X1"
    scrubbed, _ = anonymise(fixture)
    text = json.dumps(scrubbed)
    assert "SITE-TAG-0001" not in text
    assert "X1" not in text


def test_the_mapping_is_stable_across_two_anonymisations() -> None:
    fixture = _record()
    assert anonymise(fixture)[1] == anonymise(fixture)[1]


def test_anonymising_scrubs_string_features_but_not_numeric_ones() -> None:
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    fixture = recorder.fixture()
    key = "IO_STATION_1/Rail/F-DI"
    fixture["features"][key]["NetworkInterface"] = {"HostName": "SITE-HOST-01"}
    scrubbed, mapping = anonymise(fixture)
    text = json.dumps(scrubbed)
    assert "SITE-HOST-01" not in text
    # Feature names and numeric feature values are Siemens vocabulary / structural.
    assert "NetworkInterface" in text
    assert "ProfiSafe" in text
    renamed_key = "/".join(mapping.get(part, part) for part in key.split("/"))
    assert scrubbed["features"][renamed_key]["ProfiSafe"]["FDestinationAddress"] == 65534


def test_anonymising_scrubs_attribute_error_reasons() -> None:
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    fixture = recorder.fixture()
    key = "IO_STATION_1/Rail/F-DI"
    fixture["attribute_error"][key]["OtherParameter"] = "different reason entirely"
    scrubbed, mapping = anonymise(fixture)
    text = json.dumps(scrubbed)

    original_reason = "not accessible in this context"
    other_reason = "different reason entirely"
    assert original_reason not in text
    assert other_reason not in text

    renamed_key = "/".join(mapping.get(part, part) for part in key.split("/"))
    first = scrubbed["attribute_error"][renamed_key]["LockedParameter"]
    second = scrubbed["attribute_error"][renamed_key]["OtherParameter"]
    assert first.startswith("reason-")
    assert second.startswith("reason-")
    assert first != second

    # Same reason repeated gets the same pseudonym.
    fixture["attribute_error"][key]["YetAnotherParameter"] = original_reason
    rescrubbed, _ = anonymise(fixture)
    assert rescrubbed["attribute_error"][renamed_key]["LockedParameter"] == (
        rescrubbed["attribute_error"][renamed_key]["YetAnotherParameter"]
    )


def test_anonymising_scrubs_subnet_names_but_not_type_or_number() -> None:
    fixture = _record()
    scrubbed, mapping = anonymise(fixture)
    subnet = scrubbed["subnets"][0]
    assert subnet["name"] != "PN_1"
    assert subnet["name"].startswith("subnet-")
    assert subnet["type"] == "Ethernet"
    assert subnet["number"] == 100
    assert "PN_1" not in json.dumps(scrubbed)
    assert mapping["PN_1"] == subnet["name"]


def test_anonymising_leaves_no_marker_in_any_channel() -> None:
    """The test that would have caught the deny-list-by-omission defect.

    ``tests/test_no_confidential_references.py`` at the repo root is the second
    line of defence for a fixture that actually gets committed: it scans tracked
    files, including ``.json`` (listed in its ``_TEXT_SUFFIXES``), for known
    customer/site terms. This test is the first line -- it catches the shape of
    leak (a channel nobody scrubbed) rather than a specific known name.
    """
    marker = "LEAKCANARY"
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    fixture = recorder.fixture()

    fixture["project_name"] = marker
    device_key = next(iter(fixture["device_items"]))
    fixture["devices"][0]["name"] = marker
    fixture["devices"][0]["key"] = marker
    item_key = "IO_STATION_1/Rail/F-DI"
    fixture["device_items"][device_key][0]["name"] = marker
    fixture["attributes"][item_key]["Comment"] = marker
    fixture["features"][item_key]["NetworkInterface"] = {"HostName": marker}
    fixture["attribute_error"][item_key]["SomeAttr"] = marker
    fixture["subnets"][0]["name"] = marker

    scrubbed, _ = anonymise(fixture)
    text = json.dumps(scrubbed)
    assert marker not in text


def test_anonymising_preserves_the_named_structural_channels() -> None:
    """PRESERVED_STRUCTURAL_CHANNELS is a decision, not a default -- this test makes
    it executable.

    An assertion that something *survives* looks backwards next to every other test
    in this file, until the point lands: if someone later scrubs one of these
    channels, replay breaks (the walker keys its behaviour on attribute and feature
    names) and this test fails, loudly, instead of silently changing what a fixture
    means. If someone adds a fixture channel without deciding whether it is
    structural or customer data, this test and PRESERVED_STRUCTURAL_CHANNELS start
    disagreeing about what "every named channel" covers.
    """
    marker = "STRUCTMARKER"
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    fixture = recorder.fixture()
    item_key = "IO_STATION_1/Rail/F-DI"

    # "attribute names": the marker is the attribute's *name*, not its value.
    fixture["attributes"][item_key][marker] = "some value"
    fixture["attribute_infos"][item_key].append({"name": marker, "read_only": True})

    # "feature names and inner keys": marker as both the feature name and the
    # name of one of its inner values.
    fixture["features"][item_key][marker] = {marker: "some value"}

    # "address io_type"
    fixture["addresses"][item_key].append({"start": 1, "length": 1, "io_type": marker})

    # "subnet type"
    fixture["subnets"][0]["type"] = marker

    # "safety signature keys and values"
    fixture["safety_signatures"][marker] = marker

    scrubbed, mapping = anonymise(fixture)
    renamed_key = "/".join(mapping.get(part, part) for part in item_key.split("/"))

    assert PRESERVED_STRUCTURAL_CHANNELS == (
        "attribute names",
        "feature names and inner keys",
        "address io_type",
        "subnet type",
        "safety signature keys and values",
    )
    assert marker in scrubbed["attributes"][renamed_key]
    assert any(info["name"] == marker for info in scrubbed["attribute_infos"][renamed_key])
    assert marker in scrubbed["features"][renamed_key]
    assert marker in scrubbed["features"][renamed_key][marker]
    assert any(a["io_type"] == marker for a in scrubbed["addresses"][renamed_key])
    assert scrubbed["subnets"][0]["type"] == marker
    assert scrubbed["safety_signatures"][marker] == marker


def test_anonymising_does_not_mutate_the_original_fixture() -> None:
    """anonymise must copy, not alias: mutating its output must never reach back into
    the caller's recording, which is a live handle to what a real dump captured."""
    fixture = _record()
    any_item_key = next(iter(fixture["attribute_infos"]))
    original_signatures = dict(fixture["safety_signatures"])
    original_infos = [dict(info) for info in fixture["attribute_infos"][any_item_key]]
    original_addresses = [dict(a) for a in fixture["addresses"].get(any_item_key, [])]

    scrubbed, _ = anonymise(fixture)
    scrubbed["safety_signatures"]["Injected"] = "value"
    for infos in scrubbed["attribute_infos"].values():
        infos.append({"name": "Injected", "read_only": True})
    for addresses in scrubbed["addresses"].values():
        addresses.append({"start": 0, "length": 0, "io_type": "Injected"})

    assert fixture["safety_signatures"] == original_signatures
    assert fixture["attribute_infos"][any_item_key] == original_infos
    assert fixture["addresses"].get(any_item_key, []) == original_addresses
