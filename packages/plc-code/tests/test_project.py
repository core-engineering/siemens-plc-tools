"""Tests for project management module."""

from pathlib import Path

from plc_code.project.config import EfatConfig, ExternalDocs, OutputConfig, ProjectConfig
from plc_code.project.discovery import (
    BlockFile,
    _extract_categories,
    discover_blocks,
    group_by_category,
    group_by_type,
)
from plc_code.project.pipeline import (
    DocumentationPipeline,
    PipelineStats,
    ProcessingResult,
)


class TestOutputConfig:
    """Tests for OutputConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = OutputConfig()

        assert config.output_dir == Path("docs")
        assert config.plc_blocks_subdir == "plc-blocks"
        assert config.types_subdir == "types"
        assert config.create_index is True
        assert config.create_mkdocs_nav is True

    def test_get_subdir(self) -> None:
        """Test getting subdirectory for block types."""
        config = OutputConfig()

        assert config.get_subdir("FUNCTION_BLOCK") == "plc-blocks"
        assert config.get_subdir("FUNCTION") == "plc-blocks"
        assert config.get_subdir("ORGANIZATION_BLOCK") == "plc-blocks"
        assert config.get_subdir("TYPE") == "types"
        assert config.get_subdir("DATA_BLOCK") == "data-blocks"
        assert config.get_subdir("UNKNOWN") == "other"


class TestProjectConfig:
    """Tests for ProjectConfig."""

    def test_from_source(self, tmp_path: Path) -> None:
        """Test creating config from source directory."""
        config = ProjectConfig.from_source(tmp_path)

        assert config.source_dir == tmp_path
        assert config.output.output_dir == tmp_path / "docs"

    def test_from_source_with_output_dir(self, tmp_path: Path) -> None:
        """Test creating config with custom output directory."""
        output_dir = tmp_path / "custom_docs"
        config = ProjectConfig.from_source(tmp_path, output_dir)

        assert config.output.output_dir == output_dir


class TestBlockFile:
    """Tests for BlockFile dataclass."""

    def test_auto_name_from_path(self) -> None:
        """Test that name is extracted from source path."""
        block = BlockFile(source_path=Path("/path/to/MyBlock.s7dcl"))

        assert block.name == "MyBlock"

    def test_explicit_name(self) -> None:
        """Test providing explicit name."""
        block = BlockFile(
            source_path=Path("/path/to/MyBlock.s7dcl"),
            name="CustomName",
        )

        assert block.name == "CustomName"


class TestExtractCategories:
    """Tests for category extraction from paths."""

    def test_simple_path(self) -> None:
        """Test simple path without numbering."""
        category, subcategory = _extract_categories(Path("Blocks/MyBlock.s7dcl"))

        assert category == "Blocks"
        assert subcategory == ""

    def test_numbered_path(self) -> None:
        """Test TIA Portal numbered path format - full names preserved."""
        category, subcategory = _extract_categories(Path("100 - Process/120 - Physical Interfaces/MotorStarter.s7dcl"))

        assert category == "100 - Process"
        assert subcategory == "120 - Physical Interfaces"

    def test_plc_blocks_prefix(self) -> None:
        """Test that PLC blocks prefix is stripped but full names preserved."""
        category, subcategory = _extract_categories(
            Path("PLC blocks/100 - Process/120 - Physical Interfaces/MotorStarter.s7dcl")
        )

        assert category == "100 - Process"
        assert subcategory == "120 - Physical Interfaces"

    def test_plc_data_types_prefix(self) -> None:
        """Test that PLC data types prefix is stripped but full names preserved."""
        category, subcategory = _extract_categories(
            Path("PLC data types/20 - Parameters/typeUnitGeometry.s7dcl")
        )

        assert category == "20 - Parameters"
        assert subcategory == ""

    def test_deep_nesting(self) -> None:
        """Test deeply nested paths with full TIA Portal names."""
        category, subcategory = _extract_categories(
            Path("100 - Process/130 - Drive/133 - Drive Motion/Motion.s7dcl")
        )

        assert category == "100 - Process"
        assert subcategory == "130 - Drive / 133 - Drive Motion"

    def test_empty_path(self) -> None:
        """Test file in root directory."""
        category, subcategory = _extract_categories(Path("MyBlock.s7dcl"))

        assert category == ""
        assert subcategory == ""


class TestDiscoverBlocks:
    """Tests for block discovery."""

    def test_discover_in_empty_directory(self, tmp_path: Path) -> None:
        """Test discovering in empty directory."""
        blocks = discover_blocks(tmp_path)

        assert blocks == []

    def test_discover_single_file(self, tmp_path: Path) -> None:
        """Test discovering single file."""
        (tmp_path / "Test.s7dcl").write_text("FUNCTION_BLOCK")

        blocks = discover_blocks(tmp_path)

        assert len(blocks) == 1
        assert blocks[0].name == "Test"

    def test_discover_with_resource_file(self, tmp_path: Path) -> None:
        """Test discovering file with companion resource."""
        (tmp_path / "Test.s7dcl").write_text("FUNCTION_BLOCK")
        (tmp_path / "Test.s7res").write_text("MultiLingualTexts:")

        blocks = discover_blocks(tmp_path)

        assert len(blocks) == 1
        assert blocks[0].resource_path is not None
        assert blocks[0].resource_path.name == "Test.s7res"

    def test_discover_with_hierarchy(self, tmp_path: Path) -> None:
        """Test discovering with directory hierarchy."""
        (tmp_path / "Blocks").mkdir()
        (tmp_path / "Blocks" / "Test.s7dcl").write_text("FUNCTION_BLOCK")

        blocks = discover_blocks(tmp_path)

        assert len(blocks) == 1
        assert blocks[0].category == "Blocks"

    def test_discover_sorted_by_category(self, tmp_path: Path) -> None:
        """Test that results are sorted by category."""
        (tmp_path / "B_Category").mkdir()
        (tmp_path / "A_Category").mkdir()
        (tmp_path / "B_Category" / "Block1.s7dcl").write_text("FB")
        (tmp_path / "A_Category" / "Block2.s7dcl").write_text("FB")

        blocks = discover_blocks(tmp_path)

        assert len(blocks) == 2
        assert blocks[0].category == "A_Category"
        assert blocks[1].category == "B_Category"


class TestGroupByCategory:
    """Tests for grouping blocks by category."""

    def test_group_empty_list(self) -> None:
        """Test grouping empty list."""
        groups = group_by_category([])

        assert groups == {}

    def test_group_single_category(self) -> None:
        """Test grouping blocks in single category."""
        blocks = [
            BlockFile(source_path=Path("a.s7dcl"), category="Cat1"),
            BlockFile(source_path=Path("b.s7dcl"), category="Cat1"),
        ]

        groups = group_by_category(blocks)

        assert len(groups) == 1
        assert len(groups["Cat1"]) == 2

    def test_group_multiple_categories(self) -> None:
        """Test grouping blocks in multiple categories."""
        blocks = [
            BlockFile(source_path=Path("a.s7dcl"), category="Cat1"),
            BlockFile(source_path=Path("b.s7dcl"), category="Cat2"),
        ]

        groups = group_by_category(blocks)

        assert len(groups) == 2
        assert len(groups["Cat1"]) == 1
        assert len(groups["Cat2"]) == 1

    def test_uncategorized_blocks(self) -> None:
        """Test blocks without category."""
        blocks = [
            BlockFile(source_path=Path("a.s7dcl"), category=""),
        ]

        groups = group_by_category(blocks)

        assert "Uncategorized" in groups


class TestGroupByType:
    """Tests for grouping blocks by type."""

    def test_infer_type_block(self) -> None:
        """Test inferring block type."""
        blocks = [
            BlockFile(
                source_path=Path("Block.s7dcl"),
                relative_path=Path("PLC blocks/Block.s7dcl"),
            ),
        ]

        groups = group_by_type(blocks)

        assert len(groups["blocks"]) == 1
        assert len(groups["types"]) == 0

    def test_infer_type_udt(self) -> None:
        """Test inferring UDT type from path."""
        blocks = [
            BlockFile(
                source_path=Path("typeTest.s7dcl"),
                relative_path=Path("PLC data types/typeTest.s7dcl"),
            ),
        ]

        groups = group_by_type(blocks)

        assert len(groups["types"]) == 1
        assert len(groups["blocks"]) == 0

    def test_infer_type_from_name_prefix(self) -> None:
        """Test inferring UDT type from name prefix."""
        blocks = [
            BlockFile(
                source_path=Path("typeConfig.s7dcl"),
                relative_path=Path("typeConfig.s7dcl"),
            ),
        ]

        groups = group_by_type(blocks)

        assert len(groups["types"]) == 1


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = ProcessingResult(block_file=BlockFile(source_path=Path("test.s7dcl")))

        assert result.success is True
        assert result.output_path is None
        assert result.error is None


class TestPipelineStats:
    """Tests for PipelineStats dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        stats = PipelineStats()

        assert stats.total == 0
        assert stats.successful == 0
        assert stats.failed == 0
        assert stats.by_category == {}
        assert stats.by_type == {}


class TestDocumentationPipeline:
    """Tests for DocumentationPipeline."""

    def test_run_empty_directory(self, tmp_path: Path) -> None:
        """Test running on empty directory."""
        config = ProjectConfig.from_source(tmp_path)
        pipeline = DocumentationPipeline(config)

        results = pipeline.run()

        assert results == []
        assert pipeline.stats.total == 0

    def test_run_single_block(self, tmp_path: Path) -> None:
        """Test running on single block."""
        source = tmp_path / "source"
        source.mkdir()

        # Create a minimal valid SCL file
        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)

        results = pipeline.run()

        assert len(results) == 1
        assert results[0].success is True
        assert pipeline.stats.total == 1
        assert pipeline.stats.successful == 1

    def test_run_with_resource_file(self, tmp_path: Path) -> None:
        """Test processing with resource file."""
        source = tmp_path / "source"
        source.mkdir()

        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')
        (source / "Test.s7res").write_text("MultiLingualTexts:\n  - id: MLC_1\n    en-US: Test")

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)

        results = pipeline.run()

        assert len(results) == 1
        assert results[0].success is True

    def test_generates_output_file(self, tmp_path: Path) -> None:
        """Test that output file is generated."""
        source = tmp_path / "source"
        source.mkdir()

        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)
        results = pipeline.run()

        assert results[0].output_path is not None
        assert results[0].output_path.exists()
        assert "# Test" in results[0].output_path.read_text()

    def test_generates_index_page(self, tmp_path: Path) -> None:
        """Test that index page is generated."""
        source = tmp_path / "source"
        source.mkdir()

        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        index_path = config.output.output_dir / "plc-blocks" / "index.md"
        assert index_path.exists()
        assert "# PLC Blocks" in index_path.read_text()

    def test_generates_root_index_page(self, tmp_path: Path) -> None:
        """Test that the root index.md is generated with project info and stats."""
        source = tmp_path / "source"
        source.mkdir()

        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        config = ProjectConfig.from_source(source)
        config.project_name = "My Project"
        config.project_code = "PRJ001"
        config.project_version = "1.2.3"
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        index_path = config.output.output_dir / "index.md"
        content = index_path.read_text()
        assert index_path.exists()
        assert "My Project" in content
        assert "PRJ001" in content
        assert "1.2.3" in content
        # Should report at least one function block
        assert "Function Blocks" in content

    def test_root_index_default_when_no_project_name(self, tmp_path: Path) -> None:
        """Test that root index falls back gracefully without project metadata."""
        source = tmp_path / "source"
        source.mkdir()

        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        index_path = config.output.output_dir / "index.md"
        assert index_path.exists()
        content = index_path.read_text()
        # No project name → generic title
        assert "PLC Documentation" in content

    def test_generates_nav_file(self, tmp_path: Path) -> None:
        """Test that navigation file is generated."""
        source = tmp_path / "source"
        source.mkdir()

        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        nav_path = config.output.output_dir / "_nav.yml"
        assert nav_path.exists()
        assert "nav:" in nav_path.read_text()

    def test_copies_external_docs(self, tmp_path: Path) -> None:
        """External markdown files are copied into the docs tree with an index."""
        project_root = tmp_path
        source = project_root / "source"
        source.mkdir()
        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        # Create two audit files at project root
        (project_root / "audit-alarm.md").write_text("# Alarm Lifecycle\n\nDetails.")
        (project_root / "audit-naming.md").write_text("# Naming Convention\n\nDetails.")
        # Decoy that should not be copied
        (project_root / "README.md").write_text("# README")

        config = ProjectConfig.from_source(source)
        config.project_root = project_root
        config.external_docs = [ExternalDocs(source="audit-*.md", dest="audits", title="Project Audits")]
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        audits_dir = config.output.output_dir / "audits"
        assert (audits_dir / "audit-alarm.md").exists()
        assert (audits_dir / "audit-naming.md").exists()
        assert not (audits_dir / "README.md").exists()

        index_content = (audits_dir / "index.md").read_text()
        assert "# Project Audits" in index_content
        # H1 titles are extracted
        assert "[Alarm Lifecycle](audit-alarm.md)" in index_content
        assert "[Naming Convention](audit-naming.md)" in index_content

    def test_external_docs_in_root_index(self, tmp_path: Path) -> None:
        """External docs sections are linked from the root index."""
        project_root = tmp_path
        source = project_root / "source"
        source.mkdir()
        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')
        (project_root / "audit-a.md").write_text("# Audit A")

        config = ProjectConfig.from_source(source)
        config.project_root = project_root
        config.external_docs = [ExternalDocs(source="audit-*.md", dest="audits", title="Project Audits")]
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        root_index = (config.output.output_dir / "index.md").read_text()
        assert "Project Audits" in root_index
        assert "audits/index.md" in root_index

    def test_external_docs_in_nav(self, tmp_path: Path) -> None:
        """External docs section appears in the mkdocs nav."""
        project_root = tmp_path
        source = project_root / "source"
        source.mkdir()
        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')
        (project_root / "audit-a.md").write_text("# Audit A")

        config = ProjectConfig.from_source(source)
        config.project_root = project_root
        config.external_docs = [ExternalDocs(source="audit-*.md", dest="audits", title="Project Audits")]
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        nav = (config.output.output_dir / "_nav.yml").read_text()
        assert "Project Audits" in nav
        assert "audits/index.md" in nav

    def test_generates_efat_index(self, tmp_path: Path) -> None:
        """EFAT integration scenarios are listed in tests/integration.md."""
        project_root = tmp_path
        source = project_root / "source"
        source.mkdir()
        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')

        # Create EFAT YAML files
        efat_dir = project_root / "integration-tests"
        efat_dir.mkdir()
        (efat_dir / "EFAT_001_lamp_test.yaml").write_text(
            "# Lamp test header comment\n"
            "scenario:\n"
            "  name: Lamp Test\n"
            "  description: EFAT-001 verify all lamps\n"
            "  tags: [STATION]\n"
            "  steps:\n"
            "    - step: write\n"
            "    - step: assert\n"
        )
        (efat_dir / "EFAT_004_pump_alt.yaml").write_text(
            "scenario:\n"
            "  name: Pump Alternation\n"
            "  description: EFAT-004 auto pump alternation\n"
            "  tags: [STATION, PUMP]\n"
            "  steps:\n"
            "    - step: write\n"
        )
        # Non-EFAT YAML should be ignored
        (efat_dir / "setup.yaml").write_text("scenario:\n  name: setup\n")

        config = ProjectConfig.from_source(source)
        config.project_root = project_root
        config.efat = EfatConfig(test_dir=Path("integration-tests"))
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        efat_path = config.output.output_dir / "tests" / "integration.md"
        assert efat_path.exists()
        content = efat_path.read_text()
        assert "# Integration Tests (EFAT)" in content
        assert "Lamp Test" in content
        assert "Pump Alternation" in content
        assert "EFAT-001" in content
        # Tag groups
        assert "## STATION" in content
        # Setup.yaml should NOT appear
        assert "setup" not in content.lower() or "setup.yaml" not in content

    def test_efat_section_in_nav(self, tmp_path: Path) -> None:
        """EFAT section appears in the nav and root index."""
        project_root = tmp_path
        source = project_root / "source"
        source.mkdir()
        (source / "Test.s7dcl").write_text('FUNCTION_BLOCK "Test"\nEND_FUNCTION_BLOCK')
        efat_dir = project_root / "integration-tests"
        efat_dir.mkdir()
        (efat_dir / "EFAT_001.yaml").write_text(
            "scenario:\n  name: T\n  description: d\n  tags: [STATION]\n  steps: []\n"
        )

        config = ProjectConfig.from_source(source)
        config.project_root = project_root
        config.efat = EfatConfig(test_dir=Path("integration-tests"))
        pipeline = DocumentationPipeline(config)
        pipeline.run()

        root_index = (config.output.output_dir / "index.md").read_text()
        assert "Integration Tests (EFAT)" in root_index

    def test_handles_parse_error(self, tmp_path: Path) -> None:
        """Test handling parse errors gracefully."""
        source = tmp_path / "source"
        source.mkdir()

        # Create invalid SCL file
        (source / "Invalid.s7dcl").write_text("THIS IS NOT VALID SCL")

        config = ProjectConfig.from_source(source)
        pipeline = DocumentationPipeline(config)

        results = pipeline.run()

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None
        assert pipeline.stats.failed == 1
