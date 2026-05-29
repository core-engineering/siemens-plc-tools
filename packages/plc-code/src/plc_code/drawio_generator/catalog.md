# IEC stencil — catalog

> **Status:** 4 chapters validated end-to-end (see example project). No new
> shapes added in Plan 2B-1. The analyzer now backs both wire extraction (via
> `analyzer_adapter.dependencies`) and pattern definition page emission (via
> `analyzer_adapter.state_machine`). Plan 2A's hardcoded alarm state machine has
> been replaced with a generic extracted SM.

## Plan 1 (MVP) shapes

| Function | Visual purpose | Required parameters |
|----------|----------------|---------------------|
| `cartouche_a3` | A3 title block (bottom-right) | id, title, drawing_number, sheet_number, drawn_by, approved_by, revision |
| `instrument_tag_widget` | Physical instrument tag (HS/PWR/XS/TSH/…) | id, position, tag_type, code, description |
| `plc_digital_input_widget` | PLC digital input (address + signal name) | id, position, address, signal_name |
| `plc_tag_flag` | PLC tag flag (in/out banner) | id, position, path, direction |
| `acknowledge_alarm_compact` | Compact MotorStarter pattern block | id, position, instance_name |
| `and_gate` | AND gate (IEC `&`) | id, position, input_count |
| `or_gate` | OR gate (IEC `≥1`) | id, position, input_count |
| `sticky_comment` | Green sticky note for design intent | id, position, text |

## Plan 2A shapes

### Timers

| Function | Visual purpose | Required parameters |
|----------|----------------|---------------------|
| `ton_timer` | IEC TON on-delay timer block | id, position, preset_ms |
| `tof_timer` | IEC TOF off-delay timer block | id, position, preset_ms |
| `tp_timer` | IEC TP pulse timer block | id, position, preset_ms |

### Logic primitives

| Function | Visual purpose | Required parameters |
|----------|----------------|---------------------|
| `not_gate` | IEC NOT gate (logic-1 with output inversion circle) | id, position |
| `latch_sr` | IEC S/R latch (Set dominant) | id, position |
| `edge_rising` | IEC R_TRIG rising-edge detector | id, position |
| `edge_falling` | IEC F_TRIG falling-edge detector | id, position |
| `comparator` | Generic comparator block (`==`, `!=`, `>`, `<`, `>=`, `<=`) | id, position, op |

### State machine

| Function | Visual purpose | Required parameters |
|----------|----------------|---------------------|
| `state_bubble` | State bubble inside a `<<StateMachine>>` container | id, position, name; optional: entry, do, exit |
| `state_machine_container` | Green `<<StateMachine>>` bounding box for an SM diagram | id, position, size, label |
| `state_transition` | Directed transition arrow between two state bubbles (edge cell — not dispatched via `_SHAPE_DISPATCH`; emitted directly by `state_machine_page`) | id, source_id, target_id, condition |

### Annotations and special blocks

| Function | Visual purpose | Required parameters |
|----------|----------------|---------------------|
| `auto_acknowledge_annotation` | Yellow `<<AutoAcknowledge>>` sticky note next to an FB instance that auto-resets without operator action | id, position, fb_instance |
| `black_box` | Opaque FB block for complex/external FBs shown with exposed I/O only | id, position, fb_type, instance_name, exposed_io |

### Cross-page references

| Function | Visual purpose | Required parameters |
|----------|----------------|---------------------|
| `cross_page_ref_out` | Cross-page exit marker pointing to another sheet (e.g. `→ L1 (page 042)`) | id, position, label, target_page |
| `cross_page_ref_in` | Cross-page entry marker arriving from another sheet (e.g. `L1 (from page 012) →`) | id, position, label, source_page |

**Still deferred (Plan 2B / 3):** NAND, NOR, XOR, Selector pattern block,
inline parameter annotations, back-matter index cells.
