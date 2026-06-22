"""Typed AST for F-LAD (Ladder) networks.

A block's networks are flattened into a single ordered `LadderProgram` of rungs
and label markers. Each `Rung` has a boolean rail (AND of OR-terms over contacts;
an empty rail means the power rail, always true) and a sequence of actions
(coils, jumps, boxes, sub-block calls) gated by that rail (boxes execute
unconditionally — see the interpreter).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Contact:
    operand: str
    negated: bool = False


@dataclass(frozen=True)
class CompareContact:
    op: str  # GT, LT, GE, LE, EQ, NE
    in1: str
    in2: str


@dataclass(frozen=True)
class Coil:
    operand: str


@dataclass(frozen=True)
class JumpCoil:
    label: str


@dataclass(frozen=True)
class Box:
    op: str  # Move, Neg, Mul, Div, Add, Sub
    inputs: dict[str, str]
    outputs: dict[str, str]


@dataclass(frozen=True)
class CallBox:
    name: str
    params: tuple[tuple[str, str, str], ...]  # (param_name, ":=" | "=>", operand)


type RailTerm = tuple[Contact | CompareContact, ...]
type Action = Coil | JumpCoil | Box | CallBox


@dataclass(frozen=True)
class Rung:
    rail: tuple[RailTerm, ...]  # AND of terms, each term an OR of contacts
    actions: tuple[Action, ...]


@dataclass(frozen=True)
class LabelRung:
    name: str


@dataclass(frozen=True)
class LadderProgram:
    rungs: tuple[Rung | LabelRung, ...]
