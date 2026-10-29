"""Integration tests for compiling F-LAD blocks through the harness.

Fixture paths are anchored to this file's location so the suite passes from
both the repo root and the package directory. The fixture directory is the
sub-block / constant-DB search path: ``from_scl_file`` registers the directory
containing the entry block automatically, so ``ABS``, ``SIGN`` and the constant
``DataSafetyKinematics`` DB all resolve without an explicit ``search_paths``
argument.
"""

from pathlib import Path

from plc_code.executor import create_harness
from plc_code.executor.models import TranspileOptions
from plc_code.executor.transpiler import SCLTranspiler
from plc_code.executor.types import TypeMapper
from plc_code.parser import parse_scl_file

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"


def test_emit_fields_and_metadata_public_seam() -> None:
    """The ladder compiler reuses ``SCLTranspiler.emit_fields_and_metadata`` (a
    public seam) rather than poking private members, so fields/metadata stay
    identical to the SCL path."""
    block = parse_scl_file(FIX / "ABS.s7dcl")  # VAR_INPUT x, VAR_OUTPUT y, VAR_TEMP end
    source = SCLTranspiler(
        block=block, options=TranspileOptions(), type_mapper=TypeMapper()
    ).emit_fields_and_metadata()
    assert "x:" in source  # the input field declaration
    assert "y:" in source  # the output field declaration
    assert "_inputs" in source  # metadata tuple the harness reads
    assert "_outputs" in source


def test_abs_via_harness() -> None:
    h = create_harness(FIX / "ABS.s7dcl")
    h.set_inputs(x=-5)
    h.execute()
    assert h.get_output("y") == 5


def test_sin_calls_subblocks_and_db() -> None:
    # The fixture directory is auto-registered as a block search path, so the
    # sub-blocks ABS/SIGN AND the constant DataSafetyKinematics DB (LUT array
    # initialisers included) all resolve automatically — no manual registration.
    h = create_harness(FIX / "SinCalculation.s7dcl")
    h.set_inputs(angle=3000, length=13106)
    h.execute()
    assert h.get_output("result") == 6553
    assert not h.get_output("fault")


def _sign_with_contact_before_move(tmp_path: Path, *, safety: bool) -> Path:
    """SIGN with its `Move` put behind `#isNegative`, i.e. with EN wired."""
    text = (FIX / "SIGN.s7dcl").read_text(encoding="utf-8-sig")
    text = text.replace("            Move(\n", "            I_Contact( #isNegative )\n            Move(\n", 1)
    if not safety:
        text = text.replace('    S7_Safety := "TRUE";\n', "")
    path = tmp_path / "SIGN.s7dcl"
    path.write_text(text, encoding="utf-8-sig")
    return path


def test_f_lad_box_behind_a_contact_is_refused(tmp_path: Path) -> None:
    """TIA refuses EN in a safety program, so the executor must not invent a meaning for it."""
    from plc_code.executor.ladder.compile import compile_ladder_block

    block = parse_scl_file(_sign_with_contact_before_move(tmp_path, safety=True))
    result = compile_ladder_block(block)
    assert result.success is False
    assert result.compile_error is not None
    assert "EN" in result.compile_error and "Move" in result.compile_error


def test_standard_lad_box_behind_a_contact_compiles(tmp_path: Path) -> None:
    from plc_code.executor.ladder.compile import compile_ladder_block

    block = parse_scl_file(_sign_with_contact_before_move(tmp_path, safety=False))
    assert block.attributes.is_safety is False
    assert compile_ladder_block(block).success is True
