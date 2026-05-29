"""Naming conventions and mnemonic validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from plc_iol.core.models import IOCategory

if TYPE_CHECKING:
    from plc_iol.core.config import NamingConfig


@dataclass
class MnemonicParts:
    """Parsed components of a mnemonic."""

    io_category: str | None = None
    location: str | None = None
    signal: str | None = None
    full: str = ""

    @property
    def io_category_enum(self) -> IOCategory | None:
        """Get IO category as enum."""
        if self.io_category:
            return IOCategory.from_mnemonic_prefix(self.io_category)
        return None


@dataclass
class ValidationResult:
    """Result of mnemonic validation."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]
    parsed: MnemonicParts | None = None


class NamingConvention:
    """
    Handles mnemonic naming conventions and validation.

    The default pattern is: {io_category}_{location}_{signal}
    Example: DI_LOC1_PUMP_START

    Components:
    - io_category: DI, DO, AI, AO, SDI, SDO
    - location: LOC1, LOC2, etc. (configurable)
    - signal: Descriptive name using underscores
    """

    # Standard I/O category prefixes
    IO_CATEGORIES = {"DI", "DO", "AI", "AO", "SDI", "SDO", "SAI", "SAO"}

    def __init__(
        self,
        locations: list[str] | None = None,
        pattern: str = "{io_category}_{location}_{signal}",
        max_length: int = 64,
        allowed_characters: str = "A-Z0-9_",
    ):
        """
        Initialize naming convention.

        Args:
            locations: Valid location identifiers (e.g., ["LOC1", "LOC2"])
            pattern: Naming pattern (default: "{io_category}_{location}_{signal}")
            max_length: Maximum mnemonic length
            allowed_characters: Regex character class for allowed characters
        """
        self.locations = set(locations) if locations else set()
        self.pattern = pattern
        self.max_length = max_length
        self.allowed_characters = allowed_characters
        self._char_regex = re.compile(f"^[{allowed_characters}]+$")

    @classmethod
    def from_config(cls, config: NamingConfig) -> NamingConvention:
        """Create from NamingConfig."""
        return cls(
            locations=config.locations,
            pattern=config.pattern,
            max_length=config.max_length,
            allowed_characters=config.allowed_characters,
        )

    def parse(self, mnemonic: str) -> MnemonicParts:
        """
        Parse a mnemonic into its components.

        Args:
            mnemonic: The mnemonic to parse (e.g., "DI_LCP_PUMP_START")

        Returns:
            MnemonicParts with extracted components
        """
        parts = MnemonicParts(full=mnemonic)

        if not mnemonic:
            return parts

        segments = mnemonic.split("_")
        if not segments:
            return parts

        # First segment should be IO category
        if segments[0].upper() in self.IO_CATEGORIES:
            parts.io_category = segments[0].upper()
            segments = segments[1:]

        if not segments:
            return parts

        # Second segment is typically location
        if segments:
            # Always capture the location segment
            parts.location = segments[0].upper()
            segments = segments[1:]

        # Remaining segments form the signal name
        if segments:
            parts.signal = "_".join(segments)

        return parts

    def validate(self, mnemonic: str) -> ValidationResult:
        """
        Validate a mnemonic against naming conventions.

        Args:
            mnemonic: The mnemonic to validate

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors = []
        warnings = []

        if not mnemonic:
            return ValidationResult(
                is_valid=False,
                errors=["Mnemonic cannot be empty"],
                warnings=[],
            )

        # Check length
        if len(mnemonic) > self.max_length:
            errors.append(f"Mnemonic exceeds maximum length of {self.max_length}")

        # Check characters
        if not self._char_regex.match(mnemonic.upper()):
            errors.append(f"Mnemonic contains invalid characters. " f"Allowed: {self.allowed_characters}")

        # Parse and validate structure
        parts = self.parse(mnemonic)

        # Check IO category
        if parts.io_category is None:
            errors.append(
                f"Mnemonic must start with a valid I/O category: " f"{', '.join(sorted(self.IO_CATEGORIES))}"
            )

        # Check signal part exists
        if not parts.signal:
            warnings.append("Mnemonic should include a signal description")

        # Check for common issues
        if "__" in mnemonic:
            warnings.append("Mnemonic contains consecutive underscores")

        if mnemonic.startswith("_") or mnemonic.endswith("_"):
            warnings.append("Mnemonic should not start or end with underscore")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            parsed=parts,
        )

    def suggest_mnemonic(
        self,
        io_category: str | IOCategory,
        location: str,
        signal: str,
    ) -> str:
        """
        Generate a mnemonic following the naming convention.

        Args:
            io_category: I/O category (DI, DO, AI, AO, SDI, SDO)
            location: Location identifier
            signal: Signal description

        Returns:
            Generated mnemonic
        """
        if isinstance(io_category, IOCategory):
            io_category = io_category.value

        # Clean and normalize components
        io_category = io_category.upper().strip()
        location = location.upper().strip().replace(" ", "_")
        signal = signal.upper().strip().replace(" ", "_")

        # Remove any special characters
        signal = re.sub(r"[^A-Z0-9_]", "", signal)

        # Build mnemonic from pattern
        mnemonic = self.pattern.format(
            io_category=io_category,
            location=location,
            signal=signal,
        )

        # Truncate if necessary
        if len(mnemonic) > self.max_length:
            mnemonic = mnemonic[: self.max_length]

        return mnemonic

    def normalize(self, mnemonic: str) -> str:
        """
        Normalize a mnemonic (uppercase, clean whitespace).

        Args:
            mnemonic: The mnemonic to normalize

        Returns:
            Normalized mnemonic
        """
        return mnemonic.upper().strip().replace(" ", "_")


def validate_mnemonic(
    mnemonic: str,
    locations: list[str] | None = None,
    max_length: int = 64,
) -> ValidationResult:
    """
    Convenience function to validate a mnemonic.

    Args:
        mnemonic: The mnemonic to validate
        locations: Valid location identifiers
        max_length: Maximum mnemonic length

    Returns:
        ValidationResult with validation status
    """
    convention = NamingConvention(locations=locations, max_length=max_length)
    return convention.validate(mnemonic)


def extract_io_category(mnemonic: str) -> IOCategory | None:
    """
    Extract IO category from a mnemonic.

    Args:
        mnemonic: The mnemonic (e.g., "DI_LCP_PUMP_START")

    Returns:
        IOCategory enum or None
    """
    if not mnemonic:
        return None
    parts = mnemonic.split("_")
    if parts:
        return IOCategory.from_mnemonic_prefix(parts[0])
    return None
