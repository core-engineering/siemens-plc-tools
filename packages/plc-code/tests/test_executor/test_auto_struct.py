"""Tests for _AutoStruct and _dict_to_auto_struct helper.

Covers integer-keyed dict inputs (e.g. {0: 0.0, 1: 1.0}), which arise when
PLC test code passes array-like data as Python dicts with integer keys.
"""

from plc_code.executor.runtime import _AutoStruct, _dict_to_auto_struct


class TestAutoStruct:
    """Tests for _AutoStruct basic behaviour."""

    def test_attribute_read_write(self) -> None:
        """Attribute access stores and retrieves values."""
        s = _AutoStruct()
        s.foo = 42
        assert s.foo == 42

    def test_item_read_write(self) -> None:
        """Integer item access stores and retrieves values."""
        s = _AutoStruct()
        s[0] = 1.5
        s[1] = 2.5
        assert s[0] == 1.5
        assert s[1] == 2.5

    def test_unset_attribute_autovivifies(self) -> None:
        """Unset attribute access returns a new _AutoStruct."""
        s = _AutoStruct()
        child = s.missing
        assert isinstance(child, _AutoStruct)

    def test_unset_item_autovivifies(self) -> None:
        """Unset item access returns a new _AutoStruct."""
        s = _AutoStruct()
        child = s[99]
        assert isinstance(child, _AutoStruct)


class TestDictToAutoStruct:
    """Tests for _dict_to_auto_struct conversion."""

    def test_string_keyed_dict_becomes_attributes(self) -> None:
        """String keys should be accessible as attributes."""
        result = _dict_to_auto_struct({"alpha": 0.5, "d": 1.0})
        assert result.alpha == 0.5
        assert result.d == 1.0

    def test_integer_keyed_dict_accessible_by_index(self) -> None:
        """Integer keys must be stored in _items so [n] access works.

        This is the critical regression: {0: 0.0, 1: 1.0} passed as
        mdhParams.angularOffsets must support angularOffsets[0], angularOffsets[1].
        """
        result = _dict_to_auto_struct({0: 0.0, 1: 10.0, 2: 20.0, 3: 30.0})
        assert result[0] == 0.0
        assert result[1] == 10.0
        assert result[2] == 20.0
        assert result[3] == 30.0

    def test_nested_integer_keyed_dict(self) -> None:
        """Nested integer-keyed dict (e.g. angularOffsets) is accessible by index."""
        raw = {
            "angularOffsets": {0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0},
            "tau": 0.5,
        }
        result = _dict_to_auto_struct(raw)
        assert result.tau == 0.5
        assert result.angularOffsets[0] == 1.0
        assert result.angularOffsets[1] == 2.0
        assert result.angularOffsets[2] == 3.0
        assert result.angularOffsets[3] == 4.0

    def test_nested_string_keyed_dict_in_list(self) -> None:
        """A list of dicts is recursively converted."""
        raw = [{"alpha": 0.1}, {"alpha": 0.2}]
        result = _dict_to_auto_struct(raw)
        assert result[0].alpha == 0.1
        assert result[1].alpha == 0.2

    def test_scalar_passthrough(self) -> None:
        """Non-dict, non-list values are returned unchanged."""
        assert _dict_to_auto_struct(3.14) == 3.14
        assert _dict_to_auto_struct("hello") == "hello"
        assert _dict_to_auto_struct(True) is True

    def test_mixed_nested_struct_with_integer_keyed_inner(self) -> None:
        """Full mdhParams-like structure with nested integer-indexed arrays.

        jointParams has integer keys 1..6, each entry has alpha/d/r/qOffset.
        """
        raw = {
            "angularOffsets": {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0},
            "tau": 0.0,
            "theta": 0.0,
            "jointParams": {
                1: {"alpha": 0.1, "d": 0.2, "r": 0.3, "qOffset": 0.0},
                2: {"alpha": 0.4, "d": 0.5, "r": 0.6, "qOffset": 0.0},
            },
        }
        result = _dict_to_auto_struct(raw)
        assert result.angularOffsets[0] == 0.0
        assert result.tau == 0.0
        assert result.jointParams[1].alpha == 0.1
        assert result.jointParams[1].d == 0.2
        assert result.jointParams[2].r == 0.6
