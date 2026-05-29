"""State machine detection and diagram generation.

This module provides tools for detecting state machine patterns in SCL and LADDER
function blocks, extracting states and transitions, and generating Mermaid
stateDiagram-v2 visualizations.

Examples
--------
>>> from plc_code.analyzer.state_machine import (
...     has_state_machine,
...     extract_state_machine,
...     generate_state_diagram_block,
... )
>>> from plc_code.parser import parse_scl_file
>>>
>>> block = parse_scl_file(path)
>>> if has_state_machine(block):
...     sm = extract_state_machine(block)
...     diagram = generate_state_diagram_block(sm)
"""

from plc_code.analyzer.state_machine.detector import (
    extract_state_machine,
    has_state_machine,
)
from plc_code.analyzer.state_machine.mermaid import (
    generate_state_diagram,
    generate_state_diagram_block,
)
from plc_code.analyzer.state_machine.models import (
    StateConstant,
    StateMachine,
    StateTransition,
)

__all__ = [
    # Models
    "StateConstant",
    "StateTransition",
    "StateMachine",
    # Detection
    "has_state_machine",
    "extract_state_machine",
    # Mermaid generation
    "generate_state_diagram",
    "generate_state_diagram_block",
]
