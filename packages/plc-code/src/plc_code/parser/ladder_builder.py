"""Build a typed rung AST (:class:`LadderProgram`) from parsed F-LAD networks.

The SCL parser captures each ladder rung as a raw dict in
``Network.rungs_raw`` (``{"open_wire", "elements", "close_wire"}``). This module
turns those raw rungs into the typed AST defined in :mod:`plc_code.parser.ladder_ast`.

Wire topology -> rail
---------------------
Each element is one of: a contact (``Contact``/``I_Contact``), a compare contact
(``GT_Contact`` ...), a coil/jump (``Coil``/``JumpCoil``), an arithmetic box
(``Move``/``Neg``/...), or a sub-block call (``"ABS"(...)`` / ``RD_ARRAY_DI(...)``).

Within a rung the contacts that precede the action(s) form a *series* (AND) of
rail terms — one contact per term. Parallel-OR branches are expressed across
sibling rungs of the *same* network using ``wire#`` markers: a coil-bearing rung
exposes an internal ``wire#wN`` element right after the contact that feeds the
branch, and later sibling rungs whose ``close_wire == wire#wN`` OR their leading
contact into that *same* rail term. This is how ``isOutOfDomain = GT OR LT`` and
``fault = isOutOfDomain OR lutError OR lutError2`` are encoded.

Any rung shape outside these documented patterns raises ``ValueError`` rather
than guessing (accepted scope boundary, spec §6).
"""

from __future__ import annotations

import re

from plc_code.parser.ladder_ast import (
    Box,
    CallBox,
    Coil,
    CompareContact,
    Contact,
    JumpCoil,
    LabelRung,
    LadderProgram,
    Rung,
)
from plc_code.parser.models import Block

# Element name classification.
_COMPARE_OPS = {"GT", "LT", "GE", "LE", "EQ", "NE"}
_BOX_OPS = {"Move", "Neg", "Mul", "Div", "Add", "Sub"}
# Known bare-name (unquoted) instructions that are sub-block calls, not boxes.
_KNOWN_CALLS = {"RD_ARRAY_DI", "WR_ARRAY_DI"}

# Split "Name(args)" into name + inner argument text.
_CALL_RE = re.compile(r"^([A-Za-z_][\w]*)\((.*)\)$", re.DOTALL)
_COMPARE_RE = re.compile(r"^([A-Za-z]+)_Contact$")


def _split_call(elem: str) -> tuple[str, str]:
    """Split ``Name(args)`` into ``(name, args)``; raise on a non-call element."""
    match = _CALL_RE.match(elem.strip())
    if not match:
        raise ValueError(f"unsupported ladder rung: {elem!r}")
    return match.group(1), match.group(2)


def _split_params(args: str) -> list[tuple[str, str, str]]:
    """Parse ``a := #x, b => #y`` into ``[(name, ":="|"=>", operand), ...]``.

    Splits on commas at depth 0 so quoted DB references like
    ``"DataSafetyKinematics".LutSinQ14`` (which contain no commas) survive, and
    nested calls (none expected here) would not split mid-argument.
    """
    args = args.strip()
    if not args:
        return []
    parts: list[str] = []
    depth = 0
    current = ""
    in_quote = False
    for ch in args:
        if ch == '"':
            in_quote = not in_quote
            current += ch
        elif ch in "([" and not in_quote:
            depth += 1
            current += ch
        elif ch in ")]" and not in_quote:
            depth -= 1
            current += ch
        elif ch == "," and depth == 0 and not in_quote:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current)

    params: list[tuple[str, str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Output assignment "=>" must be tested before input ":=".
        if "=>" in part:
            name, operand = part.split("=>", 1)
            params.append((name.strip(), "=>", operand.strip()))
        elif ":=" in part:
            name, operand = part.split(":=", 1)
            params.append((name.strip(), ":=", operand.strip()))
        else:
            raise ValueError(f"unsupported ladder param: {part!r}")
    return params


def _parse_element(elem: str) -> Contact | CompareContact | Coil | JumpCoil | Box | CallBox:
    """Classify one element string into a typed AST node."""
    name, args = _split_call(elem)

    if name == "Contact":
        return Contact(operand=args.strip())
    if name == "I_Contact":
        return Contact(operand=args.strip(), negated=True)

    compare = _COMPARE_RE.match(name)
    if compare and compare.group(1) in _COMPARE_OPS:
        params = {p[0]: p[2] for p in _split_params(args)}
        if "in1" not in params or "in2" not in params:
            raise ValueError(f"unsupported ladder rung: {elem!r}")
        return CompareContact(op=compare.group(1), in1=params["in1"], in2=params["in2"])

    if name == "Coil":
        return Coil(operand=args.strip())
    if name == "JumpCoil":
        return JumpCoil(label=args.strip())

    if name in _BOX_OPS:
        inputs: dict[str, str] = {}
        outputs: dict[str, str] = {}
        for pname, kind, operand in _split_params(args):
            if kind == ":=":
                inputs[pname] = operand
            else:
                outputs[pname] = operand
        return Box(op=name, inputs=inputs, outputs=outputs)

    # Sub-block call: quoted names are de-quoted by the parser, so we can only
    # tell a call from a box by membership in the known set or by the original
    # being a quoted name. The parser strips quotes, so accept known calls plus
    # anything not otherwise recognised here that looks like a call to a block.
    if name in _KNOWN_CALLS or _is_block_call(name):
        return CallBox(name=name, params=tuple(_split_params(args)))

    raise ValueError(f"unsupported ladder instruction: {elem!r}")


def _is_block_call(name: str) -> bool:
    """Heuristic: a non-instruction call name is a user sub-block call.

    The parser strips the quotes off ``"ABS"(...)`` so by the time we get here a
    user-block call looks like a bare identifier. Anything that is not a known
    contact/coil/box/compare instruction is treated as a sub-block call.
    """
    return name not in ({"Contact", "I_Contact", "Coil", "JumpCoil"} | _BOX_OPS) and not _COMPARE_RE.match(
        name
    )


def _build_network_rungs(raw_rungs: list[dict[str, object]]) -> list[Rung | LabelRung]:
    """Build the typed rungs for a single network, resolving parallel-OR branches.

    A coil-bearing rung that exposes an internal ``wire#wN`` after its leading
    contact owns rail term ``wN``; sibling rungs with ``close_wire == wire#wN``
    contribute their leading contact to that same term (OR).
    """
    # First pass: collect OR-branch contacts keyed by their join wire.
    branch_contacts: dict[str, list[Contact | CompareContact]] = {}
    for raw in raw_rungs:
        close_wire = raw["close_wire"]
        elements = raw["elements"]
        assert isinstance(elements, list)
        if close_wire is None:
            continue
        # A pure branch rung: leading contact(s) only, no coil/box/call.
        contacts = [_parse_element(e) for e in elements if not _is_wire(e)]
        for c in contacts:
            if not isinstance(c, Contact | CompareContact):
                raise ValueError(f"unsupported ladder branch rung: {elements!r}")
        assert isinstance(close_wire, str)
        branch_contacts.setdefault(close_wire, []).extend(contacts)  # type: ignore[arg-type]

    result: list[Rung | LabelRung] = []
    for raw in raw_rungs:
        if raw["close_wire"] is not None:
            # Branch rung already folded into its owner; skip emitting separately.
            continue
        elements = raw["elements"]
        assert isinstance(elements, list)

        # A LabelRung: the only element is Label(NAME).
        if len(elements) == 1 and elements[0].startswith("Label("):
            name = elements[0][len("Label(") : -1].strip()
            result.append(LabelRung(name=name))
            continue

        rail: list[tuple[Contact | CompareContact, ...]] = []
        actions: list[Coil | JumpCoil | Box | CallBox] = []
        tap_wire: str | None = None

        for elem in elements:
            if _is_wire(elem):
                # Internal wire marker: tags the rail term just built as the
                # OR-tap for branches that join on this wire.
                tap_wire = elem
                continue
            node = _parse_element(elem)
            if isinstance(node, Contact | CompareContact):
                term: list[Contact | CompareContact] = [node]
                # Merge any OR branches that join on the wire tapped right after
                # this contact.
                if tap_wire is not None and tap_wire in branch_contacts:
                    term.extend(branch_contacts[tap_wire])
                    tap_wire = None
                rail.append(tuple(term))
            elif tap_wire is not None and tap_wire in branch_contacts:
                # Wire tapped before reaching this action but after the last
                # contact: fold branches into the most recent rail term.
                if not rail:
                    raise ValueError(f"unsupported ladder rung: {elements!r}")
                rail[-1] = rail[-1] + tuple(branch_contacts[tap_wire])
                tap_wire = None
                actions.append(node)
            else:
                actions.append(node)

        result.append(Rung(rail=tuple(rail), actions=tuple(actions)))
    return result


def _is_wire(elem: str) -> bool:
    """Return True if the element string is an internal ``wire#…`` marker."""
    return elem.startswith("wire#")


def build_ladder_program(block: Block) -> LadderProgram:
    """Build a :class:`LadderProgram` from a parsed F-LAD block.

    Flattens all networks' rungs in declaration order into a single typed rung
    sequence. Parallel-OR branches (sibling rungs joined by ``wire#`` markers)
    are resolved within each network.

    Parameters
    ----------
    block : Block
        A parsed ladder block (``block.is_ladder`` is expected to be true).

    Returns
    -------
    LadderProgram
        The flattened typed rung AST.
    """
    rungs: list[Rung | LabelRung] = []
    for network in block.networks:
        rungs.extend(_build_network_rungs(network.rungs_raw))
    return LadderProgram(rungs=tuple(rungs))
