"""Documentation generation pipeline.

This module provides the main pipeline for batch processing SCL files
and generating documentation output.
"""

from dataclasses import dataclass, field
from pathlib import Path

from plc_code.analyzer import (
    BlockDBDependencies,
    CallGraph,
    ConnectedComponent,
    TypeComponent,
    TypeGraph,
    build_call_graph,
    build_db_crossref,
    build_type_graph,
    compute_graph_statistics,
    compute_type_graph_statistics,
    extract_all_type_dependencies,
    extract_db_references,
    extract_state_machine,
    find_connected_components,
    find_type_components,
    generate_audit_markdown,
    generate_crossref_index,
    generate_db_page,
    generate_legend_block,
    generate_mermaid_block,
    generate_type_component_flowchart,
    has_state_machine,
    run_global_variable_audit,
)
from plc_code.analyzer.quality import (
    AnalysisRunner,
    BlockAnalysisResult,
    MarkdownReporter,
    ProjectAnalysisResult,
)
from plc_code.extractor.header import extract_header
from plc_code.extractor.interface import extract_interface
from plc_code.generator.markdown import generate_markdown
from plc_code.parser.models import Block
from plc_code.parser.parser import parse_resource_file, parse_scl_file
from plc_code.project.config import ProjectConfig
from plc_code.project.discovery import BlockFile, discover_blocks, group_by_category
from plc_code.testing import (
    BlockTestResult,
    ProjectTestResult,
    TestReporter,
    TestRunner,
    build_test_registry,
)


@dataclass
class ProcessingResult:
    """Result of processing a single block.

    Attributes
    ----------
    block_file : BlockFile
        The source block file.
    success : bool
        Whether processing succeeded.
    output_path : Path | None
        Path to generated markdown file.
    error : str | None
        Error message if processing failed.
    block_type : str
        Type of block (FUNCTION_BLOCK, FUNCTION, TYPE).
    title : str
        Block title for navigation.
    analysis_result : BlockAnalysisResult | None
        Quality analysis result for the block.
    test_result : BlockTestResult | None
        Unit test result for the block.
    """

    block_file: BlockFile
    success: bool = True
    output_path: Path | None = None
    error: str | None = None
    block_type: str = ""
    title: str = ""
    analysis_result: BlockAnalysisResult | None = None
    test_result: BlockTestResult | None = None


@dataclass
class PipelineStats:
    """Statistics from pipeline execution.

    Attributes
    ----------
    total : int
        Total files processed.
    successful : int
        Successfully processed files.
    failed : int
        Failed files.
    by_category : dict[str, int]
        Count by category.
    by_type : dict[str, int]
        Count by block type.
    """

    total: int = 0
    successful: int = 0
    failed: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)


class DocumentationPipeline:
    """Pipeline for generating documentation from SCL exports.

    Parameters
    ----------
    config : ProjectConfig
        Project configuration.

    Examples
    --------
    >>> config = ProjectConfig.from_source(Path("./exports"))
    >>> pipeline = DocumentationPipeline(config)
    >>> results = pipeline.run()
    >>> print(f"Generated {len([r for r in results if r.success])} docs")
    """

    def __init__(self, config: ProjectConfig) -> None:
        """Initialize the pipeline.

        Parameters
        ----------
        config : ProjectConfig
            Project configuration.
        """
        self.config = config
        self.results: list[ProcessingResult] = []
        self.stats = PipelineStats()
        self.call_graph: CallGraph | None = None
        self.type_graph: TypeGraph | None = None
        self._parsed_blocks: list[Block] = []
        self._parsed_type_blocks: list[Block] = []
        self._db_dependencies: list[BlockDBDependencies] = []
        self._analysis_runner = AnalysisRunner()
        self._markdown_reporter = MarkdownReporter()
        self._test_runner = TestRunner(test_dirs=config.test_dirs)
        self._test_reporter = TestReporter()
        self._test_registry: dict[str, Path] = {}
        self._test_results: dict[str, BlockTestResult] = {}
        self._copied_external_sections: list[tuple[str, str]] = []
        self._efat_section: tuple[str, str] | None = None

    def run(self) -> list[ProcessingResult]:
        """Execute the documentation pipeline.

        Returns
        -------
        list[ProcessingResult]
            Results for all processed files.
        """
        # Discover blocks
        blocks = discover_blocks(
            self.config.source_dir,
            self.config.include_patterns,
            self.config.exclude_patterns,
        )

        # Ensure output directory exists
        self.config.output.output_dir.mkdir(parents=True, exist_ok=True)

        # Build type registry (first pass to determine output paths for all types)
        type_registry = self._build_type_registry(blocks)

        # Build category registry
        categories = self._build_category_registry(blocks)

        # Build test registry and run tests (if configured)
        if self.config.run_tests:
            self._build_and_run_tests([b.name for b in blocks])

        # Process each block (also collects parsed blocks for graphs)
        self.results = []
        self._parsed_blocks = []
        self._parsed_type_blocks = []
        self._db_dependencies = []
        for block_file in blocks:
            result = self._process_block(block_file, type_registry)
            self.results.append(result)
            self._update_stats(result)

        # Build doc path registry from results (after we know actual block types)
        doc_paths = self._build_doc_path_registry_from_results()

        # Build call graph from parsed blocks
        self.call_graph = build_call_graph(
            self._parsed_blocks,
            doc_paths=doc_paths,
            categories=categories,
        )

        # Generate call graph pages
        self._generate_call_graph_pages()

        # Build type dependency graph from parsed TYPE blocks
        type_deps = extract_all_type_dependencies(self._parsed_type_blocks)
        type_doc_paths = self._build_type_doc_path_registry()
        self.type_graph = build_type_graph(type_deps, type_doc_paths)

        # Generate type graph pages
        self._generate_type_graph_pages()

        # Generate quality analysis pages
        self._generate_quality_pages()

        # Generate test documentation pages (if tests were run)
        if self.config.run_tests:
            self._generate_test_pages()

        # Generate global data cross-reference pages
        self._generate_db_crossref_pages()

        # Generate index pages if configured
        if self.config.output.create_index:
            self._generate_index_pages()

        # Copy external documentation (audits, etc.)
        self._copied_external_sections = []
        if self.config.external_docs:
            self._copy_external_docs()

        # Generate EFAT integration-test index (if configured)
        self._efat_section = None
        if self.config.efat.test_dir is not None:
            self._generate_efat_index()

        # Generate root index.md (always — single source of truth)
        self._generate_root_index()

        # Generate mkdocs nav if configured
        if self.config.output.create_mkdocs_nav:
            self._generate_mkdocs_nav()

        return self.results

    def _build_type_registry(self, blocks: list[BlockFile]) -> dict[str, str]:
        """Build a registry mapping type names to their output paths.

        Parameters
        ----------
        blocks : list[BlockFile]
            All discovered blocks.

        Returns
        -------
        dict[str, str]
            Mapping of type name to relative path from docs root.
        """
        registry: dict[str, str] = {}

        for block_file in blocks:
            # Only register types (blocks starting with "type")
            if not block_file.name.startswith("type"):
                continue

            # Compute the output path
            output_path = self._get_output_path(block_file, "TYPE")
            relative_path = output_path.relative_to(self.config.output.output_dir)

            # Use forward slashes for consistency
            registry[block_file.name] = str(relative_path).replace("\\", "/")

        return registry

    def _build_doc_path_registry_from_results(self) -> dict[str, str]:
        """Build a registry mapping block names to their documentation paths.

        Uses processing results which have the actual block types and output paths.

        Returns
        -------
        dict[str, str]
            Mapping of block name to relative doc path from docs root.
        """
        registry: dict[str, str] = {}

        for result in self.results:
            # Skip types and failed results
            if not result.success or not result.output_path:
                continue
            if result.block_type == "TYPE":
                continue

            relative_path = result.output_path.relative_to(self.config.output.output_dir)
            registry[result.block_file.name] = str(relative_path).replace("\\", "/")

        return registry

    def _build_type_doc_path_registry(self) -> dict[str, str]:
        """Build a registry mapping type names to their documentation paths.

        Uses processing results which have the actual output paths.

        Returns
        -------
        dict[str, str]
            Mapping of type name to relative doc path from docs root.
        """
        registry: dict[str, str] = {}

        for result in self.results:
            # Only include types
            if not result.success or not result.output_path:
                continue
            if result.block_type != "TYPE":
                continue

            relative_path = result.output_path.relative_to(self.config.output.output_dir)
            registry[result.block_file.name] = str(relative_path).replace("\\", "/")

        return registry

    def _build_category_registry(self, blocks: list[BlockFile]) -> dict[str, tuple[str, str]]:
        """Build a registry mapping block names to their categories.

        Parameters
        ----------
        blocks : list[BlockFile]
            All discovered blocks.

        Returns
        -------
        dict[str, tuple[str, str]]
            Mapping of block name to (category, subcategory).
        """
        registry: dict[str, tuple[str, str]] = {}

        for block_file in blocks:
            category = block_file.category or ""
            subcategory = block_file.subcategory or ""
            registry[block_file.name] = (category, subcategory)

        return registry

    def _process_block(self, block_file: BlockFile, type_registry: dict[str, str]) -> ProcessingResult:
        """Process a single block file.

        Parameters
        ----------
        block_file : BlockFile
            The block file to process.
        type_registry : dict[str, str]
            Mapping of type names to their output paths.

        Returns
        -------
        ProcessingResult
            The processing result.
        """
        try:
            # Parse the block
            block = parse_scl_file(block_file.source_path)

            # Store for call graph analysis (FB, FC, and OB)
            if block.block_type in ("FUNCTION_BLOCK", "FUNCTION", "ORGANIZATION_BLOCK"):
                self._parsed_blocks.append(block)

            # Store for type graph analysis (only TYPE)
            if block.block_type == "TYPE":
                self._parsed_type_blocks.append(block)

            # Parse resource file if available
            resource = None
            if block_file.resource_path:
                resource = parse_resource_file(block_file.resource_path)

            # Extract documentation
            header = extract_header(block, resource)
            interface = extract_interface(block, resource)

            # Determine output path
            output_path = self._get_output_path(block_file, block.block_type)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Compute current doc path (relative to output dir, with forward slashes)
            current_doc_path = str(output_path.relative_to(self.config.output.output_dir)).replace("\\", "/")

            # Read source code for inclusion in documentation
            source_code = block_file.source_path.read_text(encoding="utf-8-sig")

            # Detect and extract state machine if present
            state_machine = None
            if has_state_machine(block):
                state_machine = extract_state_machine(block)

            # Run quality analysis
            analysis_result = self._analysis_runner.analyze_block(block)

            # Get test result for this block (if available)
            test_result = self._test_results.get(block.name)

            # Extract global DB dependencies (only for FB, FC, OB)
            db_dependencies = None
            if block.block_type in ("FUNCTION_BLOCK", "FUNCTION", "ORGANIZATION_BLOCK"):
                db_dependencies = extract_db_references(block)
                # Store for cross-reference generation
                if db_dependencies and db_dependencies.references:
                    self._db_dependencies.append(db_dependencies)

            # Generate markdown with type registry for correct cross-references
            markdown = generate_markdown(
                header,
                interface,
                self.config.markdown,
                type_registry,
                current_doc_path,
                source_code,
                state_machine,
                analysis_result,
                test_result,
                db_dependencies,
            )

            # Write file
            output_path.write_text(markdown, encoding="utf-8")

            return ProcessingResult(
                block_file=block_file,
                success=True,
                output_path=output_path,
                block_type=block.block_type,
                title=header.title or block.name,
                analysis_result=analysis_result,
                test_result=test_result,
            )

        except Exception as e:
            return ProcessingResult(
                block_file=block_file,
                success=False,
                error=str(e),
            )

    def _get_output_path(self, block_file: BlockFile, block_type: str) -> Path:
        """Get the output path for a block.

        Parameters
        ----------
        block_file : BlockFile
            The block file.
        block_type : str
            The block type.

        Returns
        -------
        Path
            The output path for the markdown file.
        """
        base_dir = self.config.output.output_dir
        subdir = self.config.output.get_subdir(block_type)

        if self.config.preserve_hierarchy and block_file.category:
            # Create hierarchy from category and subcategory
            # Combine category and subcategory into full path
            full_category = block_file.category
            if block_file.subcategory:
                full_category = f"{full_category} / {block_file.subcategory}"
            # Convert to path-safe format (keep spaces for readability)
            category_dir = full_category.replace(" / ", "/")
            return base_dir / subdir / category_dir / f"{block_file.name}.md"
        else:
            return base_dir / subdir / f"{block_file.name}.md"

    def _update_stats(self, result: ProcessingResult) -> None:
        """Update pipeline statistics.

        Parameters
        ----------
        result : ProcessingResult
            The processing result.
        """
        self.stats.total += 1

        if result.success:
            self.stats.successful += 1
        else:
            self.stats.failed += 1

        # Update category counts
        category = result.block_file.category or "Uncategorized"
        self.stats.by_category[category] = self.stats.by_category.get(category, 0) + 1

        # Update type counts
        if result.block_type:
            self.stats.by_type[result.block_type] = self.stats.by_type.get(result.block_type, 0) + 1

    def _generate_index_pages(self) -> None:
        """Generate index pages for each category."""
        successful = [r for r in self.results if r.success]

        # Group by output subdirectory
        by_subdir: dict[str, list[ProcessingResult]] = {}
        for result in successful:
            if result.output_path:
                # Get the subdir (blocks, types, functions)
                relative = result.output_path.relative_to(self.config.output.output_dir)
                subdir = relative.parts[0] if relative.parts else "other"

                if subdir not in by_subdir:
                    by_subdir[subdir] = []
                by_subdir[subdir].append(result)

        # Generate index for each subdir
        for subdir, results in by_subdir.items():
            self._generate_category_index(subdir, results)

    def _generate_category_index(self, subdir: str, results: list[ProcessingResult]) -> None:
        """Generate an index page for a category.

        Parameters
        ----------
        subdir : str
            The subdirectory name.
        results : list[ProcessingResult]
            Results in this category.
        """
        # Map subdir to display name
        titles = {
            "plc-blocks": "PLC Blocks",
            "types": "Data Types",
            "data-blocks": "Data Blocks",
        }
        title = titles.get(subdir, subdir.title())

        lines = [
            f"# {title}",
            "",
        ]

        # Group by category within subdir
        grouped = group_by_category([r.block_file for r in results])

        # Map results by block name for easy lookup
        result_map = {r.block_file.name: r for r in results}

        for category, blocks in sorted(grouped.items()):
            if category:
                lines.append(f"## {category}")
                lines.append("")

            lines.append("| Name | Description |")
            lines.append("|------|-------------|")

            for block in sorted(blocks, key=lambda b: b.name):
                result = result_map.get(block.name)
                if result and result.output_path:
                    relative = result.output_path.relative_to(self.config.output.output_dir / subdir)
                    link = f"[{result.title}]({relative})"
                    lines.append(f"| {link} | |")

            lines.append("")

        # Write index file
        index_path = self.config.output.output_dir / subdir / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("\n".join(lines), encoding="utf-8")

    def _generate_mkdocs_nav(self) -> None:
        """Generate mkdocs.yml navigation structure."""
        successful = [r for r in self.results if r.success]

        nav_lines = [
            "# Auto-generated navigation for SCL documentation",
            "",
            "nav:",
            "  - Home: index.md",
        ]

        # Group results by output subdir
        by_subdir: dict[str, list[ProcessingResult]] = {
            "plc-blocks": [],
            "types": [],
            "data-blocks": [],
        }

        for result in successful:
            if not result.output_path:
                continue

            relative = result.output_path.relative_to(self.config.output.output_dir)
            subdir = relative.parts[0] if relative.parts else "other"

            if subdir in by_subdir:
                by_subdir[subdir].append(result)

        # Generate nav sections
        section_titles = {
            "plc-blocks": "PLC Blocks",
            "types": "Data Types",
            "data-blocks": "Data Blocks",
        }

        for section_key, section_title in section_titles.items():
            results = by_subdir.get(section_key, [])
            if not results:
                continue

            nav_lines.append(f"  - {section_title}:")
            nav_lines.append(f"      - Overview: {section_key}/index.md")

            # Build hierarchical navigation from full category paths
            self._generate_hierarchical_nav(nav_lines, results, section_key, indent_level=3)

        # External docs sections (audits, etc.)
        for dest, section_title in self._copied_external_sections:
            nav_lines.append(f"  - {section_title}: {dest}/index.md")

        # EFAT integration tests
        if self._efat_section is not None:
            output_rel, section_title = self._efat_section
            nav_lines.append(f"  - {section_title}: {output_rel}")

        # Write nav file
        nav_path = self.config.output.output_dir / "_nav.yml"
        nav_path.write_text("\n".join(nav_lines), encoding="utf-8")

    def _generate_hierarchical_nav(
        self,
        nav_lines: list[str],
        results: list[ProcessingResult],
        section_key: str,
        indent_level: int,
    ) -> None:
        """Generate hierarchical navigation from results.

        Parameters
        ----------
        nav_lines : list[str]
            Lines to append to.
        results : list[ProcessingResult]
            Results to organize.
        section_key : str
            The section key (plc-blocks, types).
        indent_level : int
            Current indentation level.
        """
        # Build a tree structure from category paths
        tree: dict[str, dict | list[ProcessingResult]] = {}

        for result in results:
            # Get full category path
            full_category = result.block_file.category or ""
            if result.block_file.subcategory:
                full_category = f"{full_category} / {result.block_file.subcategory}"

            # Split into path parts
            if full_category:
                parts = [p.strip() for p in full_category.split(" / ")]
            else:
                parts = []

            # Navigate/create tree path
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                node = current[part]
                if isinstance(node, dict):
                    current = node
                else:
                    break

            # Add result at leaf
            if "_items" not in current:
                current["_items"] = []
            items = current["_items"]
            if isinstance(items, list):
                items.append(result)

        # Generate nav from tree
        self._write_nav_tree(nav_lines, tree, indent_level)

    def _write_nav_tree(
        self,
        nav_lines: list[str],
        tree: dict[str, dict | list[ProcessingResult]],
        indent_level: int,
    ) -> None:
        """Write navigation tree recursively.

        Parameters
        ----------
        nav_lines : list[str]
            Lines to append to.
        tree : dict
            Tree structure to write.
        indent_level : int
            Current indentation level.
        """
        indent = "  " * indent_level

        # Sort keys, but put _items last
        keys = sorted(k for k in tree.keys() if k != "_items")

        for key in keys:
            value = tree[key]
            if isinstance(value, dict):
                nav_lines.append(f"{indent}- {key}:")
                self._write_nav_tree(nav_lines, value, indent_level + 1)

        # Write items at this level
        if "_items" in tree:
            items = tree["_items"]
            if isinstance(items, list):
                for result in sorted(items, key=lambda r: r.title):
                    if result.output_path:
                        relative = result.output_path.relative_to(self.config.output.output_dir)
                        nav_lines.append(f"{indent}- {result.title}: {relative}")

    def _generate_call_graph_pages(self) -> None:
        """Generate call graph documentation pages."""
        if not self.call_graph or not self.call_graph.nodes:
            return

        # Create graphs directory
        graphs_dir = self.config.output.output_dir / "graphs"
        graphs_dir.mkdir(parents=True, exist_ok=True)

        # Find connected components
        all_components = find_connected_components(self.call_graph)

        # Filter out isolated blocks (no relationships)
        components = [c for c in all_components if c.edge_count > 0]
        isolated_components = [c for c in all_components if c.edge_count == 0]

        # Get isolated blocks with their doc paths for linking
        isolated_blocks: dict[str, str] = {}
        for comp in isolated_components:
            for name, node in comp.nodes.items():
                isolated_blocks[name] = node.doc_path

        # Generate index page (pass all components for statistics)
        self._generate_graph_index(graphs_dir, components, isolated_blocks)

        # Generate page for each non-isolated component
        for i, component in enumerate(components):
            self._generate_component_page(graphs_dir, component, i + 1)

    def _generate_graph_index(
        self,
        graphs_dir: Path,
        components: list[ConnectedComponent],
        isolated_blocks: dict[str, str] | None = None,
    ) -> None:
        """Generate the call graph index page.

        Parameters
        ----------
        graphs_dir : Path
            Output directory for graph pages.
        components : list[ConnectedComponent]
            Connected components with relationships (non-isolated).
        isolated_blocks : dict[str, str] | None
            Mapping of isolated block names to their doc paths.
        """
        isolated_blocks = isolated_blocks or {}
        isolated_count = len(isolated_blocks)
        lines = [
            "# Call Graphs",
            "",
            "This section documents the calling dependencies between function blocks",
            "and functions in the project.",
            "",
        ]

        # Statistics
        if self.call_graph:
            stats = compute_graph_statistics(self.call_graph)
            lines.extend(
                [
                    "## Statistics",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Total Blocks | {stats['node_count']} |",
                    f"| Total Call Relationships | {stats['edge_count']} |",
                    f"| Isolated Blocks (no graph) | {isolated_count} |",
                    f"| Connected Graphs | {len(components)} |",
                    "",
                ]
            )

        # List of graphs
        lines.extend(
            [
                "## Call Graphs",
                "",
            ]
        )

        for i, component in enumerate(components):
            graph_num = i + 1
            comp_name = component.name or f"Graph {graph_num}"
            node_count = component.node_count
            edge_count = component.edge_count

            lines.append(
                f"- [{comp_name}](graph-{graph_num}.md) - " f"{node_count} blocks, {edge_count} relationships"
            )

        lines.append("")

        # List isolated blocks if any
        if isolated_blocks:
            lines.extend(
                [
                    "## Isolated Blocks",
                    "",
                    "The following blocks have no call relationships:",
                    "",
                ]
            )
            for block_name in sorted(isolated_blocks.keys()):
                doc_path = isolated_blocks[block_name]
                if doc_path:
                    # Convert doc path to relative link from graphs/ directory
                    link_path = f"../{doc_path}"
                    lines.append(f"- [{block_name}]({link_path})")
                else:
                    lines.append(f"- {block_name}")
            lines.append("")

        # Write index
        index_path = graphs_dir / "index.md"
        index_path.write_text("\n".join(lines), encoding="utf-8")

    def _generate_component_page(
        self, graphs_dir: Path, component: ConnectedComponent, graph_num: int
    ) -> None:
        """Generate a page for a single call graph component.

        Parameters
        ----------
        graphs_dir : Path
            Output directory for graph pages.
        component : ConnectedComponent
            The component to document.
        graph_num : int
            Component number (for filename).
        """
        comp_name = component.name or f"Graph {graph_num}"
        root = component.get_primary_root()

        lines = [
            f"# {comp_name}",
            "",
        ]

        # Add root information
        if root:
            lines.extend(
                [
                    f"**Entry Point:** `{root}`",
                    "",
                ]
            )

        # Statistics
        node_count = component.node_count
        edge_count = component.edge_count

        lines.extend(
            [
                "## Overview",
                "",
                f"- **Blocks:** {node_count}",
                f"- **Call Relationships:** {edge_count}",
                "",
            ]
        )

        # Generate Mermaid diagram
        lines.extend(
            [
                "## Call Graph",
                "",
                "Click on any block to view its documentation.",
                "",
            ]
        )

        # Use current graph file as base path for relative link computation
        current_file_path = f"graphs/graph-{graph_num}.md"

        # Add legend before the graph
        legend = generate_legend_block(component)
        if legend:
            lines.append(legend)
            lines.append("")

        # Use LR (left-right) direction for larger graphs for better readability
        direction = "LR" if node_count > 5 else "TB"

        mermaid = generate_mermaid_block(
            component,
            direction=direction,
            include_click_links=True,
            base_path=current_file_path,
        )
        lines.append(mermaid)
        lines.append("")

        # Write page
        page_path = graphs_dir / f"graph-{graph_num}.md"
        page_path.write_text("\n".join(lines), encoding="utf-8")

    def _generate_type_graph_pages(self) -> None:
        """Generate type dependency graph documentation pages."""
        if not self.type_graph or not self.type_graph.nodes:
            return

        # Create type-graphs directory
        type_graphs_dir = self.config.output.output_dir / "type-graphs"
        type_graphs_dir.mkdir(parents=True, exist_ok=True)

        # Find connected components
        all_components = find_type_components(self.type_graph)

        # Filter out isolated types (no relationships)
        components = [c for c in all_components if c.edge_count > 0]

        # Generate index page
        self._generate_type_graph_index(type_graphs_dir, components, len(all_components) - len(components))

        # Generate page for each non-isolated component
        for i, component in enumerate(components):
            self._generate_type_component_page(type_graphs_dir, component, i + 1)

    def _generate_type_graph_index(
        self,
        type_graphs_dir: Path,
        components: list[TypeComponent],
        isolated_count: int = 0,
    ) -> None:
        """Generate the type dependency graph index page.

        Parameters
        ----------
        type_graphs_dir : Path
            Output directory for type graph pages.
        components : list[TypeComponent]
            Connected components with relationships (non-isolated).
        isolated_count : int
            Number of isolated types (no relationships).
        """
        lines = [
            "# Type Dependency Graphs",
            "",
            "This section documents the type dependencies between User Data Types (UDTs)",
            "in the project. A dependency exists when one UDT contains a field of another",
            "UDT type.",
            "",
        ]

        # Statistics
        if self.type_graph:
            stats = compute_type_graph_statistics(self.type_graph)
            lines.extend(
                [
                    "## Statistics",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Total Types | {stats['node_count']} |",
                    f"| Total Dependencies | {stats['edge_count']} |",
                    f"| Isolated Types (no graph) | {isolated_count} |",
                    f"| Connected Graphs | {len(components)} |",
                    "",
                ]
            )

        # List of graphs
        lines.extend(
            [
                "## Type Graphs",
                "",
            ]
        )

        for i, component in enumerate(components):
            graph_num = i + 1
            comp_name = component.name or f"Graph {graph_num}"
            node_count = component.node_count
            edge_count = component.edge_count

            lines.append(
                f"- [{comp_name}](type-graph-{graph_num}.md) - "
                f"{node_count} types, {edge_count} dependencies"
            )

        lines.append("")

        # Write index
        index_path = type_graphs_dir / "index.md"
        index_path.write_text("\n".join(lines), encoding="utf-8")

    def _generate_type_component_page(
        self, type_graphs_dir: Path, component: TypeComponent, graph_num: int
    ) -> None:
        """Generate a page for a single type graph component.

        Parameters
        ----------
        type_graphs_dir : Path
            Output directory for type graph pages.
        component : TypeComponent
            The component to document.
        graph_num : int
            Component number (for filename).
        """
        comp_name = component.name or f"Graph {graph_num}"

        lines = [
            f"# {comp_name}",
            "",
        ]

        # Statistics
        node_count = component.node_count
        edge_count = component.edge_count

        lines.extend(
            [
                "## Overview",
                "",
                f"- **Types:** {node_count}",
                f"- **Dependencies:** {edge_count}",
                "",
            ]
        )

        # Generate Mermaid diagram
        lines.extend(
            [
                "## Dependency Graph",
                "",
                "Click on any type to view its documentation.",
                "",
            ]
        )

        # Use LR (left-right) direction for larger graphs for better readability
        direction = "LR" if node_count > 5 else "TB"

        mermaid = generate_type_component_flowchart(
            component,
            direction=direction,
            include_click_links=True,
        )
        lines.append("```mermaid")
        lines.append(mermaid)
        lines.append("```")
        lines.append("")

        # Write page
        page_path = type_graphs_dir / f"type-graph-{graph_num}.md"
        page_path.write_text("\n".join(lines), encoding="utf-8")

    def _generate_quality_pages(self) -> None:
        """Generate quality analysis documentation pages."""
        # Collect all analysis results from processing results
        analysis_results = [
            r.analysis_result for r in self.results if r.success and r.analysis_result is not None
        ]

        if not analysis_results:
            return

        # Create analysis directory
        analysis_dir = self.config.output.output_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        # Build mapping of block names to their doc paths (relative to analysis/)
        block_paths: dict[str, str] = {}
        for result in self.results:
            if result.success and result.output_path and result.block_file:
                # Get path relative to docs dir, then make it relative to analysis/
                relative_path = result.output_path.relative_to(self.config.output.output_dir)
                # From analysis/, we need to go up one level then to the block path
                block_paths[result.block_file.name] = f"../{relative_path}"

        # Build project-level analysis result
        project_result = ProjectAnalysisResult(block_results=analysis_results)

        # Generate rules documentation
        rules_content = self._markdown_reporter.generate_rules_documentation()
        (analysis_dir / "rules.md").write_text(rules_content, encoding="utf-8")

        # Generate summary page with block links
        summary_content = self._markdown_reporter.generate_summary(project_result, block_paths)
        (analysis_dir / "summary.md").write_text(summary_content, encoding="utf-8")

    def _build_and_run_tests(self, block_names: list[str]) -> None:
        """Build test registry and run tests for all blocks.

        Parameters
        ----------
        block_names : list[str]
            Names of all blocks to test.
        """
        # Build test registry (discover test files)
        self._test_registry = build_test_registry(block_names, self.config.test_dirs)

        # Run tests for discovered test files
        self._test_results = self._test_runner.run_all_tests(self._test_registry)

        # Add empty results for blocks without tests
        for block_name in block_names:
            if block_name not in self._test_results:
                self._test_results[block_name] = BlockTestResult(
                    block_name=block_name,
                    test_file=None,
                )

    def _generate_test_pages(self) -> None:
        """Generate test documentation pages."""
        # Collect all test results from processing results
        # Exclude TYPE blocks (UDTs) - they don't need unit testing
        test_results = [
            r.test_result
            for r in self.results
            if r.success and r.test_result is not None and r.block_type != "TYPE"
        ]

        if not test_results:
            return

        # Create tests directory
        tests_dir = self.config.output.output_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        # Build mapping of block names to their doc paths (relative to tests/)
        # Exclude TYPE blocks
        block_paths: dict[str, str] = {}
        for result in self.results:
            if result.success and result.output_path and result.block_file:
                if result.block_type != "TYPE":
                    relative_path = result.output_path.relative_to(self.config.output.output_dir)
                    block_paths[result.block_file.name] = f"../{relative_path}"

        # Build project-level test result
        project_result = ProjectTestResult(block_results=test_results)

        # Build category registry for coverage page
        # Exclude TYPE blocks
        categories: dict[str, list[str]] = {}
        for result in self.results:
            if result.success and result.block_file and result.block_type != "TYPE":
                category = result.block_file.category or "Uncategorized"
                if category not in categories:
                    categories[category] = []
                categories[category].append(result.block_file.name)

        # Generate summary page
        summary_content = self._test_reporter.generate_summary_page(project_result, block_paths)
        (tests_dir / "summary.md").write_text(summary_content, encoding="utf-8")

        # Generate coverage page
        coverage_content = self._test_reporter.generate_coverage_page(project_result, categories)
        (tests_dir / "coverage.md").write_text(coverage_content, encoding="utf-8")

    def _generate_db_crossref_pages(self) -> None:
        """Generate global data block cross-reference documentation pages."""
        if not self._db_dependencies:
            return

        # Create global-data directory
        global_data_dir = self.config.output.output_dir / "global-data"
        global_data_dir.mkdir(parents=True, exist_ok=True)

        # Build mapping of block names to their doc paths (relative to global-data/)
        # Exclude TYPE blocks
        doc_paths: dict[str, str] = {}
        for result in self.results:
            if result.success and result.output_path and result.block_file:
                if result.block_type != "TYPE":
                    relative_path = result.output_path.relative_to(self.config.output.output_dir)
                    doc_paths[result.block_file.name] = str(relative_path).replace("\\", "/")

        # Build cross-reference from all collected dependencies
        crossref = build_db_crossref(self._db_dependencies, doc_paths)

        # Generate main index page
        index_content = generate_crossref_index(crossref)
        (global_data_dir / "index.md").write_text(index_content, encoding="utf-8")

        # Generate per-DB pages with collapsible hierarchy
        for db_name in sorted(crossref.by_db.keys()):
            variables = crossref.by_db[db_name]
            base_path = f"global-data/{db_name}.md"
            db_content = generate_db_page(db_name, variables, base_path)
            (global_data_dir / f"{db_name}.md").write_text(db_content, encoding="utf-8")

        # Run global variable audit and generate report
        audit_result = run_global_variable_audit(crossref, self._db_dependencies)
        audit_content = generate_audit_markdown(audit_result, "global-data/audit.md")
        (global_data_dir / "audit.md").write_text(audit_content, encoding="utf-8")

    def _project_root(self) -> Path:
        """Resolve the project root used for external paths (audits, EFAT)."""
        return self.config.project_root or self.config.source_dir

    def _copy_external_docs(self) -> None:
        """Copy external markdown files (audits, etc.) into the docs tree."""
        import shutil

        project_root = self._project_root()
        for entry in self.config.external_docs:
            matches = sorted(project_root.glob(entry.source))
            if not matches:
                continue

            dest_dir = self.config.output.output_dir / entry.dest
            dest_dir.mkdir(parents=True, exist_ok=True)

            copied: list[tuple[str, str]] = []
            for src in matches:
                if not src.is_file():
                    continue
                dst = dest_dir / src.name
                shutil.copy2(src, dst)
                title = _extract_first_h1(dst) or src.stem
                copied.append((title, src.name))

            if not copied:
                continue

            # Generate index for this external-docs section
            index_lines = [f"# {entry.title}", ""]
            for title, filename in sorted(copied, key=lambda t: t[1]):
                index_lines.append(f"- [{title}]({filename})")
            index_lines.append("")
            (dest_dir / "index.md").write_text("\n".join(index_lines), encoding="utf-8")

            self._copied_external_sections.append((entry.dest, entry.title))

    def _generate_efat_index(self) -> None:
        """Generate a static index of EFAT integration test scenarios."""
        import yaml

        test_dir = self.config.efat.test_dir
        if test_dir is None:
            return

        project_root = self._project_root()
        if not test_dir.is_absolute():
            test_dir = project_root / test_dir

        if not test_dir.is_dir():
            return

        patterns = ("EFAT_*.yaml", "EFAT_*.yml", "test_*.yaml", "test_*.yml")
        files: list[Path] = []
        for pattern in patterns:
            files.extend(test_dir.glob(pattern))
        files = sorted(set(files))

        scenarios: list[dict[str, object]] = []
        for path in files:
            try:
                content = path.read_text(encoding="utf-8")
                data = yaml.safe_load(content) or {}
            except (yaml.YAMLError, OSError):
                continue

            scenario = data.get("scenario", {}) if isinstance(data, dict) else {}
            if not isinstance(scenario, dict):
                scenario = {}

            tags = scenario.get("tags") or []
            if not isinstance(tags, list):
                tags = []

            steps = scenario.get("steps") or []
            step_count = len(steps) if isinstance(steps, list) else 0

            scenarios.append(
                {
                    "file": path.name,
                    "name": str(scenario.get("name", path.stem)),
                    "description": str(scenario.get("description", "")),
                    "tags": [str(t) for t in tags],
                    "step_count": step_count,
                }
            )

        # Group by primary tag (first tag); scenarios without tags go to "Other"
        by_tag: dict[str, list[dict[str, object]]] = {}
        for scenario in scenarios:
            tags = scenario["tags"]
            assert isinstance(tags, list)
            tag = tags[0] if tags else "Other"
            by_tag.setdefault(tag, []).append(scenario)

        # Build markdown
        lines = [
            "# Integration Tests (EFAT)",
            "",
            f"This page lists the {len(scenarios)} integration test scenarios "
            f"executed via `plc sim test`. Each scenario is a YAML file in "
            f"`{test_dir.name}/`.",
            "",
        ]

        for tag in sorted(by_tag.keys()):
            lines.extend([f"## {tag}", ""])
            lines.append("| File | Name | Description | Steps | Tags |")
            lines.append("|------|------|-------------|-------|------|")
            for scenario in sorted(by_tag[tag], key=lambda s: str(s["file"])):
                file = scenario["file"]
                name = str(scenario["name"]).replace("|", "\\|")
                description = str(scenario["description"]).replace("|", "\\|")
                tags = scenario["tags"]
                assert isinstance(tags, list)
                tags_str = ", ".join(tags)
                steps = scenario["step_count"]
                lines.append(f"| `{file}` | {name} | {description} | {steps} | {tags_str} |")
            lines.append("")

        # Write the output
        output_rel = self.config.efat.output
        output_path = self.config.output.output_dir / output_rel
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")

        # Record for nav generation
        self._efat_section = (output_rel, "Integration Tests (EFAT)")

    def _generate_root_index(self) -> None:
        """Generate the root index.md with project info and dynamic stats."""
        # Compute statistics from results
        by_type: dict[str, int] = {}
        total_errors = 0
        total_warnings = 0
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        tested_blocks = 0

        for result in self.results:
            if not result.success:
                continue
            if result.block_type:
                by_type[result.block_type] = by_type.get(result.block_type, 0) + 1
            if result.analysis_result is not None:
                total_errors += result.analysis_result.error_count
                total_warnings += result.analysis_result.warning_count
            if result.test_result is not None and result.test_result.test_file is not None:
                tested_blocks += 1
                total_tests += result.test_result.total
                passed_tests += result.test_result.passed
                failed_tests += result.test_result.failed
                skipped_tests += result.test_result.skipped

        # Header
        if self.config.project_name:
            title = f"{self.config.project_name} - PLC Documentation"
        else:
            title = "PLC Documentation"

        lines = [f"# {title}", ""]

        # Project info table
        info_rows: list[tuple[str, str]] = []
        if self.config.project_name:
            info_rows.append(("Project Name", self.config.project_name))
        if self.config.project_code:
            info_rows.append(("Project Code", self.config.project_code))
        if self.config.project_version:
            info_rows.append(("Version", self.config.project_version))

        if info_rows:
            lines.extend(["## Project Overview", "", "| Property | Value |", "|----------|-------|"])
            for label, value in info_rows:
                lines.append(f"| **{label}** | {value} |")
            lines.append("")

        # Block statistics
        type_labels = [
            ("FUNCTION_BLOCK", "Function Blocks"),
            ("FUNCTION", "Functions"),
            ("ORGANIZATION_BLOCK", "Organization Blocks"),
            ("DATA_BLOCK", "Data Blocks"),
            ("TYPE", "User Data Types (UDTs)"),
        ]
        block_total = sum(by_type.values())
        if block_total > 0:
            lines.extend(["## Block Statistics", "", "| Block Type | Count |", "|------------|-------|"])
            for type_key, label in type_labels:
                count = by_type.get(type_key, 0)
                if count > 0:
                    lines.append(f"| {label} | {count} |")
            lines.append(f"| **Total** | **{block_total}** |")
            lines.append("")

        # Quality summary
        if total_errors or total_warnings:
            lines.extend(
                [
                    "## Code Quality",
                    "",
                    "| Severity | Count |",
                    "|----------|-------|",
                    f"| Errors | {total_errors} |",
                    f"| Warnings | {total_warnings} |",
                    "",
                    "See [Quality Analysis Summary](analysis/summary.md) for details.",
                    "",
                ]
            )

        # Test summary
        if tested_blocks > 0:
            pass_rate = (passed_tests / total_tests * 100.0) if total_tests else 0.0
            lines.extend(
                [
                    "## Unit Tests",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Tested Blocks | {tested_blocks} |",
                    f"| Total Tests | {total_tests} |",
                    f"| Passed | {passed_tests} |",
                    f"| Failed | {failed_tests} |",
                    f"| Skipped | {skipped_tests} |",
                    f"| Pass Rate | {pass_rate:.1f}% |",
                    "",
                    "See [Test Summary](tests/summary.md) for details.",
                    "",
                ]
            )

        # Sections directory
        lines.extend(["## Documentation Sections", ""])
        if (
            by_type.get("FUNCTION_BLOCK", 0)
            + by_type.get("FUNCTION", 0)
            + by_type.get("ORGANIZATION_BLOCK", 0)
            > 0
        ):
            lines.append("- [PLC Blocks](plc-blocks/index.md) — function blocks, functions, OBs")
        if by_type.get("TYPE", 0) > 0:
            lines.append("- [Data Types](types/index.md) — user-defined types (UDTs)")
        if by_type.get("DATA_BLOCK", 0) > 0:
            lines.append("- [Data Blocks](data-blocks/index.md) — global data blocks")
        if self.call_graph and self.call_graph.nodes:
            lines.append("- [Call Graphs](graphs/index.md) — block call relationships")
        if self.type_graph and self.type_graph.nodes:
            lines.append("- [Type Graphs](type-graphs/index.md) — UDT dependencies")
        if self._db_dependencies:
            lines.append("- [Global Data](global-data/index.md) — cross-references and audit")
        if total_errors or total_warnings:
            lines.append("- [Quality Analysis](analysis/summary.md) — linting results")
        if tested_blocks > 0:
            lines.append("- [Unit Tests](tests/summary.md) — test results and coverage")
        if self._efat_section is not None:
            lines.append(
                f"- [{self._efat_section[1]}]({self._efat_section[0]}) — " "integration test scenarios"
            )
        for dest, section_title in self._copied_external_sections:
            lines.append(f"- [{section_title}]({dest}/index.md)")
        lines.append("")

        # Write
        index_path = self.config.output.output_dir / "index.md"
        index_path.write_text("\n".join(lines), encoding="utf-8")


def _extract_first_h1(path: Path) -> str:
    """Read the first H1 heading from a markdown file, or empty string."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        return ""
    return ""


def generate_project_documentation(
    source_dir: Path,
    output_dir: Path | None = None,
    **options: object,
) -> list[ProcessingResult]:
    """Generate documentation for an entire project.

    Parameters
    ----------
    source_dir : Path
        Root directory containing TIA Portal exports.
    output_dir : Path | None
        Output directory for generated docs.
    **options : object
        Additional options passed to ProjectConfig.

    Returns
    -------
    list[ProcessingResult]
        Results for all processed files.
    """
    config = ProjectConfig.from_source(source_dir, output_dir)

    # Apply any additional options
    for key, value in options.items():
        if hasattr(config, key):
            setattr(config, key, value)
        elif hasattr(config.output, key):
            setattr(config.output, key, value)
        elif hasattr(config.markdown, key):
            setattr(config.markdown, key, value)

    pipeline = DocumentationPipeline(config)
    return pipeline.run()
