"""Instruction handlers for the ladder interpreter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from plc_code.executor.ladder import fixedpoint as fp
from plc_code.parser.ladder_ast import Box, CallBox, CompareContact, Contact

_INT_RE = re.compile(r"^-?\d+$")
_DB_MEMBER_RE = re.compile(r'^"(?P<db>[^"]+)"\.(?P<member>\w+)$')
_COMPARE = {
    "GT": lambda a, b: a > b,
    "LT": lambda a, b: a < b,
    "GE": lambda a, b: a >= b,
    "LE": lambda a, b: a <= b,
    "EQ": lambda a, b: a == b,
    "NE": lambda a, b: a != b,
}


@dataclass
class EvalContext:
    instance: Any
    runtime: Any  # PLCRuntime

    def read(self, operand: str) -> Any:
        operand = operand.strip()
        if operand.startswith("#"):
            return getattr(self.instance, operand[1:])
        if operand.startswith("T#"):
            raise ValueError(
                f"TIME literal {operand!r} is not supported by the ladder interpreter yet"
            )
        if operand in ("True", "TRUE", "true"):
            return True
        if operand in ("False", "FALSE", "false"):
            return False
        if _INT_RE.match(operand):
            return int(operand)
        m = _DB_MEMBER_RE.match(operand)
        if m:
            # Subscript access (not get_db) so a constant DB auto-loads from the
            # runtime's search paths on first use, mirroring the SCL codegen path.
            return getattr(self.runtime.global_dbs[m.group("db")], m.group("member"))
        # bare identifier = block variable
        return getattr(self.instance, operand)

    def write(self, operand: str, value: Any) -> None:
        name = operand[1:] if operand.startswith("#") else operand
        setattr(self.instance, name, value)


def eval_rail(rail: tuple, ctx: EvalContext) -> bool:
    if not rail:  # power rail
        return True
    for term in rail:  # AND of terms
        if not any(_eval_contact(c, ctx) for c in term):  # OR within a term
            return False
    return True


def _eval_contact(c: Any, ctx: EvalContext) -> bool:
    if isinstance(c, Contact):
        val = bool(ctx.read(c.operand))
        return (not val) if c.negated else val
    if isinstance(c, CompareContact):
        return bool(_COMPARE[c.op](ctx.read(c.in1), ctx.read(c.in2)))
    raise TypeError(f"not a contact: {c!r}")


def run_box(box: Box, ctx: EvalContext) -> None:
    if box.op == "Move":
        ctx.write(box.outputs["out1"], ctx.read(box.inputs["in"]))
        return
    if box.op == "Neg":
        ctx.write(box.outputs["out"], fp.neg(ctx.read(box.inputs["in"])))
        return
    a = ctx.read(box.inputs["in1"])
    b = ctx.read(box.inputs["in2"])
    op = {"Mul": fp.mul, "Add": fp.add, "Sub": fp.sub, "Div": fp.div_trunc}[box.op]
    ctx.write(box.outputs["out"], op(a, b))


def run_callbox(cb: CallBox, ctx: EvalContext) -> None:
    if cb.name == "RD_ARRAY_DI":
        _rd_array_di(cb, ctx)
        return
    inputs = {p: ctx.read(o) for p, d, o in cb.params if d == ":="}
    outs = ctx.runtime.call_named_block(cb.name, inputs=inputs, in_outs={})
    for p, d, o in cb.params:
        if d == "=>" and p in outs:
            ctx.write(o, outs[p])


def _rd_array_di(cb: CallBox, ctx: EvalContext) -> None:
    params = {p: (d, o) for p, d, o in cb.params}
    array = ctx.read(params["ARRAY"][1])
    index = ctx.read(params["INDEX"][1])
    out_op = params["OUT"][1]
    err_op = params["ERROR"][1]
    if 0 <= index < len(array):
        ctx.write(out_op, array[index])
        ctx.write(err_op, False)
    else:
        ctx.write(out_op, array[0])  # safe substitute element[0]
        ctx.write(err_op, True)
