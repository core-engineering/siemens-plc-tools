"""The plc.yaml ``hw:`` section."""

from __future__ import annotations

from pathlib import Path

from plc_hw.config import HwConfig, load_hw_config
from plc_hw.normalize import DEFAULT_VOLATILE


def test_defaults_when_the_section_is_absent(tmp_path: Path) -> None:
    (tmp_path / "plc.yaml").write_text("project:\n  name: demo\n")
    config, root = load_hw_config(tmp_path)
    assert config == HwConfig()
    assert config.volatile_attributes == DEFAULT_VOLATILE
    assert root == tmp_path


def test_values_are_read_from_the_section(tmp_path: Path) -> None:
    (tmp_path / "plc.yaml").write_text(
        "hw:\n"
        "  paths:\n"
        "    dump: out/hardware\n"
        "  project: some/project.ap21\n"
        "  volatile_attributes:\n"
        "    - InstallationDate\n"
        "    - SomethingElse\n"
        "  anonymize: false\n"
    )
    config, _ = load_hw_config(tmp_path)
    assert config.dump_dir == "out/hardware"
    assert config.project == "some/project.ap21"
    assert config.volatile_attributes == ("InstallationDate", "SomethingElse")
    assert config.anonymize is False


def test_no_plc_yaml_falls_back_to_defaults_and_the_start_path(tmp_path: Path) -> None:
    config, root = load_hw_config(tmp_path)
    assert config == HwConfig()
    assert root == tmp_path


def test_an_explicit_empty_volatile_list_means_drop_nothing(tmp_path: Path) -> None:
    # An empty list is a deliberate choice ("drop nothing"), not the same as
    # the key being absent ("use the default"). `if volatile else DEFAULT`
    # conflated the two; `if volatile is not None else DEFAULT` does not.
    (tmp_path / "plc.yaml").write_text("hw:\n  volatile_attributes: []\n")
    config, _ = load_hw_config(tmp_path)
    assert config.volatile_attributes == ()
