# drawio_generator

Generate the Control Logic deliverable (.drawio files) from a TIA Portal
SCL export and a hand-written `doc-map.yaml`.

## Usage

    plc code drawio \
      --doc-map <project>/doc-map.yaml \
      --xml-tags "<project>/tags" \
      --scl "<project>/Program blocks" \
      --out <project>/chapters

Produces one `.drawio` per chapter declared in the doc-map, plus a
`front-matter.drawio` when the doc-map declares any `pattern`-style FB
with a `definition_page`.

### CLI options

| Option | Description |
|--------|-------------|
| `--doc-map PATH` | Path to the `doc-map.yaml` file (required) |
| `--xml-tags DIR` | Directory of S7-1500 XML tag exports (optional) |
| `--scl DIR` | Root directory of SCL `.s7dcl` sources (optional) |
| `--out DIR` | Output directory for `.drawio` files (required) |
| `--chapter NAME` | Generate only the named chapter (default: all chapters) |

When `--scl` is provided:
- The resolver indexes every FB instance declaration found in `*.s7dcl` files,
  enabling doc-map entries that reference FB instance names (e.g. `panelHighTempAlarm`)
  to resolve to `kind="fb_instance"` with the correct `fb_type` and `parent_block`.
- The CLI extracts a dependency graph via `analyzer.logic_dependency` for each
  chapter's `source_blocks` and passes it to `page_builder.build_sheet` via
  `analyzer_adapter.dependencies`, so wires between blocks are emitted automatically.
- Wire generation requires **both** `--scl` AND that I/O tags appear on the page.
  I/O tags resolve only for standard prefixes: `DI_`, `SDI_`, `DO_`, `SDO_`, `AI_`,
  `SAI_`. Tags with non-standard prefixes (e.g. `CUSTOM_FACE_C_*`) are filtered out
  and produce no wires. See `analyzer/logic_dependency/tag_parser.py: TAG_PREFIXES`.

## analyzer_adapter

Adapters that bridge plc-tools analyzer outputs to drawio_generator IR shapes.

- `state_machine.py` — converts `analyzer.state_machine.StateMachine` → Protocol lists consumed by `state_machine_page.build_state_machine_sheet`.
- `dependencies.py` — converts `analyzer.logic_dependency` chains → flat `dict[target_id, list[source_id]]` for `wiring.build_wires_for_sheet`.

The CLI uses these adapters automatically when `--scl` is provided.

## Modules

- `models.py`           — Render IR (`Sheet`, `Block`, `Wire`, `Annotation`, `Cartouche`)
- `iec_stencil.py`      — Shape catalog (mxCell XML producers); see `catalog.md`
- `page_builder.py`     — Doc-map page → `Sheet`; dispatches on FB rendering mode
                          (`inline` / `pattern` / `black-box`) and emits
                          `AutoAcknowledge` annotations when `annotation: auto_acknowledge`
                          is set in the doc-map block ref
- `wiring.py`           — Derive `Wire` objects from a flat dependency dict
                          (`dict[target_id, list[source_id]]`); cross-sheet
                          dependencies (source or target not on current sheet) are
                          silently skipped
- `state_machine_page.py` — Build SM definition pages for the front-matter pattern pages;
                           given a list of state/transition protocol objects, produces a
                           complete `Sheet` with a `<<StateMachine>>` container, one
                           `state_bubble` per state, and transition wires
- `xml_writer.py`       — `Sheet` list → `.drawio` (mxGraph XML); dispatches blocks
                          through `_SHAPE_DISPATCH` and renders wires / annotations
                          separately

## FB rendering modes

The `fb_rendering` section of `doc-map.yaml` controls how resolved FB instances appear:

| `style` | Shape emitted | Notes |
|---------|--------------|-------|
| `pattern` | `acknowledge_alarm_compact` (or generic compact) | Compact pattern block referencing the definition page |
| `black-box` | `black_box` | Opaque block showing only `expose:` I/O list |
| `inline` (default) | Placeholder `instrument_tag_widget` | Full inline expansion deferred to Plan 2B |

## FB instance resolution

`plc_code.docmap.resolver.Resolver` resolves identifiers in two passes:

1. **Instrument tags** — S7-1500 XML exports (unchanged from Plan 1)
2. **FB instances** — when `scl_dir` is provided, the resolver parses every
   `*.s7dcl` file and indexes `VAR` block declarations, supporting both the
   quoted-string form (`"TypeName"`) and the TIA library-reference form
   (`_.TypeName`).  Instrument tags take precedence if both match.

## See also

- Shape catalog: `catalog.md`
- Schema and resolution: `plc_code.docmap`
