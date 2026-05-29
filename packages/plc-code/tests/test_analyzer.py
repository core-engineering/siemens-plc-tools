"""Tests for the call graph analyzer module."""

from plc_code.analyzer import (
    BlockNode,
    CallGraph,
    CallReference,
    CallType,
    build_call_graph,
    compute_graph_statistics,
    extract_calls,
    find_connected_components,
    generate_block_dependency_diagram,
    generate_mermaid_block,
    generate_mermaid_flowchart,
    get_callees,
    get_callers,
)
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.models import Block
from plc_code.parser.parser import SCLParser


def parse_scl_source(source: str) -> Block:
    """Helper to parse SCL source code."""
    tokens = tokenize_with_newlines(source)
    parser = SCLParser(tokens)
    return parser.parse()


class TestCallExtractor:
    """Tests for call extraction from SCL blocks."""

    def test_extract_simple_instance_call(self) -> None:
        """Test extraction of simple instance calls like #pumpControl()."""
        source = """
FUNCTION_BLOCK "ProcessUnit"
    VAR
        pumpControl : _.PumpControl;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION PumpControl process
            #pumpControl();
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        assert len(calls) == 1
        assert calls[0].caller == "ProcessUnit"
        assert calls[0].callee == "PumpControl"
        assert calls[0].instance_name == "pumpControl"
        assert calls[0].call_type == CallType.INSTANCE

    def test_extract_multiple_instance_calls(self) -> None:
        """Test extraction of multiple instance calls."""
        source = """
FUNCTION_BLOCK "ProcessUnit"
    VAR
        pumpControl : _.PumpControl;
        station : _.Station;
        remote : _.RemoteFaceT;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Process
            #pumpControl();
            #station();
            #remote();
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        assert len(calls) == 3
        callees = {c.callee for c in calls}
        assert callees == {"PumpControl", "Station", "RemoteFaceT"}

    def test_extract_instance_call_with_parameters(self) -> None:
        """Test extraction of instance calls with parameters."""
        source = """
FUNCTION_BLOCK "Test"
    VAR
        timer : _.PumpControl;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Timer call
            #timer(safetyState := 1,
                   hornAcknowledge := TRUE,
                   alarmState => #result);
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        assert len(calls) == 1
        assert calls[0].callee == "PumpControl"

    def test_extract_array_instance_call(self) -> None:
        """Test extraction of array instance calls like #arms[1]()."""
        source = """
FUNCTION_BLOCK "ProcessUnit"
    VAR
        arms : Array[1..9] of _.MotorStarter;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION MotorStarter1
            #arms[1](starterNumber := 1);
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        assert len(calls) == 1
        assert calls[0].callee == "MotorStarter"
        assert calls[0].instance_name == "arms"

    def test_ignore_system_functions(self) -> None:
        """Test that system functions are not extracted."""
        source = """
FUNCTION_BLOCK "Test"
    VAR
        converter : _.MyConverter;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Conversions
            #result := INT_TO_REAL(#input);
            #output := SQRT(#value);
            #converter();
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        # Only the user-defined converter should be extracted
        assert len(calls) == 1
        assert calls[0].callee == "MyConverter"

    def test_ignore_system_types(self) -> None:
        """Test that system types like TON_TIME are not extracted."""
        source = """
FUNCTION_BLOCK "Test"
    VAR
        timer : TON_TIME;
        userBlock : _.UserBlock;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Timer
            #timer(IN := TRUE, PT := T#1s);
            #userBlock();
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        # TON_TIME is a system type, only UserBlock should be extracted
        assert len(calls) == 1
        assert calls[0].callee == "UserBlock"

    def test_deduplicate_multiple_calls_to_same_target(self) -> None:
        """Test that multiple calls to same target are deduplicated."""
        source = """
FUNCTION_BLOCK "Test"
    VAR
        alarm : _.PumpControl;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Alarms
            #alarm();
            #alarm();
            #alarm();
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = parse_scl_source(source)
        calls = extract_calls(block)

        # Should only have one call reference despite multiple actual calls
        assert len(calls) == 1


class TestCallGraph:
    """Tests for CallGraph data structure."""

    def test_add_node(self) -> None:
        """Test adding nodes to graph."""
        graph = CallGraph()
        node = BlockNode(name="Test", block_type="FUNCTION_BLOCK")
        graph.add_node(node)

        assert "Test" in graph.nodes
        assert graph.node_count == 1

    def test_add_edge(self) -> None:
        """Test adding edges updates relationships."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="Caller", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="Callee", block_type="FUNCTION_BLOCK"))

        edge = CallReference(
            caller="Caller",
            callee="Callee",
            instance_name="callee",
            call_type=CallType.INSTANCE,
        )
        graph.add_edge(edge)

        assert "Callee" in graph.nodes["Caller"].calls
        assert "Caller" in graph.nodes["Callee"].called_by
        assert graph.edge_count == 1


class TestGraphBuilder:
    """Tests for building call graphs from blocks."""

    def test_build_graph_from_blocks(self) -> None:
        """Test building a call graph from multiple blocks."""
        process_unit_source = """
FUNCTION_BLOCK "ProcessUnit"
    VAR
        pumpControl : _.PumpControl;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION PumpControl
            #pumpControl();
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        pump_control_source = """
FUNCTION_BLOCK "PumpControl"
    { S7_Language := "SCL" }
    NETWORK
        REGION Process
            // No calls
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        blocks = [parse_scl_source(process_unit_source), parse_scl_source(pump_control_source)]
        graph = build_call_graph(blocks)

        assert graph.node_count == 2
        assert "ProcessUnit" in graph.nodes
        assert "PumpControl" in graph.nodes
        assert "PumpControl" in graph.nodes["ProcessUnit"].calls
        assert "ProcessUnit" in graph.nodes["PumpControl"].called_by

    def test_build_graph_excludes_type_blocks(self) -> None:
        """Test that TYPE blocks are not included in graph."""
        fb_source = """
FUNCTION_BLOCK "MyFB"
END_FUNCTION_BLOCK
"""
        # TYPE syntax in TIA Portal: TYPE\n    typeName : STRUCT
        type_source = """
TYPE
    MyType : STRUCT
        field : Int;
    END_STRUCT;
END_TYPE
"""
        blocks = [parse_scl_source(fb_source), parse_scl_source(type_source)]
        graph = build_call_graph(blocks)

        assert graph.node_count == 1
        assert "MyFB" in graph.nodes
        assert "MyType" not in graph.nodes

    def test_get_callers(self) -> None:
        """Test getting callers of a block."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="C", block_type="FUNCTION_BLOCK"))

        # A calls B, B calls C
        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))
        graph.add_edge(CallReference(caller="B", callee="C", instance_name="c", call_type=CallType.INSTANCE))

        # Direct callers of B
        callers = get_callers(graph, "B", max_depth=1)
        assert callers == {"A"}

        # Direct callers of C
        callers = get_callers(graph, "C", max_depth=1)
        assert callers == {"B"}

    def test_get_callees(self) -> None:
        """Test getting callees of a block."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="C", block_type="FUNCTION_BLOCK"))

        # A calls B and C
        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))
        graph.add_edge(CallReference(caller="A", callee="C", instance_name="c", call_type=CallType.INSTANCE))

        callees = get_callees(graph, "A", max_depth=1)
        assert callees == {"B", "C"}


class TestConnectedComponents:
    """Tests for finding connected components in call graphs."""

    def test_single_component(self) -> None:
        """Test graph with all nodes connected."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="C", block_type="FUNCTION_BLOCK"))

        # A -> B -> C (all connected)
        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))
        graph.add_edge(CallReference(caller="B", callee="C", instance_name="c", call_type=CallType.INSTANCE))

        components = find_connected_components(graph)

        assert len(components) == 1
        assert components[0].node_count == 3

    def test_multiple_components(self) -> None:
        """Test graph with disconnected components."""
        graph = CallGraph()
        # Component 1: A -> B
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))

        # Component 2: C -> D (disconnected)
        graph.add_node(BlockNode(name="C", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="D", block_type="FUNCTION_BLOCK"))
        graph.add_edge(CallReference(caller="C", callee="D", instance_name="d", call_type=CallType.INSTANCE))

        components = find_connected_components(graph)

        assert len(components) == 2
        # Components are sorted by size (largest first)
        assert all(c.node_count == 2 for c in components)

    def test_isolated_node(self) -> None:
        """Test that isolated nodes form their own component."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="Isolated", block_type="FUNCTION_BLOCK"))

        # Only A and B are connected
        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))

        components = find_connected_components(graph)

        assert len(components) == 2
        # Larger component first
        assert components[0].node_count == 2
        assert components[1].node_count == 1
        assert "Isolated" in components[1].nodes

    def test_component_root_candidates(self) -> None:
        """Test identification of root candidates in components."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="Root", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="Child", block_type="FUNCTION_BLOCK"))

        graph.add_edge(
            CallReference(caller="Root", callee="Child", instance_name="child", call_type=CallType.INSTANCE)
        )

        components = find_connected_components(graph)

        assert len(components) == 1
        # Root has no callers, so it's a root candidate
        assert "Root" in components[0].root_candidates
        assert "Child" not in components[0].root_candidates


class TestMermaidGeneration:
    """Tests for Mermaid diagram generation."""

    def test_generate_simple_flowchart(self) -> None:
        """Test generating a simple flowchart."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))

        mermaid = generate_mermaid_flowchart(graph, include_click_links=False)

        assert "flowchart TB" in mermaid
        assert 'A["A"]' in mermaid
        assert 'B["B"]' in mermaid
        assert "A --> B" in mermaid

    def test_generate_flowchart_with_direction(self) -> None:
        """Test flowchart with different direction."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))

        mermaid = generate_mermaid_flowchart(graph, direction="LR", include_click_links=False)

        assert "flowchart LR" in mermaid

    def test_generate_flowchart_with_click_links(self) -> None:
        """Test flowchart with clickable links."""
        graph = CallGraph()
        graph.add_node(
            BlockNode(name="TestBlock", block_type="FUNCTION_BLOCK", doc_path="blocks/TestBlock.md")
        )

        mermaid = generate_mermaid_flowchart(graph, include_click_links=True)

        # Links are absolute paths from site root, with .md replaced by /
        assert 'click TestBlock "/blocks/TestBlock/"' in mermaid

    def test_generate_flowchart_with_styling(self) -> None:
        """Test flowchart includes styling for block types."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="FB1", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="FC1", block_type="FUNCTION"))

        mermaid = generate_mermaid_flowchart(graph, include_click_links=False)

        assert "classDef fb" in mermaid
        assert "classDef fc" in mermaid
        assert "class FB1 fb" in mermaid
        assert "class FC1 fc" in mermaid

    def test_generate_mermaid_block_with_fences(self) -> None:
        """Test generating complete mermaid block with fences."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))

        mermaid = generate_mermaid_block(graph, include_click_links=False)

        assert mermaid.startswith("```mermaid\n")
        assert mermaid.endswith("\n```")

    def test_generate_block_dependency_diagram(self) -> None:
        """Test generating focused dependency diagram for a block."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="Caller", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="Target", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="Callee", block_type="FUNCTION_BLOCK"))

        graph.add_edge(
            CallReference(caller="Caller", callee="Target", instance_name="t", call_type=CallType.INSTANCE)
        )
        graph.add_edge(
            CallReference(caller="Target", callee="Callee", instance_name="c", call_type=CallType.INSTANCE)
        )

        mermaid = generate_block_dependency_diagram(graph, "Target", include_click_links=False)

        assert "subgraph Callers" in mermaid
        assert "subgraph Current" in mermaid
        assert "subgraph Callees" in mermaid
        assert "Caller --> Target" in mermaid
        assert "Target --> Callee" in mermaid


class TestGraphStatistics:
    """Tests for graph statistics computation."""

    def test_compute_statistics(self) -> None:
        """Test computing graph statistics."""
        graph = CallGraph()
        graph.add_node(BlockNode(name="A", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="B", block_type="FUNCTION_BLOCK"))
        graph.add_node(BlockNode(name="Isolated", block_type="FUNCTION_BLOCK"))

        graph.add_edge(CallReference(caller="A", callee="B", instance_name="b", call_type=CallType.INSTANCE))

        stats = compute_graph_statistics(graph)

        assert stats["node_count"] == 3
        assert stats["edge_count"] == 1
        assert stats["isolated_nodes"] == 1
        assert stats["max_out_degree"] == 1
        assert stats["max_in_degree"] == 1

    def test_empty_graph_statistics(self) -> None:
        """Test statistics for empty graph."""
        graph = CallGraph()
        stats = compute_graph_statistics(graph)

        assert stats["node_count"] == 0
        assert stats["edge_count"] == 0
