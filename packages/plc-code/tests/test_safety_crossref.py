"""The three boundary checks.

A cross-block check is not expressible as a Rule: `Rule.check(self, block)`
sees one block and the runner loops per block, so "this standard block calls a
safety block" cannot reach the callee's flag. This follows the repository's
existing shape for cross-block work instead — `build_db_crossref`,
`build_call_graph` — and returns plain `Violation`s.

Every violation names its subject by source path, never by block name: all 13
safety UDTs in the corpus parsed with an empty name before Task 2, and paths are
unique whatever the parser does with names.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.analyzer.quality.models import Severity
from plc_code.analyzer.safety_crossref import build_safety_report, is_safety_block
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _fb(name: str, safety: bool, calls: list[str] | None = None) -> str:
    """Build a block in the shape the real corpus uses.

    The attribute pragma block comes BEFORE the ``FUNCTION_BLOCK`` line — that is
    where TIA Portal writes it, verified against
    ``Program blocks/200 - Safety/.../PercArmedTriggering.s7dcl``. A pragma placed
    after the declaration line reaches ``_parse_pragma_or_network``, not
    ``_parse_block_attributes``, so ``is_safety`` would silently stay False.
    """
    pragma = '\n    S7_Safety := "True";' if safety else ""
    body = "\n".join(f'            "{c}"();' for c in (calls or [])) or "            #a := FALSE;"
    return f"""{{
    S7_Optimized := "TRUE";{pragma}
}}
FUNCTION_BLOCK "{name}"
    VAR_INPUT
        a : Bool;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _ob(name: str, calls: list[str] | None = None) -> str:
    """Build an organization block in the shape the real corpus uses.

    Derived from ``_fb()``: same attribute-pragma-before-declaration shape,
    verified against
    ``Program blocks/100 - Process/101 - Organisation Blocks/Main.s7dcl``. An
    OB has no ``VAR_INPUT`` section in that corpus, so this shape omits it. No
    OB in the observed corpus declares ``S7_Safety``, so this helper has no
    ``safety`` parameter.
    """
    body = "\n".join(f'            "{c}"();' for c in (calls or [])) or "            #a := FALSE;"
    return f"""{{
    S7_Optimized := "TRUE";
}}
ORGANIZATION_BLOCK "{name}"
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_ORGANIZATION_BLOCK
"""


def _parse(source: str):
    return SCLParser(tokenize_with_newlines(source)).parse()


def _pair(path: str, source: str) -> tuple[Path, object]:
    return (Path(path), _parse(source))


def _udt(name: str, safety: bool) -> str:
    """Build a UDT (TYPE) in the shape the real corpus uses.

    Mirrors ``TestIsSafetyBlock.test_reads_the_udt_flag_for_a_type`` above: the
    pragma sits between ``TYPE`` and the type name, which is where TIA Portal
    writes it.
    """
    pragma = '\n    { S7_Safety := "True" }' if safety else ""
    return f"TYPE{pragma}\n    {name} : STRUCT\n        a : Bool;\n    END_STRUCT;\nEND_TYPE\n"


class TestIsSafetyBlock:
    def test_reads_the_block_attribute(self) -> None:
        assert is_safety_block(_parse(_fb("F", safety=True))) is True
        assert is_safety_block(_parse(_fb("S", safety=False))) is False

    def test_reads_the_udt_flag_for_a_type(self) -> None:
        udt = _parse(
            'TYPE\n    { S7_Safety := "True" }\n    typeFoo : STRUCT\n'
            "        a : Bool;\n    END_STRUCT;\nEND_TYPE\n"
        )
        assert is_safety_block(udt) is True


class TestF001StandardCallsSafety:
    def test_reported_as_an_error(self) -> None:
        report = build_safety_report(
            [
                _pair("std/Caller.s7dcl", _fb("Caller", safety=False, calls=["FTarget"])),
                _pair("safety/FTarget.s7dcl", _fb("FTarget", safety=True)),
            ]
        )
        f001 = [v for v in report.violations if v.rule_code == "F001"]
        assert len(f001) == 1
        assert f001[0].severity is Severity.ERROR
        assert "FTarget" in f001[0].message

    def test_names_the_subject_by_path(self) -> None:
        report = build_safety_report(
            [
                _pair("std/Caller.s7dcl", _fb("Caller", safety=False, calls=["FTarget"])),
                _pair("safety/FTarget.s7dcl", _fb("FTarget", safety=True)),
            ]
        )
        f001 = [v for v in report.violations if v.rule_code == "F001"][0]
        assert "std/Caller.s7dcl" in f001.context

    def test_an_organization_block_caller_is_checked(self) -> None:
        """An OB is where standard cyclic code invokes FBs, so it must be checked.

        Excluding ORGANIZATION_BLOCK from the callable kinds made this crossing
        invisible. No OB in the observed corpus declares S7_Safety, so nothing in
        production moves — but the path has to stay closed.
        """
        report = build_safety_report(
            [
                _pair("std/Main.s7dcl", _ob("Main", calls=["FTarget"])),
                _pair("safety/FTarget.s7dcl", _fb("FTarget", safety=True)),
            ]
        )
        f001 = [v for v in report.violations if v.rule_code == "F001"]
        assert len(f001) == 1
        assert "std/Main.s7dcl" in f001[0].context


class TestF002SafetyCallsStandard:
    def test_reported_as_an_error(self) -> None:
        report = build_safety_report(
            [
                _pair("safety/FCaller.s7dcl", _fb("FCaller", safety=True, calls=["Target"])),
                _pair("std/Target.s7dcl", _fb("Target", safety=False)),
            ]
        )
        f002 = [v for v in report.violations if v.rule_code == "F002"]
        assert len(f002) == 1
        assert f002[0].severity is Severity.ERROR


class TestNameCollisionWithANonCallableKind:
    def test_a_udt_sharing_a_name_cannot_silence_a_crossing(self) -> None:
        """A UDT is never a caller or a callee; it must not hide a real F001."""
        report = build_safety_report(
            [
                _pair("std/Caller.s7dcl", _fb("Caller", safety=False, calls=["Worker"])),
                _pair("safety/Worker.s7dcl", _fb("Worker", safety=True)),
                _pair("types/Worker.s7dcl", _udt("Worker", safety=False)),
            ]
        )
        f001 = [v for v in report.violations if v.rule_code == "F001"]
        assert len(f001) == 1

    def test_a_udt_sharing_a_name_cannot_fabricate_a_crossing(self) -> None:
        """A UDT is never a caller or a callee; it must not fabricate an F001/F002."""
        report = build_safety_report(
            [
                _pair("std/Caller.s7dcl", _fb("Caller", safety=False, calls=["Worker"])),
                _pair("std/Worker.s7dcl", _fb("Worker", safety=False)),
                _pair("types/Worker.s7dcl", _udt("Worker", safety=True)),
            ]
        )
        assert [v for v in report.violations if v.rule_code in {"F001", "F002"}] == []


class TestNoViolationWhenBothSidesAgree:
    def test_safety_calling_safety_is_clean(self) -> None:
        report = build_safety_report(
            [
                _pair("safety/A.s7dcl", _fb("A", safety=True, calls=["B"])),
                _pair("safety/B.s7dcl", _fb("B", safety=True)),
            ]
        )
        assert [v for v in report.violations if v.rule_code in {"F001", "F002"}] == []

    def test_standard_calling_standard_is_clean(self) -> None:
        report = build_safety_report(
            [
                _pair("std/A.s7dcl", _fb("A", safety=False, calls=["B"])),
                _pair("std/B.s7dcl", _fb("B", safety=False)),
            ]
        )
        assert [v for v in report.violations if v.rule_code in {"F001", "F002"}] == []


class TestF003DeclarationAndPathDisagree:
    def test_unmarked_block_inside_a_safety_path(self) -> None:
        report = build_safety_report([_pair("Safety/Arm/Foo.s7dcl", _fb("Foo", safety=False))])
        f003 = [v for v in report.violations if v.rule_code == "F003"]
        assert len(f003) == 1
        assert f003[0].severity is Severity.WARNING

    def test_marked_block_outside_a_safety_path(self) -> None:
        report = build_safety_report([_pair("Process/Foo.s7dcl", _fb("Foo", safety=True))])
        assert len([v for v in report.violations if v.rule_code == "F003"]) == 1

    def test_agreement_is_clean_both_ways(self) -> None:
        report = build_safety_report(
            [
                _pair("Safety/Foo.s7dcl", _fb("Foo", safety=True)),
                _pair("Process/Bar.s7dcl", _fb("Bar", safety=False)),
            ]
        )
        assert [v for v in report.violations if v.rule_code == "F003"] == []

    def test_match_is_case_insensitive(self) -> None:
        report = build_safety_report([_pair("SAFETY/Foo.s7dcl", _fb("Foo", safety=True))])
        assert [v for v in report.violations if v.rule_code == "F003"] == []

    def test_pattern_is_configurable(self) -> None:
        report = build_safety_report(
            [_pair("secu/Foo.s7dcl", _fb("Foo", safety=True))],
            safety_path_pattern="secu",
        )
        assert [v for v in report.violations if v.rule_code == "F003"] == []

    def test_the_pattern_matches_the_directory_not_the_filename(self) -> None:
        """A standard block named ...Safety... is not a safety block.

        project-A has 14 of these — `100 - Process/.../SafetyAlarm.s7dcl` and
        friends — standard code that interfaces with the safety side. Matching
        the whole path would report every one of them.
        """
        report = build_safety_report(
            [_pair("Process/Alarms/SafetyAlarm.s7dcl", _fb("SafetyAlarm", safety=False))]
        )
        assert [v for v in report.violations if v.rule_code == "F003"] == []


class TestCounts:
    def test_report_counts_both_populations(self) -> None:
        report = build_safety_report(
            [
                _pair("safety/A.s7dcl", _fb("A", safety=True)),
                _pair("std/B.s7dcl", _fb("B", safety=False)),
                _pair("std/C.s7dcl", _fb("C", safety=False)),
            ]
        )
        assert report.safety_blocks == 1
        assert report.standard_blocks == 2
