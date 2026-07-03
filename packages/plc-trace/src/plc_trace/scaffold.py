"""UDT-first SCL scaffold generator for the on-PLC trace recorder.

Given a flat, scalar-fields UDT (a ``TYPE ... END_TYPE`` block), this module
generates the three SCL sources needed to record a cycle-granular ring (or
one-shot) trace of that UDT's fields:

- the trace UDT itself (``control``/``status`` housekeeping plus one ring
  array per source field, all sized ``depth``);
- an instance DATA_BLOCK for that UDT;
- the recorder FUNCTION, driven once per plant cycle from the cyclic
  regulation OB, that fills the ring arrays.

The three templates rendered here are normative: downstream golden tests
freeze their exact text. Keep edits in sync with
``packages/plc-trace/tests/test_scaffold.py``.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.parser import parse_scl_file

#: Scalar SCL data types the scaffold generator accepts as UDT fields.
ALLOWED_TYPES = {"Bool", "Int", "DInt", "UDInt", "Real", "LReal"}

#: Default fill value written into the FC's FILL SAMPLE placeholder, by type.
_DEFAULT_FILL_VALUES = {
    "Bool": "FALSE",
    "Int": "0",
    "DInt": "0",
    "UDInt": "0",
    "Real": "0.0",
    "LReal": "0.0",
}


class ScaffoldError(ValueError):
    """Raised when a UDT cannot be scaffolded into a trace recorder."""


def _extract_fields(udt_path: Path) -> tuple[str, list[tuple[str, str]]]:
    """Parse a UDT source file and return its name and its scalar fields.

    Parameters
    ----------
    udt_path : Path
        Path to the ``.s7dcl`` file holding the ``TYPE ... END_TYPE`` block.

    Returns
    -------
    tuple[str, list[tuple[str, str]]]
        The UDT's own type name (e.g. ``typeDemoTrace``) and its ordered
        ``(field_name, data_type)`` pairs, in declaration order.

    Raises
    ------
    ScaffoldError
        If the file does not contain a ``TYPE`` block, or a field's type is
        not one of the flat scalar types in ``ALLOWED_TYPES`` (nested UDTs,
        arrays, strings, ...).
    """
    block = parse_scl_file(udt_path)
    if block.block_type != "TYPE" or block.user_data_type is None:
        raise ScaffoldError(f"{udt_path} does not contain a TYPE (UDT) block")

    fields: list[tuple[str, str]] = []
    for struct_field in block.user_data_type.fields:
        if struct_field.data_type not in ALLOWED_TYPES:
            raise ScaffoldError(
                f"field '{struct_field.name}' has type '{struct_field.data_type}' — "
                "not supported in v1, flatten your UDT to scalar fields "
                "(Bool, Int, DInt, UDInt, Real, LReal)"
            )
        fields.append((struct_field.name, struct_field.data_type))

    return block.user_data_type.name, fields


def _render_type(name: str, depth: int, fields: list[tuple[str, str]]) -> str:
    """Render the trace UDT (``type<name>``) SCL source.

    Parameters
    ----------
    name : str
        Trace instance name (e.g. ``TraceData``); the type itself is named
        ``type<name>``.
    depth : int
        Ring depth; each array is sized ``Array[0..depth-1]``.
    fields : list[tuple[str, str]]
        Ordered ``(field_name, data_type)`` pairs copied from the source UDT.

    Returns
    -------
    str
        The ``type<name>.s7dcl`` file text (LF-terminated).
    """
    bound = depth - 1
    field_lines = "\n".join(
        f"        {field_name} : Array[0..{bound}] of {data_type};" for field_name, data_type in fields
    )
    return f"""TYPE
    type{name} : STRUCT
        control : STRUCT
            start : Bool;        // rising edge = start (resets indices); low level = stop
            mode : Int;          // 0 = ring (default), 1 = one-shot
            decimation : UDInt;  // sample every k-th cycle; 0/1 = every cycle; writable mid-run
        END_STRUCT;
        status : STRUCT
            recording : Bool;
            wrapped : Bool;
            writeIdx : DInt;
            sampleCount : DInt;
            cycleCounter : UDInt;
            cycleTimeMs : Real;
            depth : DInt;
            startMem : Bool;     // internal FC edge memory
            decCounter : UDInt;  // internal decimation countdown
        END_STRUCT;
        sampleCycles : Array[0..{bound}] of UDInt;
{field_lines}
    END_STRUCT;
END_TYPE
"""


def _render_db(name: str, depth: int) -> str:
    """Render the instance DATA_BLOCK SCL source.

    Parameters
    ----------
    name : str
        Trace instance name; the DB is ``<name>`` typed as ``type<name>``.
    depth : int
        Ring depth, written into ``status.depth`` as the initial value.

    Returns
    -------
    str
        The ``<name>.s7dcl`` file text (LF-terminated).
    """
    return f"""{{
    S7_Optimized := "TRUE";
    S7_StandardRetain := "FALSE";
    S7_Version := "0.1"
}}
DATA_BLOCK {name} : type{name}
    status.depth := {depth};
END_DATA_BLOCK
"""


def _render_fc(name: str, udt_name: str, fields: list[tuple[str, str]]) -> str:
    """Render the recorder FUNCTION SCL source.

    Parameters
    ----------
    name : str
        Trace instance name; the FC is ``<name>Recorder``.
    udt_name : str
        The source UDT's own type name (e.g. ``typeDemoTrace``), used only in
        the FILL SAMPLE region's comment.
    fields : list[tuple[str, str]]
        Ordered ``(field_name, data_type)`` pairs copied from the source UDT;
        each gets a placeholder assignment in the FILL SAMPLE region.

    Returns
    -------
    str
        The ``<name>Recorder.s7dcl`` file text (LF-terminated).
    """
    fill_lines = "\n".join(
        f"                    #trace.{field_name}[#idx] := "
        f"{_DEFAULT_FILL_VALUES[data_type]}; // TODO: assign your signal"
        for field_name, data_type in fields
    )
    return f"""{{
    S7_EditorMode := "SCL";
    S7_Optimized := "TRUE";
    S7_Version := "0.1"
}}
FUNCTION "{name}Recorder" : Void
    VAR_INPUT
        timeCycle : Real;   // plant cycle time in SECONDS
    END_VAR
    VAR_IN_OUT
        trace : _.type{name};
    END_VAR
    VAR_TEMP
        idx : DInt;
        k : UDInt;
    END_VAR

    {{ S7_Language := "SCL" }}
    NETWORK
        // DESCRIPTION
        // Generated by plc-trace scaffold - cycle-granular trace recorder.
        // Ring or one-shot buffer driven over OPC UA via trace.control;
        // complete ONLY the FILL SAMPLE region below, then call this FC from
        // the cyclic regulation OB: "{name}Recorder"(timeCycle := #timeCycle, trace := "{name}");
        // END_DESCRIPTION
        //
        // TAG
        // TRACE
        // END_TAG

        REGION Start edge and stop level
            IF #trace.control.start AND NOT #trace.status.startMem THEN
                #trace.status.recording := TRUE;
                #trace.status.wrapped := FALSE;
                #trace.status.writeIdx := 0;
                #trace.status.sampleCount := 0;
                #trace.status.cycleCounter := 0;
                #trace.status.cycleTimeMs := #timeCycle * 1000.0;
                #trace.status.decCounter := 1;
            END_IF;
            IF NOT #trace.control.start THEN
                #trace.status.recording := FALSE;
            END_IF;
            #trace.status.startMem := #trace.control.start;
        END_REGION

        REGION Sampling
            IF #trace.status.recording THEN
                #trace.status.cycleCounter := #trace.status.cycleCounter + 1;
                IF #trace.status.decCounter <= 1 THEN
                    #idx := #trace.status.writeIdx;
                    #trace.sampleCycles[#idx] := #trace.status.cycleCounter;
                    // --- FILL SAMPLE (project-specific): one assignment per {udt_name} field ---
{fill_lines}
                    // --- END FILL SAMPLE ---
                    #trace.status.writeIdx := #trace.status.writeIdx + 1;
                    #trace.status.sampleCount := #trace.status.sampleCount + 1;
                    IF #trace.status.writeIdx >= #trace.status.depth THEN
                        IF #trace.control.mode = 1 THEN
                            #trace.status.recording := FALSE;
                        ELSE
                            #trace.status.writeIdx := 0;
                            #trace.status.wrapped := TRUE;
                        END_IF;
                    END_IF;
                    #k := #trace.control.decimation;
                    IF #k < 1 THEN
                        #k := 1;
                    END_IF;
                    #trace.status.decCounter := #k;
                ELSE
                    #trace.status.decCounter := #trace.status.decCounter - 1;
                END_IF;
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION
"""


def generate_trace_blocks(udt_path: Path, depth: int, name: str) -> dict[str, str]:
    """Generate the three trace-recorder SCL sources for a source UDT.

    Parameters
    ----------
    udt_path : Path
        Path to the source UDT's ``.s7dcl`` file (a ``TYPE ... END_TYPE``
        block with only scalar fields).
    depth : int
        Ring depth (number of samples held per field).
    name : str
        Trace instance name (e.g. ``TraceData``). Drives the generated type
        name (``type<name>``), DB name, and FC name (``<name>Recorder``).

    Returns
    -------
    dict[str, str]
        ``{"type": ..., "db": ..., "fc": ...}`` mapping to the three
        generated file texts (LF-terminated; the CLI writer converts to
        CRLF + BOM on disk).

    Raises
    ------
    ScaffoldError
        If the UDT cannot be flattened to scalar fields (see
        ``_extract_fields``).
    """
    udt_name, fields = _extract_fields(Path(udt_path))
    return {
        "type": _render_type(name, depth, fields),
        "db": _render_db(name, depth),
        "fc": _render_fc(name, udt_name, fields),
    }


def _write_scl(path: Path, text: str) -> None:
    """Write an SCL source file with the TIA Portal export byte conventions.

    Parameters
    ----------
    path : Path
        Destination file path.
    text : str
        File content, LF-terminated (as returned by ``generate_trace_blocks``).

    Notes
    -----
    TIA Portal SCL exports are UTF-8 with a BOM and CRLF line endings; the
    generated file is written with a trailing newline.
    """
    body = text.replace("\r\n", "\n")
    if not body.endswith("\n"):
        body += "\n"
    crlf_body = body.replace("\n", "\r\n")
    path.write_bytes(b"\xef\xbb\xbf" + crlf_body.encode("utf-8"))
