"""Python generation from the statement AST.

The executor used to rewrite SCL as text: `ControlFlowTranslator` split a
region's flattened content on newlines and matched control-flow keywords with
regular expressions, so anything it did not recognise was copied verbatim into
the generated Python while `transpile_block` reported success. This module reads
the statement tree instead, and a construct it cannot generate raises rather
than emitting nothing.

It does not translate expressions. For each statement it rebuilds the SCL string
the text path would have handed to `ExpressionTranslator` / `StatementTranslator`
and calls those same methods, so the two paths agree byte for byte by
construction rather than by re-derivation. Replacing them is pass 2.
"""

from __future__ import annotations

from plc_code.parser.lexer import Token


def scl_text(tokens: list[Token]) -> str:
    """The SCL text of a token slice, spelled as ``Region.content`` spells it.

    Parameters
    ----------
    tokens : list[Token]
        A slice carried by a statement node, such as ``Assignment.value``.

    Returns
    -------
    str
        The token values joined with single spaces. `Region.content` is built
        the same way, so this reproduces the substring the text path worked
        from — `#a` reads as `# a`, and that lossiness is deliberate: the
        translators expect it.
    """
    return " ".join(token.value for token in tokens)
