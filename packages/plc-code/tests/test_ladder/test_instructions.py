from typing import Any

from plc_code.executor.ladder.instructions import EvalContext, eval_rail, run_box, run_callbox
from plc_code.parser.ladder_ast import Box, CallBox, CompareContact, Contact


class FakeInstance:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class FakeRuntime:
    def __init__(self, dbs: dict[str, Any] | None = None) -> None:
        self.global_dbs: dict[str, Any] = dbs or {}


def _ctx(**vars_: Any) -> EvalContext:
    inst = FakeInstance(**vars_)
    return EvalContext(instance=inst, runtime=FakeRuntime())


def test_eval_rail_series_and() -> None:
    # Two-term rail: (a,) AND (b,) — both True → True
    c = _ctx(a=True, b=True)
    assert eval_rail(((Contact("#a"),), (Contact("#b"),)), c) is True


def test_eval_rail_parallel_or() -> None:
    # Single term with two contacts OR'd: a=False, b=True → True
    c = _ctx(a=False, b=True)
    assert eval_rail(((Contact("#a"), Contact("#b")),), c) is True


def test_compare_contact_gt() -> None:
    c = _ctx(angle=950)
    assert eval_rail(((CompareContact("GT", "#angle", "900"),),), c) is True
    c2 = _ctx(angle=800)
    assert eval_rail(((CompareContact("GT", "#angle", "900"),),), c2) is False


def test_box_mul_div_trunc() -> None:
    c = _ctx(scaleTemp=0, sinQ14=13106, length=300)
    run_box(Box("Mul", {"in1": "#sinQ14", "in2": "#length"}, {"out": "#scaleTemp"}), c)
    assert c.instance.scaleTemp == 13106 * 300
    run_box(Box("Div", {"in1": "#scaleTemp", "in2": "16384"}, {"out": "#scaleTemp"}), c)
    assert c.instance.scaleTemp == (13106 * 300) // 16384


def test_rd_array_di_in_and_out_of_bounds() -> None:
    class DB:
        LutSinQ14 = [0, 29, 57, 86]

    rt = FakeRuntime({"DataSafetyKinematics": DB()})
    inst: Any = FakeInstance(idx=2, val=0, err=False)
    c = EvalContext(instance=inst, runtime=rt)
    cb = CallBox("RD_ARRAY_DI", (("ARRAY", ":=", '"DataSafetyKinematics".LutSinQ14'),
                                 ("INDEX", ":=", "#idx"), ("OUT", "=>", "#val"), ("ERROR", "=>", "#err")))
    run_callbox(cb, c)
    assert inst.val == 57 and inst.err is False
    inst.idx = 99
    run_callbox(cb, c)
    assert inst.val == 0 and inst.err is True  # substitute element[0], ERROR set


def test_negated_contact() -> None:
    assert eval_rail(((Contact("#a", negated=True),),), _ctx(a=False)) is True
    assert eval_rail(((Contact("#a", negated=True),),), _ctx(a=True)) is False


def test_box_div_truncates_toward_zero_on_negative() -> None:
    c = _ctx(x=-7)
    run_box(Box("Div", {"in1": "#x", "in2": "2"}, {"out": "#x"}), c)
    assert c.instance.x == -3  # truncation toward zero, not floor (-4)
