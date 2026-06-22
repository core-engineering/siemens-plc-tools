from dataclasses import dataclass
from pathlib import Path

from plc_code.executor.ladder.interpreter import LadderInterpreter
from plc_code.parser import parse_scl_file
from plc_code.parser.ladder_builder import build_ladder_program

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"


class FakeRuntime:
    def get_db(self, name: str) -> object:
        raise KeyError(name)

    def call_named_block(self, name: str, inputs: object, in_outs: object) -> object:
        raise AssertionError("no sub-calls in ABS/SIGN")


@dataclass
class AbsInst:
    x: int = 0
    y: int = 0
    end: bool = False


def run_abs(x: int) -> int:
    prog = build_ladder_program(parse_scl_file(FIX / "ABS.s7dcl"))
    inst = AbsInst(x=x)
    LadderInterpreter(prog).run(inst, FakeRuntime())
    return inst.y


def test_abs_negative() -> None:
    assert run_abs(-5) == 5  # the label fall-through bug would give -5


def test_abs_positive() -> None:
    assert run_abs(5) == 5


def test_abs_zero() -> None:
    assert run_abs(0) == 0


@dataclass
class SignInst:
    x: int = 0
    isNegative: bool = False
    y: int = 0
    end: bool = False


def run_sign(x: int, is_negative: bool) -> int:
    prog = build_ladder_program(parse_scl_file(FIX / "SIGN.s7dcl"))
    inst = SignInst(x=x, isNegative=is_negative)
    LadderInterpreter(prog).run(inst, FakeRuntime())
    return inst.y


def test_sign_applies_negation_when_flagged() -> None:
    assert run_sign(9267, True) == -9267


def test_sign_keeps_value_when_not_flagged() -> None:
    assert run_sign(9267, False) == 9267
