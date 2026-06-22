"""The ladder interpreter: one cycle over a LadderProgram with a program counter."""

from __future__ import annotations

from typing import Any

from plc_code.executor.ladder.instructions import (
    EvalContext,
    eval_rail,
    run_box,
    run_callbox,
)
from plc_code.parser.ladder_ast import (
    Box,
    CallBox,
    Coil,
    JumpCoil,
    LabelRung,
    LadderProgram,
    Rung,
)


class LadderInterpreter:
    def __init__(self, program: LadderProgram) -> None:
        self._program = program
        self._labels = {
            r.name: i for i, r in enumerate(program.rungs) if isinstance(r, LabelRung)
        }

    def run(self, instance: Any, runtime: Any) -> None:
        ctx = EvalContext(instance=instance, runtime=runtime)
        rungs = self._program.rungs
        pc = 0
        guard = 0
        max_steps = len(rungs) * 1000 + 1000  # backstop against a malformed jump loop
        while pc < len(rungs):
            guard += 1
            if guard > max_steps:
                raise RuntimeError("ladder interpreter exceeded step budget (jump loop?)")
            rung = rungs[pc]
            if isinstance(rung, LabelRung):
                pc += 1
                continue
            assert isinstance(rung, Rung)
            rail = eval_rail(rung.rail, ctx)
            jumped = False
            for action in rung.actions:
                if isinstance(action, Box):
                    run_box(action, ctx)
                elif isinstance(action, CallBox):
                    run_callbox(action, ctx)
                elif isinstance(action, Coil):
                    ctx.write(action.operand, rail)
                elif isinstance(action, JumpCoil):
                    if rail:
                        pc = self._labels[action.label]
                        jumped = True
                        break
                else:
                    raise TypeError(f"unknown action: {action!r}")
            if not jumped:
                pc += 1
