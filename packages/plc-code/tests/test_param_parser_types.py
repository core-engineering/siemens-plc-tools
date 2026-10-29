"""Self-closing UDT members of a parameter XML expand from the ``.s7dcl`` type sources."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.exporter.param_parser import parse_parameter_xml

LIMIT = """TYPE
    typeLimit : STRUCT
        "id" : Int := 3;
        low : Real;
        band : Struct
            lo : Int := 1;
            hi : Int;
        END_STRUCT;
        gains : Array[0..2] of Real;
        zones : Array[1..2] of _.typeZone;
        label : String[16] := 'none';
        names : Array[0..1] of String[8];
        grid : Array[0..1, 2..3] of Bool;
    END_STRUCT;
END_TYPE
"""

ZONE = """TYPE
    typeZone : STRUCT
        x : DInt := 7;
    END_STRUCT;
END_TYPE
"""

XML = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Blocks.InstanceDB ID="0">
    <AttributeList>
      <Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
        <Section Name="Static">
          <Member Name="limit" Datatype="&quot;typeLimit&quot;" />
        </Section>
      </Sections></Interface>
      <Name>Params</Name>
    </AttributeList>
  </SW.Blocks.InstanceDB>
</Document>
"""


def test_self_closing_udt_member_expands_every_member(tmp_path: Path) -> None:
    types = tmp_path / "types"
    write_s7dcl(types, "typeLimit.s7dcl", LIMIT)
    write_s7dcl(types, "typeZone.s7dcl", ZONE)
    xml = tmp_path / "Params.xml"
    xml.write_text(XML, encoding="utf-8")

    entries = {e.qualified_path: (e.datatype, e.value) for e in parse_parameter_xml(xml, types_dir=types)}

    assert entries == {
        "Params.limit.id": ("Int", "3"),
        "Params.limit.low": ("Real", ""),
        "Params.limit.band.lo": ("Int", "1"),
        "Params.limit.band.hi": ("Int", ""),
        "Params.limit.gains[0]": ("Real", ""),
        "Params.limit.gains[1]": ("Real", ""),
        "Params.limit.gains[2]": ("Real", ""),
        "Params.limit.zones[1].x": ("DInt", "7"),
        "Params.limit.zones[2].x": ("DInt", "7"),
        "Params.limit.label": ("String[16]", "'none'"),
        "Params.limit.names[0]": ("String[8]", ""),
        "Params.limit.names[1]": ("String[8]", ""),
        "Params.limit.grid[0,2]": ("Bool", ""),
        "Params.limit.grid[0,3]": ("Bool", ""),
        "Params.limit.grid[1,2]": ("Bool", ""),
        "Params.limit.grid[1,3]": ("Bool", ""),
    }
