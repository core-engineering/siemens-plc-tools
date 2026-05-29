"""Tests for testing module discovery functions."""

from pathlib import Path

from plc_code.testing.discovery import (
    _camel_to_snake,
    _generate_test_file_candidates,
    _snake_to_camel,
    build_test_registry,
    discover_test_file,
)


class TestCamelToSnake:
    """Tests for CamelCase to snake_case conversion."""

    def test_simple_camel_case(self) -> None:
        """Test simple CamelCase conversion."""
        assert _camel_to_snake("HelloWorld") == "hello_world"

    def test_single_word(self) -> None:
        """Test single word stays lowercase."""
        assert _camel_to_snake("Hello") == "hello"

    def test_acronym(self) -> None:
        """Test acronym handling."""
        assert _camel_to_snake("HTTPServer") == "http_server"

    def test_already_snake_case(self) -> None:
        """Test already snake_case stays the same."""
        assert _camel_to_snake("hello_world") == "hello_world"

    def test_lowercase(self) -> None:
        """Test lowercase stays the same."""
        assert _camel_to_snake("hello") == "hello"


class TestSnakeToCamel:
    """Tests for snake_case to CamelCase conversion."""

    def test_simple_snake_case(self) -> None:
        """Test simple snake_case conversion."""
        assert _snake_to_camel("hello_world") == "HelloWorld"

    def test_single_word(self) -> None:
        """Test single word gets capitalized."""
        assert _snake_to_camel("hello") == "Hello"

    def test_multiple_underscores(self) -> None:
        """Test multiple underscores."""
        assert _snake_to_camel("one_two_three") == "OneTwoThree"


class TestGenerateTestFileCandidates:
    """Tests for test file candidate generation."""

    def test_camel_case_block(self) -> None:
        """Test candidates for CamelCase block name."""
        candidates = _generate_test_file_candidates("MotorStarter")

        assert "test_MotorStarter.py" in candidates
        assert "test_motorstarter.py" in candidates
        assert "test_motor_starter.py" in candidates
        assert "test_fbMotorStarter.py" in candidates

    def test_simple_name(self) -> None:
        """Test candidates for simple block name."""
        candidates = _generate_test_file_candidates("Timer")

        assert "test_Timer.py" in candidates
        assert "test_timer.py" in candidates
        assert "test_fbTimer.py" in candidates
        assert "test_fcTimer.py" in candidates

    def test_name_with_underscore(self) -> None:
        """Test candidates for name with underscore."""
        candidates = _generate_test_file_candidates("My_Block")

        assert "test_My_Block.py" in candidates
        assert "test_my_block.py" in candidates
        assert "test_myblock.py" in candidates  # Underscores removed


class TestDiscoverTestFile:
    """Tests for test file discovery."""

    def test_discover_nonexistent_file(self, tmp_path: Path) -> None:
        """Test discovery when no test file exists."""
        result = discover_test_file("NonExistentBlock", [tmp_path])
        assert result is None

    def test_discover_exact_match(self, tmp_path: Path) -> None:
        """Test discovery with exact name match."""
        test_file = tmp_path / "test_MyBlock.py"
        test_file.write_text("# test file")

        result = discover_test_file("MyBlock", [tmp_path])
        assert result == test_file

    def test_discover_lowercase_match(self, tmp_path: Path) -> None:
        """Test discovery with lowercase match."""
        test_file = tmp_path / "test_myblock.py"
        test_file.write_text("# test file")

        result = discover_test_file("MyBlock", [tmp_path])
        assert result == test_file

    def test_discover_snake_case_match(self, tmp_path: Path) -> None:
        """Test discovery with snake_case match."""
        test_file = tmp_path / "test_motor_starter.py"
        test_file.write_text("# test file")

        result = discover_test_file("MotorStarter", [tmp_path])
        assert result == test_file

    def test_discover_fb_prefix_match(self, tmp_path: Path) -> None:
        """Test discovery with fb prefix match."""
        test_file = tmp_path / "test_fbMyBlock.py"
        test_file.write_text("# test file")

        result = discover_test_file("MyBlock", [tmp_path])
        assert result == test_file

    def test_discover_in_subdirectory(self, tmp_path: Path) -> None:
        """Test discovery in subdirectory."""
        subdir = tmp_path / "plc"
        subdir.mkdir()
        test_file = subdir / "test_myblock.py"
        test_file.write_text("# test file")

        result = discover_test_file("MyBlock", [tmp_path])
        assert result == test_file

    def test_discover_with_multiple_dirs(self, tmp_path: Path) -> None:
        """Test discovery searches multiple directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        test_file = dir2 / "test_myblock.py"
        test_file.write_text("# test file")

        result = discover_test_file("MyBlock", [dir1, dir2])
        assert result == test_file

    def test_discover_nonexistent_directory(self) -> None:
        """Test discovery handles nonexistent directories."""
        result = discover_test_file("MyBlock", [Path("/nonexistent/path")])
        assert result is None


class TestBuildTestRegistry:
    """Tests for test registry building."""

    def test_empty_block_list(self, tmp_path: Path) -> None:
        """Test registry with no blocks."""
        registry = build_test_registry([], [tmp_path])
        assert registry == {}

    def test_registry_with_matches(self, tmp_path: Path) -> None:
        """Test registry finds matching test files."""
        (tmp_path / "test_block_a.py").write_text("# test")
        (tmp_path / "test_block_b.py").write_text("# test")

        registry = build_test_registry(["BlockA", "BlockB", "BlockC"], [tmp_path])

        assert "BlockA" in registry
        assert "BlockB" in registry
        assert "BlockC" not in registry
        assert registry["BlockA"] == tmp_path / "test_block_a.py"

    def test_registry_preserves_all_found(self, tmp_path: Path) -> None:
        """Test registry includes all discovered test files."""
        (tmp_path / "test_one.py").write_text("# test")
        (tmp_path / "test_two.py").write_text("# test")

        registry = build_test_registry(["One", "Two", "Three"], [tmp_path])

        assert len(registry) == 2
        assert "Three" not in registry
