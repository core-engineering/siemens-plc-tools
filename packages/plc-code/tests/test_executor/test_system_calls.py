"""System instructions with `=>` outputs: RD_SYS_T is real, the rest are logged stubs.

`#ret := GET_DIAG(MODE := 1, CNT_DIAG => #n)` was refused (6 production blocks):
a positional call has nowhere to route the output. It is now a
`PLCRuntime.system_call` whose result dict feeds each output and the return
value; every call lands in `runtime.system_call_log`.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.executor.harness import create_harness

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_rd_sys_t_reads_the_simulated_clock_and_the_rest_are_logged_stubs() -> None:
    harness = create_harness(FIXTURES / "SystemCalls.s7dcl")
    harness.runtime.epoch = harness.runtime.epoch.replace(year=2030)
    harness.advance_time(3600.0)
    harness.execute()
    assert harness.get_output("status") == 0
    assert harness.get_output("year") == 2030
    assert harness.get_output("ldt") == int(harness.runtime.system_time().timestamp()) * 1_000_000_000
    assert harness.get_output("count") == 0  # stub: no hardware behind the harness
    assert harness.get_var("diagStatus") == 0
    names = [name for name, _inputs, _outputs in harness.runtime.system_call_log]
    assert names == ["RD_SYS_T", "GET_DIAG", "GET_DIAG"]
    assert harness.runtime.system_call_log[1][1] == {"MODE": 1, "LADDR": 0x100}


def test_value_only_system_instructions_are_logged_stubs() -> None:
    from plc_code.executor.renderer import render
    from plc_code.executor.runtime import PLCRuntime
    from plc_code.parser.expression_parser import parse_expression
    from plc_code.parser.lexer import TokenType, tokenize

    tree = parse_expression([t for t in tokenize("LED(#addr, 1)") if t.type is not TokenType.EOF]).expression
    assert render(tree) == "(lambda *args: self._runtime.system_value('LED', *args))(self.addr, 1)"
    runtime = PLCRuntime()
    assert runtime.system_value("RH_GetPrimaryID") == 0
    assert runtime.system_call_log == [("RH_GetPrimaryID", {}, [])]
