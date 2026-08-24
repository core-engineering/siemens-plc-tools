"""The tag-table cross-reference: which declared I/O the code actually uses."""

from __future__ import annotations

from plc_code.analyzer.logic_dependency.tag_parser import IOTag, TagCollection
from plc_code.analyzer.tag_xref import cross_reference
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

_SOURCE = """FUNCTION_BLOCK "IoMap"
    VAR_INPUT
        speed : Real;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF "DI_START" THEN
                "DO_PUMP" := TRUE;
            END_IF;
            "DO_VALVE" := "AI_LEVEL" > 2.0;
            "DI_MYSTERY" := FALSE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _tag(name: str, direction: str) -> IOTag:
    return IOTag(name=name, address="%I0.0", data_type="Bool", comment="", category="", direction=direction)


def _report():
    block = SCLParser(tokenize_with_newlines(_SOURCE)).parse()
    tags = TagCollection(
        tags=[
            _tag("DI_START", "input"),
            _tag("AI_LEVEL", "input"),
            _tag("DO_PUMP", "output"),
            _tag("DO_VALVE", "output"),
            _tag("DI_SPARE", "input"),  # wired, never touched
            _tag("DO_LAMP", "output"),  # wired, never touched
        ]
    )
    return cross_reference([block], tags)


def test_verdicts_follow_the_accesses() -> None:
    verdicts = {usage.tag.name: usage.verdict for usage in _report().usages}
    assert verdicts == {
        "DI_START": "read-only",
        "AI_LEVEL": "read-only",
        "DO_PUMP": "write-only",
        "DO_VALVE": "write-only",
        "DI_SPARE": "untouched",
        "DO_LAMP": "untouched",
    }


def test_findings_are_the_untouched_tags_only_here() -> None:
    # Inputs read and outputs written are healthy; only the two spares are findings.
    assert {usage.tag.name for usage in _report().findings} == {"DI_SPARE", "DO_LAMP"}


def test_an_input_only_written_would_be_a_finding() -> None:
    block = SCLParser(tokenize_with_newlines(_SOURCE)).parse()
    tags = TagCollection(tags=[_tag("DI_MYSTERY", "input")])
    report = cross_reference([block], tags)
    (usage,) = report.findings
    assert usage.tag.name == "DI_MYSTERY" and usage.verdict == "write-only"


def test_io_named_tags_the_table_does_not_declare_are_reported_with_sites() -> None:
    report = _report()
    assert "DI_MYSTERY" in report.undeclared
    ((block, line),) = report.undeclared["DI_MYSTERY"]
    assert block == "IoMap" and line > 0


def test_a_tag_accessed_through_a_bit_slice_or_index_is_still_that_tag() -> None:
    source = _SOURCE.replace('"AI_LEVEL" > 2.0', '"AI_LEVEL".%X0')
    block = SCLParser(tokenize_with_newlines(source)).parse()
    report = cross_reference([block], TagCollection(tags=[_tag("AI_LEVEL", "input")]))
    (usage,) = report.usages
    assert usage.verdict == "read-only"


def test_a_whole_silent_prefix_is_flagged_as_a_probably_missing_export() -> None:
    block = SCLParser(tokenize_with_newlines(_SOURCE)).parse()
    tags = TagCollection(tags=[_tag(f"SDI_UNSEEN_{i}", "input") for i in range(3)])
    report = cross_reference([block], tags)
    assert report.silent_prefixes == ["SDI_"]


def test_the_io_prefix_list_covers_every_declared_prefix() -> None:
    from plc_code.analyzer.logic_dependency.tag_parser import TAG_PREFIXES
    from plc_code.analyzer.tag_xref import _IO_PREFIXES

    assert set(TAG_PREFIXES) <= set(_IO_PREFIXES)


def test_analog_outputs_are_declared_tags_now() -> None:
    from plc_code.analyzer.logic_dependency.tag_parser import _get_tag_category

    assert _get_tag_category("AO_VALVE_CMD") == ("AO", "output")
