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


def test_construct_simple_coil_rung() -> None:
    rung = Rung(rail=((Contact("#isOutOfDomain"),),), actions=(Coil("#fault"),))
    assert rung.actions[0].operand == "#fault"
    assert rung.rail[0][0].operand == "#isOutOfDomain"


def test_construct_unconditional_box() -> None:
    box = Box(op="Mul", inputs={"in1": "#sinQ14", "in2": "#length"}, outputs={"out": "#scaleTemp"})
    rung = Rung(rail=(), actions=(box,))
    assert rung.rail == ()
    assert rung.actions[0].op == "Mul"


def test_callbox_and_compare_and_jump() -> None:
    cb = CallBox(name="ABS", params=(("x", ":=", "#angle"), ("y", "=>", "#angleAbs")))
    cmp = CompareContact(op="GT", in1="#angle", in2="900")
    jump = JumpCoil("END")
    prog = LadderProgram(
        rungs=(
            Rung(rail=((cmp,),), actions=(jump,)),
            LabelRung("END"),
            Rung(rail=(), actions=(cb,)),
        )
    )
    assert prog.rungs[1].name == "END"
    assert prog.rungs[2].actions[0].name == "ABS"
