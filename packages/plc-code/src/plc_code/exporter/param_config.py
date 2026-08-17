"""Configuration for parameter table document generation.

Loads project metadata, document settings, and parameter descriptions
from a plc-program-parameters-export.yaml configuration file. This information is combined
with the parsed XML data to produce the final document.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RevisionEntry:
    """A single revision history entry.

    Attributes
    ----------
    rev : int | str
        Revision number or letter.
    date : str
        Issue date (e.g. "2025-08-08").
    description : str
        Description of changes.
    prepared_by : str
        Author who prepared the revision.
    checked_by : str
        Reviewer who checked the revision.
    approved_by : str
        Person who approved the revision.
    """

    rev: int | str = 0
    date: str = ""
    description: str = "First Issue"
    prepared_by: str = ""
    checked_by: str = ""
    approved_by: str = ""


@dataclass
class DocumentConfig:
    """Document identification and output settings.

    Attributes
    ----------
    number : str
        Document reference number (e.g. "DOC_PARAMS_0001").
    title : str
        Document title (e.g. "PROGRAM PARAMETERS TABLE").
    template : str
        Path to the docx template file (relative to config file).
    output : str
        Output path for the generated docx (relative to config file).
    """

    number: str = ""
    title: str = "PROGRAM PARAMETERS TABLE"
    template: str = ""
    output: str = "parameters_table.docx"


@dataclass
class ProjectInfo:
    """Project-level metadata for the cover page.

    Attributes
    ----------
    tag_number : str
        Equipment tag number (e.g. "219337C001").
    customer : str
        Customer/end-user name.
    equipment : str
        Equipment description (e.g. "Equipment\\nUnit-01, Unit-02").
    """

    tag_number: str = ""
    customer: str = ""
    equipment: str = ""


@dataclass
class SourceConfig:
    """Configuration for a single XML parameter source.

    Attributes
    ----------
    path : str
        Path to the XML file (relative to config file).
    prefix : str
        DB name prefix for qualified paths (e.g. "ProcessParameter").
    types_dir : str
        Optional path to directory containing .s7dcl UDT type definitions.
        When provided, self-closing UDT members are expanded using type defaults.
    """

    path: str = ""
    prefix: str = ""
    types_dir: str = ""


@dataclass
class ArmsConfig:
    """Configuration for arm parameter handling.

    Attributes
    ----------
    range : tuple[int, int]
        Array bounds [start, end] (e.g. (1, 9)).
    labels : dict[int, str]
        Human-readable labels for arms (e.g. {1: "LA-01", 2: "LA-02"}).
    skip_inactive : bool
        Whether to skip arms where type='none'.
    """

    range: tuple[int, int] = (1, 9)
    labels: dict[int, str] = field(default_factory=dict)
    skip_inactive: bool = True


@dataclass
class FilterRule:
    """A conditional filter rule for skipping parameters.

    Filters evaluate within a scope (e.g. a specific CPMS axis) and
    conditionally remove entries based on a field value.

    Attributes
    ----------
    scope : str
        Scope pattern with wildcards, e.g. "arms[*].cpms[*]".
        Each unique instantiation is evaluated independently.
    field : str
        Field name within the scope to check (e.g. "type").
    equals : str
        Value to match against (e.g. "'coder'", "''").
    action : str
        "skip_section" to remove all entries in the scope instance.
    skip : list[str]
        Field name prefixes to remove (e.g. ["cylinderPivotPosition"]).
    """

    scope: str = ""
    field: str = ""
    equals: str = ""
    action: str = ""
    skip: list[str] = dataclasses.field(default_factory=list)


@dataclass
class ParamsExportConfig:
    """Complete configuration for parameter table document generation.

    Attributes
    ----------
    document : DocumentConfig
        Document identification and output settings.
    project : ProjectInfo
        Project-level metadata.
    revision : RevisionEntry
        Current revision details.
    history : list[RevisionEntry]
        Previous revision entries.
    sources : list[SourceConfig]
        XML parameter source files.
    arms : ArmsConfig
        Unit parameter handling configuration.
    descriptions : dict[str, str]
        Parameter path → description mapping for the Comment column.
    config_path : Path | None
        Path to the config file (set after loading, used for path resolution).
    """

    document: DocumentConfig = field(default_factory=DocumentConfig)
    project: ProjectInfo = field(default_factory=ProjectInfo)
    revision: RevisionEntry = field(default_factory=RevisionEntry)
    history: list[RevisionEntry] = field(default_factory=list)
    sources: list[SourceConfig] = field(default_factory=list)
    arms: ArmsConfig = field(default_factory=ArmsConfig)
    descriptions: dict[str, str] = field(default_factory=dict)
    filters: list[FilterRule] = field(default_factory=list)
    config_path: Path | None = None

    @property
    def root_path(self) -> Path:
        """Project root directory (parent of config file)."""
        if self.config_path:
            return self.config_path.parent
        return Path.cwd()

    @property
    def template_path(self) -> Path | None:
        """Absolute path to the template docx file."""
        if not self.document.template:
            return None
        return self.root_path / self.document.template

    @property
    def output_path(self) -> Path:
        """Absolute path for the output docx file."""
        return self.root_path / self.document.output

    def resolve_source_path(self, source: SourceConfig) -> Path:
        """Resolve a source config path to an absolute path."""
        return self.root_path / source.path

    def get_description(self, relative_path: str) -> str:
        """Look up a parameter description by relative path.

        Tries progressively shorter path suffixes to find a match.
        For example, for "arms[1].motion.angular.nominalSpeeds[0]",
        tries: the full path, then "motion.angular.nominalSpeeds",
        then "angular.nominalSpeeds", then "nominalSpeeds".

        Parameters
        ----------
        relative_path : str
            Path relative to the DB name, with array indices.

        Returns
        -------
        str
            Description if found, empty string otherwise.
        """
        # Strip array indices for matching
        import re

        stripped = re.sub(r"\[\d+\]", "", relative_path)

        # Try exact match first
        if stripped in self.descriptions:
            return self.descriptions[stripped]

        # Try progressively shorter suffixes
        parts = stripped.split(".")
        for i in range(len(parts)):
            suffix = ".".join(parts[i:])
            if suffix in self.descriptions:
                return self.descriptions[suffix]

        return ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: Path | None = None) -> ParamsExportConfig:
        """Create config from a dictionary (parsed YAML).

        Parameters
        ----------
        data : dict[str, Any]
            Configuration dictionary.
        config_path : Path | None
            Path to the source config file.

        Returns
        -------
        ParamsExportConfig
            Loaded configuration.
        """
        doc_data = data.get("document", {})
        proj_data = data.get("project", {})
        rev_data = data.get("revision", {})
        history_data = data.get("revision", {}).get("history", [])
        sources_data = data.get("sources", [])
        arms_data = data.get("arms", {})

        document = DocumentConfig(
            number=doc_data.get("number", ""),
            title=doc_data.get("title", "PROGRAM PARAMETERS TABLE"),
            template=doc_data.get("template", ""),
            output=doc_data.get("output", "parameters_table.docx"),
        )

        project = ProjectInfo(
            tag_number=proj_data.get("tag_number", ""),
            customer=proj_data.get("customer", ""),
            equipment=proj_data.get("equipment", ""),
        )

        revision = RevisionEntry(
            rev=rev_data.get("number", rev_data.get("rev", 0)),
            date=rev_data.get("date", ""),
            description=rev_data.get("description", "First Issue"),
            prepared_by=rev_data.get("prepared_by", ""),
            checked_by=rev_data.get("checked_by", ""),
            approved_by=rev_data.get("approved_by", ""),
        )

        history = [
            RevisionEntry(
                rev=h.get("rev", 0),
                date=h.get("date", ""),
                description=h.get("description", ""),
                prepared_by=h.get("prepared_by", rev_data.get("prepared_by", "")),
                checked_by=h.get("checked_by", rev_data.get("checked_by", "")),
                approved_by=h.get("approved_by", rev_data.get("approved_by", "")),
            )
            for h in history_data
        ]

        sources = [
            SourceConfig(
                path=s.get("path", ""),
                prefix=s.get("prefix", ""),
                types_dir=s.get("types_dir", ""),
            )
            for s in sources_data
        ]

        arm_range = arms_data.get("range", [1, 9])
        arm_labels_raw = arms_data.get("labels", {})
        # Ensure keys are ints
        arm_labels = {int(k): v for k, v in arm_labels_raw.items()}

        arms = ArmsConfig(
            range=tuple(arm_range),  # type: ignore[arg-type]
            labels=arm_labels,
            skip_inactive=arms_data.get("skip_inactive", True),
        )

        descriptions = data.get("descriptions", {})

        filters_data = data.get("filters", [])
        filters = [
            FilterRule(
                scope=f.get("scope", ""),
                field=f.get("condition", {}).get("field", ""),
                equals=f.get("condition", {}).get("equals", ""),
                action=f.get("action", ""),
                skip=f.get("skip", []),
            )
            for f in filters_data
        ]

        return cls(
            document=document,
            project=project,
            revision=revision,
            history=history,
            sources=sources,
            arms=arms,
            descriptions=descriptions,
            filters=filters,
            config_path=config_path,
        )


def load_params_config(path: Path) -> ParamsExportConfig:
    """Load parameter export configuration from a YAML file.

    Searches for configuration in this order:
    1. Explicit file path (if path points to a file)
    2. ``plc.yaml`` → ``code.export.params`` section
    3. Standalone ``plc-program-parameters-export.yaml``
    4. Legacy ``params.yaml``

    Parameters
    ----------
    path : Path
        Path to a config file or a directory to search in.

    Returns
    -------
    ParamsExportConfig
        Loaded configuration.

    Raises
    ------
    FileNotFoundError
        If no config file is found.
    yaml.YAMLError
        If the YAML is malformed.
    """
    path = Path(path).resolve()

    if path.is_dir():
        # Try plc.yaml first (unified config)
        plc_yaml = path / "plc.yaml"
        if plc_yaml.exists():
            with open(plc_yaml, encoding="utf-8") as f:
                full_data = yaml.safe_load(f) or {}
            nested = (full_data.get("code") or {}).get("export", {}).get("params")
            if nested:
                return ParamsExportConfig.from_dict(nested, config_path=plc_yaml)

        # Fall back to standalone files
        for name in (
            "plc-program-parameters-export.yaml",
            "plc-program-parameters-export.yml",
            "params.yaml",
            "params.yml",
        ):
            candidate = path / name
            if candidate.exists():
                path = candidate
                break
        else:
            raise FileNotFoundError(
                f"No parameter export config found in {path} "
                f"(looked in plc.yaml → code.export.params, "
                f"plc-program-parameters-export.yaml, params.yaml)"
            )
    elif not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Support plc.yaml passed directly as --config
    nested = (data.get("code") or {}).get("export", {}).get("params")
    if nested:
        return ParamsExportConfig.from_dict(nested, config_path=path)

    return ParamsExportConfig.from_dict(data, config_path=path)
