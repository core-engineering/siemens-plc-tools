"""Documentation completeness rules for SCL code quality.

This module implements rules for enforcing documentation standards
in SCL blocks, ensuring proper header information, descriptions,
changelog entries, and author attribution.
"""

from plc_code.analyzer.quality.models import RuleCategory, RuleInfo, Severity, Violation
from plc_code.analyzer.quality.rules import Rule, register_rule
from plc_code.extractor.header import ExtractedHeader, extract_header
from plc_code.parser.models import Block


def _get_extracted_header(block: Block) -> ExtractedHeader:
    """Extract header from block using the header extractor.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    ExtractedHeader
        Extracted header information.
    """
    return extract_header(block, block.resource_file)


@register_rule
class MissingBlockHeaderRule(Rule):
    """D001: Block missing "Block info header" REGION.

    This rule checks that blocks have a properly formatted header region
    containing documentation metadata.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="D001",
            name="missing-block-header",
            description='Block must have a "Block info header" REGION with metadata',
            severity=Severity.ERROR,
            category=RuleCategory.DOCUMENTATION,
            rationale="Block headers provide essential documentation including title, "
            "author, version history, and purpose. Without headers, code is difficult "
            "to maintain and audit.",
            examples_bad=["FUNCTION_BLOCK without REGION Block info header"],
            examples_good=["FUNCTION_BLOCK with REGION Block info header containing metadata"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for presence of block info header.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if header is missing.
        """
        # Skip TYPE blocks - UDTs don't have Block info headers
        if block.block_type == "TYPE":
            return []

        violations = []

        # Use extractor to get header info
        header = _get_extracted_header(block)
        has_header = bool(
            header.title
            or header.comment
            or header.author
            or header.library
            or header.changelog
            or header.raw_header
        )

        if not has_header:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' is missing 'Block info header' REGION",
                    context=block.name,
                    suggestion="Add a REGION Block info header with Title, Author, and changelog",
                )
            )

        return violations


@register_rule
class MissingTitleRule(Rule):
    """D002: Block header missing Title field.

    This rule checks that the block header contains a Title field
    identifying the block's purpose.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="D002",
            name="missing-title",
            description="Block header must contain a Title field",
            severity=Severity.ERROR,
            category=RuleCategory.DOCUMENTATION,
            rationale="The title provides a human-readable name for the block that "
            "may differ from the technical block name",
            examples_bad=["Block info header without // Title: line"],
            examples_good=["// Title:            MotorStarter"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for presence of Title in header.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if title is missing.
        """
        # Skip TYPE blocks - UDTs don't have Block info headers
        if block.block_type == "TYPE":
            return []

        violations = []

        # Use extractor to get header info
        header = _get_extracted_header(block)
        has_header = bool(header.raw_header)

        if has_header and not header.title:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' header is missing Title field",
                    context=block.name,
                    suggestion="Add '// Title: BlockName' to the Block info header",
                )
            )

        return violations


@register_rule
class MissingDescriptionRule(Rule):
    """D003: Block missing description/comment.

    This rule checks that the block has a description explaining its purpose,
    either in the header Comment/Function field or in a Description REGION.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="D003",
            name="missing-description",
            description="Block must have a description explaining its purpose",
            severity=Severity.WARNING,
            category=RuleCategory.DOCUMENTATION,
            rationale="Descriptions help other developers understand what the block does "
            "without having to read all the code",
            examples_bad=["Block with empty Comment/Function field and no Description REGION"],
            examples_good=["// Comment/Function: Manage the Acknowledge Alarm state machine"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for presence of description.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if description is missing.
        """
        # Skip TYPE blocks - UDTs don't have Description REGIONs
        if block.block_type == "TYPE":
            return []

        violations = []

        # Use extractor to get header info
        header = _get_extracted_header(block)
        has_description = bool(header.comment) or bool(header.description)

        if not has_description:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' is missing a description",
                    context=block.name,
                    suggestion="Add '// Comment/Function:' to header or a Description REGION",
                )
            )

        return violations


@register_rule
class MissingChangelogRule(Rule):
    """D004: Block header missing changelog.

    This rule checks that the block header contains a changelog table
    documenting version history.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="D004",
            name="missing-changelog",
            description="Block header should contain a changelog table",
            severity=Severity.INFO,
            category=RuleCategory.DOCUMENTATION,
            rationale="Changelogs track version history and help understand how the "
            "block has evolved over time",
            examples_bad=["Block info header without Change log table"],
            examples_good=["// v1.0.0   | 07/04/2025 | Author | First released version"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for presence of changelog.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if changelog is missing.
        """
        # Skip TYPE blocks - UDTs don't have Block info headers
        if block.block_type == "TYPE":
            return []

        violations = []

        # Use extractor to get header info
        header = _get_extracted_header(block)
        has_header = bool(header.raw_header)

        if has_header and not header.changelog:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' header is missing changelog",
                    context=block.name,
                    suggestion="Add a Change log table with version, date, author, and changes",
                )
            )

        return violations


@register_rule
class MissingAuthorRule(Rule):
    """D005: Block header missing author.

    This rule checks that the block header contains an Author field.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="D005",
            name="missing-author",
            description="Block header should contain an Author field",
            severity=Severity.INFO,
            category=RuleCategory.DOCUMENTATION,
            rationale="Author attribution helps identify who to contact for questions "
            "and acknowledges contributions",
            examples_bad=["Block info header without // Author: line"],
            examples_good=["// Author:           MyProject"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for presence of author.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if author is missing.
        """
        # Skip TYPE blocks - UDTs don't have Block info headers
        if block.block_type == "TYPE":
            return []

        violations = []

        # Use extractor to get header info
        header = _get_extracted_header(block)
        has_header = bool(header.raw_header)

        if has_header and not header.author:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' header is missing Author field",
                    context=block.name,
                    suggestion="Add '// Author: YourName' to the Block info header",
                )
            )

        return violations


@register_rule
class EmptyDescriptionRegionRule(Rule):
    """D006: Description REGION exists but is empty.

    This rule checks that if a Description REGION exists, it contains
    meaningful content.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="D006",
            name="empty-description-region",
            description="Description REGION should not be empty",
            severity=Severity.WARNING,
            category=RuleCategory.DOCUMENTATION,
            rationale="An empty Description REGION suggests incomplete documentation. "
            "Either fill it with useful content or remove it.",
            examples_bad=["REGION Description\\n{ }\\nEND_REGION"],
            examples_good=["REGION Description\\n{ S7_MLC := 'Detailed description' }\\nEND_REGION"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for empty Description REGION.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if Description REGION is empty.
        """
        # Skip TYPE blocks - UDTs don't have Description REGIONs
        if block.block_type == "TYPE":
            return []

        violations = []

        # Check for description region presence and emptiness
        for network in block.networks:
            for region in network.regions:
                if region.name.lower() == "description":
                    # Check if content is essentially empty
                    content = region.content.strip()
                    # Remove common empty patterns like { S7_MLC := "" }
                    cleaned = content.replace("{", "").replace("}", "")
                    cleaned = cleaned.replace("S7_MLC", "").replace(":=", "")
                    cleaned = cleaned.replace('"', "").replace("'", "").strip()

                    if not cleaned:
                        violations.append(
                            self._create_violation(
                                message=f"Block '{block.name}' has empty Description REGION",
                                context=block.name,
                                suggestion=("Add meaningful description content or remove the REGION"),
                            )
                        )

        return violations


__all__ = [
    "MissingBlockHeaderRule",
    "MissingTitleRule",
    "MissingDescriptionRule",
    "MissingChangelogRule",
    "MissingAuthorRule",
    "EmptyDescriptionRegionRule",
]
