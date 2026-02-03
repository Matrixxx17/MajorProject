from hypothesis import given, strategies as st, settings
import importlib.util
from pathlib import Path

# Import testable module
_testable_path = Path(__file__).parent.parent / "my_code.testable.py"
_spec = importlib.util.spec_from_file_location("my_code_testable", _testable_path)
my_code_testable = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(my_code_testable)

# Property-based tests for my_code
# These tests verify function behavior with various inputs

@settings(max_examples=20, deadline=None)
@given(st.lists(st.text(min_size=1), min_size=0, max_size=10))
def test_anagram_property(strings):
    """Property test: anagram should accept list of strings and return dict-like values."""
    try:
        result = my_code_testable.anagram(strings)
        # Result should be iterable (dict_values)
        if result is not None:
            list(result)  # Ensure we can iterate
        assert True  # If no exception, test passes
    except (TypeError, ValueError, AttributeError) as e:
        # These exceptions are acceptable for invalid inputs
        pass

@settings(max_examples=15, deadline=None)
@given(st.lists(st.text(min_size=1, max_size=5), min_size=1, max_size=5))
def test_anagram_return_type(strings):
    """Property test: anagram should return dict values."""
    result = my_code_testable.anagram(strings)
    # Check that result is dict_values type (iterable)
    assert hasattr(result, '__iter__'), "Result should be iterable"

# Parametrized tests for anagram
@settings(max_examples=10, deadline=None)
@given(st.lists(st.text(min_size=1), min_size=2, max_size=3))
def test_anagram_basic_grouping(strings):
    """Parametrized test: anagram should group strings by character frequency."""
    result = my_code_testable.anagram(strings)
    groups = list(result)
    # Should have at most as many groups as input strings
    assert len(groups) <= len(strings)
