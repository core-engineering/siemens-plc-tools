"""Every token must be accounted for — the structural anti-silence guarantee.

A translator that drops a construct produces valid, empty output and passes
every diagnostic: the generated Python is syntactically fine and references
only names that are actually defined, so nothing downstream can see the
absence. Counting tokens can — but only in its strong form.

The weak form (``stream.position() == len(tokens)`` at the end of a parse) is
not a check at all: ``StatementParser.parse()``'s own recovery loop already
guarantees the cursor reaches the end of the stream on every input, so that
equality holds unconditionally, before and after a defect, every time. Two
real defects were found and fixed with this weak form in place (Task 5's
``_recover`` and Task 6's ``_parse_case_labels``) and both still passed it,
because both leave the cursor at the very end of the input; they differ only
in whether every token in between ended up in ``result.statements`` or
``result.errors``, which position alone cannot see.

``verify_no_silent_loss`` is the strong form: every token must be covered by
exactly one top-level statement's span or by a recorded error span, and no
statement's span may be wider than its own content (plus any error nested
inside it) can explain. This file exercises it directly, then reintroduces
each historical defect in a scratch copy of the parser and confirms
``verify_no_silent_loss`` — and *only* the strong form — catches it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements, verify_no_silent_loss

SOURCES = [
    "#b := 10;",
    "#b := #a + 1; #c := 2;",
    "IF #a > 1 THEN #b := 2; END_IF;",
    "IF #a THEN #b := 1; ELSIF #c THEN #b := 2; ELSE #b := 3; END_IF;",
    "CASE #a OF 1: #b := 10; 2: #b := 20; ELSE #b := 99; END_CASE;",
    "CASE #a OF\n 1:\n #b := 10;\n ELSE\n #b := 99;\n END_CASE;",
    "FOR #i := 1 TO 9 BY 2 DO #b := #i; END_FOR;",
    "WHILE #a < 5 DO #a := #a + 1; END_WHILE;",
    "#timer(IN := #start, PT := T#5s, Q => #done);",
    "RETURN;",
    # Mixes a readable statement, an unsupported one, and another readable
    # one, so the middle construct's error must not swallow either neighbour.
    "#a := 1; GOTO done; #b := 2;",
    # Every statement here is unreadable; every token must still land in an
    # error span, none silently dropped.
    "GOTO a; CONTINUE; REPEAT #x := 1; UNTIL #y > 0 END_REPEAT;",
    # A CASE with a branch that fails to open with a label, sitting between
    # two branches that do — the exact defect-2 shape, generalised.
    "CASE #a OF 1: #x := 1; #y := 2; 2: #z := 3; END_CASE;",
]


@pytest.mark.parametrize("source", SOURCES, ids=range(len(SOURCES)))
def test_every_token_is_accounted_for_by_a_statement_or_an_error(source: str) -> None:
    """The strong invariant: no gap, and no statement wider than its content."""
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    problems = verify_no_silent_loss(tokens, result)
    assert not problems, "\n".join(problems)


def test_an_unreadable_construct_is_still_accounted_for() -> None:
    """Recovery consumes; it does not leak."""
    tokens = [t for t in tokenize("GOTO done; #b := 1;") if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    assert result.errors
    assert not verify_no_silent_loss(tokens, result)


def test_all_unparseable_stream_is_still_fully_accounted_for() -> None:
    """A stream with no readable statement at all still tiles exactly."""
    tokens = [
        t
        for t in tokenize("REPEAT UNTIL #a > 0 END_REPEAT; GOTO x; CONTINUE;")
        if t.type is not TokenType.EOF
    ]
    result = parse_statements(tokens)
    assert not result.statements
    assert result.errors
    assert not verify_no_silent_loss(tokens, result)


def test_case_branch_that_fails_to_open_still_surfaces_its_statement() -> None:
    """Defect 2, standalone: an unlabelled branch's body is not lost."""
    tokens = [t for t in tokenize("CASE #a OF #x := 1; END_CASE;") if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    assert result.errors
    assert not verify_no_silent_loss(tokens, result)


def test_stray_block_ender_inside_a_case_branch_is_caught() -> None:
    """The reviewer's repro: an unmatched END_WHILE inside an ELSE-less CASE branch.

    ``_parse_case_body``'s last-resort fallback (statement_parser.py, the
    ``elif self._stream.position() == before`` branch) recognises ``END_WHILE``
    as belonging to no CASE construct, so nothing in ``_parse_statement`` reads
    it either; it used to be skipped with no statement, no error and no
    separator recorded for it at all — invisible to both the old weak
    ``consumed_tokens`` check and, before this fix, to the CASE branch of
    ``_content_width``'s unconditional ELSE slack too.
    """
    tokens = [
        t for t in tokenize("CASE #a OF 1: #b := 1; END_WHILE; END_CASE;") if t.type is not TokenType.EOF
    ]
    result = parse_statements(tokens)
    assert not result.errors  # nothing flags this today; that is the point
    problems = verify_no_silent_loss(tokens, result)
    assert problems, "the dropped END_WHILE should be reported"
    assert any("unattributed" in p for p in problems)


def test_stray_block_ender_nested_inside_an_if_inside_a_case_branch_is_caught() -> None:
    """Same shape, one level deeper: the stray keyword is inside an IF's THEN body.

    This exercises ``_parse_body``'s fallback (not ``_parse_case_body``'s),
    reached only because the IF itself is nested inside a CASE branch — the
    top-level statement is the CASE, so only recursive content-width
    accounting (not a top-level span) can see the loss.
    """
    tokens = [
        t
        for t in tokenize("CASE #a OF 1: IF #x THEN #b := 1; END_WHILE; END_IF; END_CASE;")
        if t.type is not TokenType.EOF
    ]
    result = parse_statements(tokens)
    assert not result.errors
    problems = verify_no_silent_loss(tokens, result)
    assert problems, "the dropped END_WHILE nested inside the IF should be reported"
    assert any("unattributed" in p for p in problems)


def test_else_less_case_well_formed_has_no_false_positive() -> None:
    """The tightened (zero) ELSE slack must not flag a genuinely ELSE-less CASE."""
    tokens = [
        t for t in tokenize("CASE #a OF 1: #b := 10; 2: #b := 20; END_CASE;") if t.type is not TokenType.EOF
    ]
    result = parse_statements(tokens)
    assert not verify_no_silent_loss(tokens, result)


def test_case_with_else_arm_well_formed_has_no_false_positive() -> None:
    """A real ELSE arm still earns its (now-conditional) slack."""
    tokens = [
        t
        for t in tokenize("CASE #a OF 1: #b := 10; 2: #b := 20; ELSE #b := 99; END_CASE;")
        if t.type is not TokenType.EOF
    ]
    result = parse_statements(tokens)
    assert not verify_no_silent_loss(tokens, result)


# A present-but-empty ELSE/default arm used to be indistinguishable, by
# content alone, from ELSE being absent entirely — and after round 1 that
# ambiguity was resolved by assuming "absent," so any of these four
# genuinely well-formed inputs false-positived. round 2's fix attributes the
# ELSE keyword (and its tolerated bare colon) as a separator span at the
# point it's actually consumed, in _parse_if/_parse_case/_consume_colon, so
# the width arithmetic no longer needs to guess.
EMPTY_ELSE_ARM_SOURCES = [
    "CASE #a OF 1: #b := 1; ELSE ; END_CASE;",
    "CASE #a OF 1: #b := 1; ELSE END_CASE;",
    "IF #a THEN #b := 1; ELSE ; END_IF;",
    "IF #a THEN #b := 1; ELSE END_IF;",
    # The tolerated bare-colon spelling of an empty default arm.
    "CASE #a OF 1: #b := 1; ELSE: END_CASE;",
]


@pytest.mark.parametrize("source", EMPTY_ELSE_ARM_SOURCES, ids=range(len(EMPTY_ELSE_ARM_SOURCES)))
def test_present_but_empty_else_arm_has_no_false_positive(source: str) -> None:
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    problems = verify_no_silent_loss(tokens, result)
    assert not problems, "\n".join(problems)


def test_critical_repro_is_still_reported_after_the_empty_else_fix() -> None:
    """The regression this round risks: loosening the brackets back out.

    Reconfirms round 1's fix (the stray END_WHILE inside an ELSE-less CASE
    branch) is still caught now that ELSE/default-arm emptiness no longer
    drives any bracket slack at all.
    """
    tokens = [
        t for t in tokenize("CASE #a OF 1: #b := 1; END_WHILE; END_CASE;") if t.type is not TokenType.EOF
    ]
    result = parse_statements(tokens)
    assert not result.errors
    problems = verify_no_silent_loss(tokens, result)
    assert problems, "the dropped END_WHILE should still be reported"
    assert any("unattributed" in p for p in problems)


def _load_scratch_parser(module_name: str, source_text: str) -> object:
    """Load a scratch copy of ``statement_parser`` with its source text swapped in.

    Used only to reintroduce a historical defect for the two regression tests
    below, without touching the real module other tests in this suite import.

    Parameters
    ----------
    module_name : str
        A unique name to register the scratch module under in ``sys.modules``.
    source_text : str
        The full source of the scratch ``statement_parser`` module.

    Returns
    -------
    object
        The loaded module, with ``parse_statements`` and ``verify_no_silent_loss``
        available as attributes.
    """
    scratch_path = Path(__file__).parent / f"_scratch_{module_name}.py"
    scratch_path.write_text(source_text)
    try:
        spec = importlib.util.spec_from_file_location(f"plc_code.parser._scratch_{module_name}", scratch_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        scratch_path.unlink()


def test_weak_form_never_catches_the_old_recover_defect() -> None:
    """Reverting Task 5's fix must break the strong form; the weak form stays silent.

    This is the acceptance check the task specifies: the invariant must fail
    if the fix is reverted. Old ``_recover`` hunted for the next ``;``, so
    ``REPEAT #a := 1; #b := 2; UNTIL #c > 5 END_REPEAT;`` lost ``#a := 1;``
    with no statement and no error naming it.
    """
    real_path = Path(__file__).parent.parent / "src" / "plc_code" / "parser" / "statement_parser.py"
    source_text = real_path.read_text()
    broken = source_text.replace(
        """        if not self._stream.at_end():
            self._stream.advance()

    def _recover_and_record""",
        """        while not self._stream.at_end():
            if self._stream.advance().type is TokenType.SEMICOLON:
                return

    def _recover_and_record""",
        1,
    )
    assert broken != source_text, "the _recover body to replace was not found"

    module = _load_scratch_parser("old_recover", broken)
    tokens = [
        t
        for t in tokenize("REPEAT #a := 1; #b := 2; UNTIL #c > 5 END_REPEAT;")
        if t.type is not TokenType.EOF
    ]
    result = module.parse_statements(tokens)

    # Strong form: catches it.
    problems = module.verify_no_silent_loss(tokens, result)
    assert problems, "reverting the _recover fix should break verify_no_silent_loss"

    # And the dropped statement really is missing from the output.
    targets = [tok.value for stmt in result.statements for tok in getattr(stmt, "target", [])]
    assert "a" not in targets, "expected '#a := 1;' to have been silently dropped by the old bug"


def test_weak_form_never_catches_the_old_case_label_defect() -> None:
    """Reverting Task 6's fix must break the strong form; the weak form stays silent.

    Old ``_parse_case_labels`` scanned speculatively and discarded its buffer
    on failure, so ``CASE #a OF #x := 1; END_CASE;`` lost the whole branch
    with no statement and no error.
    """
    real_path = Path(__file__).parent.parent / "src" / "plc_code" / "parser" / "statement_parser.py"
    source_text = real_path.read_text()

    old_parse_case_branch_loop = """\
        while not self._stream.at_end() and self._keyword_ahead() not in {"ELSE", "END_CASE"}:
            values = self._parse_case_labels()
            if values is None:
                self._error(self._stream.peek(), "a case label")
                self._record_flag_error()
                branches.append(CaseBranch(values=[], body=self._parse_case_body()))
                continue
            body = self._parse_case_body()
            branches.append(
                CaseBranch(
                    values=values,
                    body=body,
                    values_expr=[self._parse_expr(value) for value in values],
                )
            )"""
    new_parse_case_branch_loop = """\
        while not self._stream.at_end() and self._keyword_ahead() not in {"ELSE", "END_CASE"}:
            values = self._parse_case_labels()
            if values is None:
                break
            body = self._parse_case_body()
            branches.append(
                CaseBranch(
                    values=values,
                    body=body,
                    values_expr=[self._parse_expr(value) for value in values],
                )
            )"""
    assert old_parse_case_branch_loop in source_text, "the _parse_case branch loop was not found"

    old_parse_case_labels = """        if not self._at_case_label():
            return None

        values: list[list[Token]] = []
        current: list[Token] = []
        while not self._stream.at_end():
            if self._stream.match(TokenType.COLON):
                self._stream.advance()
                if current:
                    values.append(current)
                return values or None
            if self._stream.match(TokenType.COMMA):
                self._stream.advance()
                if current:
                    values.append(current)
                current = []
                continue
            current.append(self._stream.advance())
        return None  # pragma: no cover - unreachable once `_at_case_label` gates entry"""
    new_parse_case_labels = """        values: list[list[Token]] = []
        current: list[Token] = []
        while not self._stream.at_end():
            if self._stream.match(TokenType.COLON):
                self._stream.advance()
                if current:
                    values.append(current)
                return values or None
            if self._stream.match(TokenType.COMMA):
                self._stream.advance()
                if current:
                    values.append(current)
                current = []
                continue
            if self._keyword_ahead() in {"ELSE", "END_CASE"}:
                return None
            current.append(self._stream.advance())
        return None"""
    assert old_parse_case_labels in source_text, "the _parse_case_labels body was not found"

    broken = source_text.replace(old_parse_case_branch_loop, new_parse_case_branch_loop, 1)
    broken = broken.replace(old_parse_case_labels, new_parse_case_labels, 1)
    assert broken != source_text

    module = _load_scratch_parser("old_case_labels", broken)
    tokens = [t for t in tokenize("CASE #a OF #x := 1; END_CASE;") if t.type is not TokenType.EOF]
    result = module.parse_statements(tokens)

    # Strong form: catches it.
    problems = module.verify_no_silent_loss(tokens, result)
    assert problems, "reverting the case-label fix should break verify_no_silent_loss"

    # And the branch really did vanish: zero errors, zero branches.
    assert not result.errors
    (case,) = result.statements
    assert not case.branches
