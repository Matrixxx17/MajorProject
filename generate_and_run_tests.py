import subprocess
from pathlib import Path
import sys
import os
import pytest

def generate_tests_pynguin(module_path: str, output_dir: str = "./generated_tests"):
    module_path = Path(module_path)
    if not module_path.exists():
        raise FileNotFoundError(f"Module not found: {module_path}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYNGUIN_DANGER_AWARE"] = "1"

    subprocess.run([
        sys.executable, "-m", "pynguin",
        "--project-path", str(module_path.parent),
        "--output-path", str(output_dir),
        "--module-name", module_path.stem,
        "--algorithm", "DYNAMOSA"
    ], check=True, env=env)

    print(f" Pynguin test files generated in {output_dir}")
    return Path(output_dir)

def create_property_tests(module_name: str, output_dir: Path):
    """
    Create property-based tests for is_even(n) with input reporting.
    """
    prop_test_file = output_dir / "test_properties.py"
    with open(prop_test_file, "w", encoding="utf-8") as f:
        f.write(f"""
from hypothesis import given, strategies as st
import {module_name}

@given(st.integers())
def test_is_even(n):
    result = {module_name}.is_even(n)
    assert result == (n % 2 == 0), f"Failed for input: {{n}}"
""")
    print(f" Property-based tests created: {prop_test_file}")
    return prop_test_file

def run_tests_summary(test_dir: Path):
    """
    Run pytest and print a concise summary with failing test names and inputs.
    """
    print(f"Running pytest on {test_dir} ...")

    # Run pytest with verbose output and capture results
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-q", "--disable-warnings", "--tb=short"],
        capture_output=True,
        text=True
    )

    # Print concise summary
    total = result.stdout.count("::")  # approximate test count
    passed = result.stdout.count("PASSED")
    failed = result.stdout.count("FAILED")

    print("\n===== Test Summary =====")
    print(f"Total tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("Failed tests and inputs:")
        for line in result.stdout.splitlines():
            if "FAILED" in line:
                print(f" - {line.strip()}")
            elif "Failed for input:" in line:
                print(f"   {line.strip()}")

    # Also print full Hypothesis falsifying example info for reference
    print("\n Detailed pytest output (for reference):")
    print(result.stdout)
    print(result.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_and_run_tests.py <python_file>")
        sys.exit(1)

    python_file = sys.argv[1]
    module_path = Path(python_file)
    module_name = module_path.stem

    try:
        test_dir = generate_tests_pynguin(python_file)
        create_property_tests(module_name, test_dir)
        run_tests_summary(test_dir)
    except subprocess.CalledProcessError as e:
        print(f" Pynguin or pytest failed with exit code {e.returncode}")
    except Exception as e:
        print(f" Error: {e}")
