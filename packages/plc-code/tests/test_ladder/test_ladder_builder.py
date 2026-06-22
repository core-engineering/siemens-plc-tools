from pathlib import Path

from plc_code.parser import parse_scl_file
from plc_code.parser.ladder_ast import (  # noqa: F401 (LabelRung used via type-name assert)
    Box,
    CallBox,
    Coil,
    CompareContact,
    JumpCoil,
    LabelRung,
    Rung,
)
from plc_code.parser.ladder_builder import build_ladder_program

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"


def test_abs_program_shape() -> None:
    block = parse_scl_file(FIX / "ABS.s7dcl")
    prog = build_ladder_program(block)
    kinds = [type(r).__name__ for r in prog.rungs]
    # ABS: coil(end); Move(x->y); GE_Contact -> JumpCoil(END); Neg(x->y); Label(END) coil(end)
    assert "LabelRung" in kinds
    # there is a JumpCoil to END
    jumps = [a for r in prog.rungs if isinstance(r, Rung) for a in r.actions if isinstance(a, JumpCoil)]
    assert any(j.label == "END" for j in jumps)
    # there is a Neg box and a Move box
    boxes = [a.op for r in prog.rungs if isinstance(r, Rung) for a in r.actions if isinstance(a, Box)]
    assert "Neg" in boxes and "Move" in boxes


def test_sin_domain_check_is_parallel_or() -> None:
    block = parse_scl_file(FIX / "SinCalculation.s7dcl")
    prog = build_ladder_program(block)
    # the first coil-bearing rung writes #isOutOfDomain, gated by an OR of two compare contacts
    coil_rungs = [r for r in prog.rungs if isinstance(r, Rung)
                  and any(isinstance(a, Coil) and a.operand == "#isOutOfDomain" for a in r.actions)]
    assert coil_rungs, "expected a coil writing #isOutOfDomain"
    rung = coil_rungs[0]
    # one rail term that ORs two compare contacts (GT 900, LT -900)
    ops = {c.op for term in rung.rail for c in term if isinstance(c, CompareContact)}
    assert {"GT", "LT"} <= ops


def test_rd_array_di_is_callbox() -> None:
    block = parse_scl_file(FIX / "SinCalculation.s7dcl")
    prog = build_ladder_program(block)
    calls = [a for r in prog.rungs if isinstance(r, Rung) for a in r.actions if isinstance(a, CallBox)]
    names = {c.name for c in calls}
    assert "RD_ARRAY_DI" in names and "ABS" in names and "SIGN" in names
