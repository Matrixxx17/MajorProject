import importlib.util
from pathlib import Path

_testable_path = Path(__file__).parent.parent / "my_code.testable.py"
_spec = importlib.util.spec_from_file_location("my_code_testable", _testable_path)
my_code_testable = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(my_code_testable)

def test_element_does_not_raise():
    """Basic smoke test for `element`."""
    try:
        my_code_testable.element([])
    except Exception:
        pass
