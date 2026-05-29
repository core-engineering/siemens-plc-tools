"""Configuration models for documentation projects.

This module defines configuration dataclasses for controlling
documentation generation behavior and output organization.
"""

from dataclasses import dataclass, field
from pathlib import Path

from plc_code.generator.markdown import MarkdownOptions


@dataclass
class OutputConfig:
    """Configuration for documentation output.

    Attributes
    ----------
    output_dir : Path
        Root directory for generated documentation.
    plc_blocks_subdir : str
        Subdirectory for PLC blocks (both function blocks and functions).
    types_subdir : str
        Subdirectory for UDT documentation.
    create_index : bool
        Whether to generate index pages per category.
    create_mkdocs_nav : bool
        Whether to generate mkdocs.yml navigation structure.
    """

    output_dir: Path = field(default_factory=lambda: Path("docs"))
    plc_blocks_subdir: str = "plc-blocks"
    types_subdir: str = "types"
    data_blocks_subdir: str = "data-blocks"
    create_index: bool = True
    create_mkdocs_nav: bool = True

    def get_subdir(self, block_type: str) -> str:
        """Get the subdirectory for a block type.

        Parameters
        ----------
        block_type : str
            The block type (FUNCTION_BLOCK, FUNCTION, ORGANIZATION_BLOCK,
            DATA_BLOCK, TYPE).

        Returns
        -------
        str
            The subdirectory name.
        """
        if block_type in ("FUNCTION_BLOCK", "FUNCTION", "ORGANIZATION_BLOCK"):
            return self.plc_blocks_subdir
        elif block_type == "TYPE":
            return self.types_subdir
        elif block_type == "DATA_BLOCK":
            return self.data_blocks_subdir
        return "other"


@dataclass
class ExternalDocs:
    """Reference to a glob of external markdown files to embed in the site.

    Attributes
    ----------
    source : str
        Glob pattern (relative to project root) for files to copy.
    dest : str
        Subdirectory under the docs output root where files are copied.
    title : str
        Human-readable section title shown in navigation.
    """

    source: str
    dest: str
    title: str


@dataclass
class EfatConfig:
    """Configuration for the integration-test (EFAT) scenario index.

    Attributes
    ----------
    test_dir : Path | None
        Directory containing EFAT/integration test YAML files. If None, the
        feature is disabled.
    output : str
        Path (relative to the docs output root) of the generated index file.
    """

    test_dir: Path | None = None
    output: str = "tests/integration.md"


@dataclass
class ProjectConfig:
    """Configuration for a documentation project.

    Attributes
    ----------
    source_dir : Path
        Root directory containing TIA Portal exports.
    output : OutputConfig
        Output configuration.
    markdown : MarkdownOptions
        Markdown generation options.
    include_patterns : list[str]
        Glob patterns for files to include.
    exclude_patterns : list[str]
        Glob patterns for files to exclude.
    preserve_hierarchy : bool
        Whether to preserve the source directory hierarchy in output.
    category_from_path : bool
        Whether to extract category names from path structure.
    test_dirs : list[Path]
        Directories to search for test files.
    run_tests : bool
        Whether to run tests during documentation generation.
    project_name : str
        Project name, used in the auto-generated root ``index.md``.
    project_code : str
        Short project code/identifier, shown next to the name.
    project_version : str
        Project version string.
    project_root : Path | None
        Project root used to resolve relative paths for external docs and
        the EFAT scenario directory. Defaults to ``source_dir`` if unset.
    external_docs : list[ExternalDocs]
        External markdown groups to copy into the generated site.
    efat : EfatConfig
        Configuration for the EFAT integration-test index.
    """

    source_dir: Path
    output: OutputConfig = field(default_factory=OutputConfig)
    markdown: MarkdownOptions = field(default_factory=MarkdownOptions)
    include_patterns: list[str] = field(default_factory=lambda: ["**/*.s7dcl"])
    exclude_patterns: list[str] = field(default_factory=list)
    preserve_hierarchy: bool = True
    category_from_path: bool = True
    test_dirs: list[Path] = field(default_factory=lambda: [Path("test-cases")])
    run_tests: bool = True
    project_name: str = ""
    project_code: str = ""
    project_version: str = ""
    project_root: Path | None = None
    external_docs: list[ExternalDocs] = field(default_factory=list)
    efat: EfatConfig = field(default_factory=EfatConfig)

    @classmethod
    def from_source(
        cls,
        source_dir: Path,
        output_dir: Path | None = None,
        **kwargs: object,
    ) -> "ProjectConfig":
        """Create a project config from source directory.

        Parameters
        ----------
        source_dir : Path
            The source directory.
        output_dir : Path | None
            Optional output directory (defaults to source_dir/docs).
        **kwargs : object
            Additional configuration options.

        Returns
        -------
        ProjectConfig
            The created configuration.
        """
        if output_dir is None:
            output_dir = source_dir / "docs"

        return cls(
            source_dir=source_dir,
            output=OutputConfig(output_dir=output_dir),
            **kwargs,  # type: ignore[arg-type]
        )
