"""Tests for analyzer modules."""

from plc_iol.analyzers.comparison import (
    DatabaseComparator,
    compare_databases,
)
from plc_iol.analyzers.validation import (
    DatabaseValidator,
    IssueSeverity,
    IssueType,
    ValidationIssue,
    ValidationResult,
    validate_database,
)
from plc_iol.core.models import IODatabase, IOPoint


class TestDatabaseComparator:
    """Tests for DatabaseComparator class."""

    def test_compare_identical_databases(self, sample_database):
        comparator = DatabaseComparator()
        result = comparator.compare(sample_database, sample_database)

        assert result.has_changes is False
        assert result.added_count == 0
        assert result.removed_count == 0
        assert result.modified_count == 0
        assert result.unchanged_count == len(sample_database)

    def test_compare_detect_added(self):
        source = IODatabase()
        source.add(IOPoint(mnemonic="DI_TEST_1", signal_name="Test 1"))

        target = IODatabase()
        target.add(IOPoint(mnemonic="DI_TEST_1", signal_name="Test 1"))
        target.add(IOPoint(mnemonic="DI_TEST_2", signal_name="Test 2"))

        comparator = DatabaseComparator()
        result = comparator.compare(source, target)

        assert result.added_count == 1
        assert result.get_added()[0].mnemonic == "DI_TEST_2"

    def test_compare_detect_removed(self):
        source = IODatabase()
        source.add(IOPoint(mnemonic="DI_TEST_1", signal_name="Test 1"))
        source.add(IOPoint(mnemonic="DI_TEST_2", signal_name="Test 2"))

        target = IODatabase()
        target.add(IOPoint(mnemonic="DI_TEST_1", signal_name="Test 1"))

        comparator = DatabaseComparator()
        result = comparator.compare(source, target)

        assert result.removed_count == 1
        assert result.get_removed()[0].mnemonic == "DI_TEST_2"

    def test_compare_detect_modified(self):
        source = IODatabase()
        source.add(IOPoint(mnemonic="DI_TEST", signal_name="Original"))

        target = IODatabase()
        target.add(IOPoint(mnemonic="DI_TEST", signal_name="Modified"))

        comparator = DatabaseComparator()
        result = comparator.compare(source, target)

        assert result.modified_count == 1
        modified = result.get_modified()[0]
        assert modified.mnemonic == "DI_TEST"
        assert any(fd.field_name == "signal_name" for fd in modified.field_diffs)

    def test_compare_field_diffs(self):
        source = IODatabase()
        source.add(
            IOPoint(
                mnemonic="DI_TEST",
                signal_name="Test",
                plc_address="%I1.0",
            )
        )

        target = IODatabase()
        target.add(
            IOPoint(
                mnemonic="DI_TEST",
                signal_name="Test",
                plc_address="%I2.0",  # Changed
            )
        )

        comparator = DatabaseComparator()
        result = comparator.compare(source, target)

        modified = result.get_modified()[0]
        address_diff = next(fd for fd in modified.field_diffs if fd.field_name == "plc_address")
        assert address_diff.source_value == "%I1.0"
        assert address_diff.target_value == "%I2.0"

    def test_compare_ignore_fields(self):
        source = IODatabase()
        source.add(IOPoint(mnemonic="DI_TEST", signal_name="Test", plc_address="%I1.0"))

        target = IODatabase()
        target.add(IOPoint(mnemonic="DI_TEST", signal_name="Test", plc_address="%I2.0"))

        comparator = DatabaseComparator(ignore_fields=["plc_address"])
        result = comparator.compare(source, target)

        # Should not detect change since plc_address is ignored
        assert result.modified_count == 0

    def test_compare_case_insensitive(self):
        source = IODatabase()
        source.add(IOPoint(mnemonic="DI_TEST", signal_name="test signal"))

        target = IODatabase()
        target.add(IOPoint(mnemonic="DI_TEST", signal_name="TEST SIGNAL"))

        comparator = DatabaseComparator(case_sensitive=False)
        result = comparator.compare(source, target)

        assert result.modified_count == 0  # Should be considered equal

    def test_compare_summary(self, sample_database):
        comparator = DatabaseComparator()
        result = comparator.compare(sample_database, sample_database)

        summary = result.summary()
        assert "Source points:" in summary
        assert "Target points:" in summary


class TestCompareConvenience:
    """Tests for compare_databases convenience function."""

    def test_compare_databases(self, sample_database):
        result = compare_databases(sample_database, sample_database)
        assert result.has_changes is False


class TestDatabaseValidator:
    """Tests for DatabaseValidator class."""

    def test_validate_valid_database(self, sample_database):
        validator = DatabaseValidator()
        result = validator.validate(sample_database)

        # May have warnings but should have no errors
        # (depends on what's in sample_database)
        assert result.points_checked == len(sample_database)

    def test_validate_duplicate_addresses(self):
        db = IODatabase()
        db.add(IOPoint(mnemonic="DI_TEST_1", signal_name="Test 1", plc_address="%I1.0"))
        db.add(IOPoint(mnemonic="DI_TEST_2", signal_name="Test 2", plc_address="%I1.0"))

        validator = DatabaseValidator()
        result = validator.validate(db)

        assert result.error_count >= 1
        assert any(i.issue_type == IssueType.DUPLICATE_ADDRESS for i in result.issues)

    def test_validate_invalid_mnemonic(self):
        db = IODatabase()
        db.add(IOPoint(mnemonic="INVALID@MNEMONIC", signal_name="Test"))

        validator = DatabaseValidator()
        result = validator.validate(db)

        assert any(i.issue_type == IssueType.INVALID_MNEMONIC for i in result.issues)

    def test_validate_missing_signal_name(self):
        db = IODatabase()
        db.add(IOPoint(mnemonic="DI_TEST", signal_name=""))

        validator = DatabaseValidator()
        result = validator.validate(db)

        assert any(
            i.issue_type == IssueType.MISSING_REQUIRED_FIELD and i.field_name == "signal_name"
            for i in result.issues
        )

    def test_validate_invalid_address_format(self):
        db = IODatabase()
        db.add(IOPoint(mnemonic="DI_TEST", signal_name="Test", plc_address="INVALID"))

        validator = DatabaseValidator()
        result = validator.validate(db)

        assert any(i.issue_type == IssueType.INVALID_ADDRESS_FORMAT for i in result.issues)

    def test_validate_orphan_points(self, sample_config):
        db = IODatabase()
        db.add(
            IOPoint(
                mnemonic="DI_TEST",
                signal_name="Test",
                functional_group="UNKNOWN_GROUP",
            )
        )

        validator = DatabaseValidator(config=sample_config)
        result = validator.validate(db)

        assert any(i.issue_type == IssueType.ORPHAN_POINT for i in result.issues)

    def test_validate_result_methods(self):
        result = ValidationResult()
        result.issues = [
            ValidationIssue(
                issue_type=IssueType.DUPLICATE_ADDRESS,
                severity=IssueSeverity.ERROR,
                message="Test error",
            ),
            ValidationIssue(
                issue_type=IssueType.MISSING_REQUIRED_FIELD,
                severity=IssueSeverity.WARNING,
                message="Test warning",
            ),
        ]
        result.points_checked = 10

        assert result.error_count == 1
        assert result.warning_count == 1
        assert result.is_valid is False
        assert len(result.get_errors()) == 1
        assert len(result.get_warnings()) == 1
        assert "FAILED" in result.summary()


class TestValidateConvenience:
    """Tests for validate_database convenience function."""

    def test_validate_database(self, sample_database):
        result = validate_database(sample_database)
        assert result.points_checked == len(sample_database)
