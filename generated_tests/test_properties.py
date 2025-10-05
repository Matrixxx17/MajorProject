
from hypothesis import given, strategies as st
import my_code

@given(st.integers())
def test_is_even(n):
    result = my_code.is_even(n)
    assert result == (n % 2 == 0), f"Failed for input: {n}"
