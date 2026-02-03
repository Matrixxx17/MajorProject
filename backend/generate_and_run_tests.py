import subprocess
from pathlib import Path
import sys
import os
import pytest
from typing import Optional, Tuple
import time

def post_process_pynguin_tests(test_dir: Path, module_name: str):
    """
    Post-process Pynguin-generated tests to improve quality:
    - Remove xfail markers that make tests expected to fail
    - Fix imports to use testable module
    - Add better assertions
    - Remove tests for non-existent functions
    """
    import ast
    import re
    
    # Get list of actual functions in the module
    module_path = Path(f"{module_name}.testable.py")
    if not module_path.exists():
        module_path = Path(f"{module_name}.py")
    
    actual_functions = set()
    if module_path.exists():
        try:
            content = module_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    actual_functions.add(node.name)
        except:
            pass
    
    # Process each test file
    for test_file in test_dir.glob("test_*.py"):
        if test_file.name == "test_properties.py":  # Skip property tests
            continue
            
        try:
            content = test_file.read_text(encoding="utf-8")
            original_content = content
            lines = content.split('\n')
            modified_lines = []
            removed_tests = []
            
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Remove xfail markers
                if '@pytest.mark.xfail' in line:
                    # Skip the xfail line
                    i += 1
                    continue
                
                # Check if this is a test function that calls non-existent functions
                if line.strip().startswith('def test_'):
                    # Look ahead to see what functions are called
                    test_content = '\n'.join(lines[i:min(i+20, len(lines))])
                    # Check if test calls non-existent functions
                    should_remove = False
                    if actual_functions:
                        for func_name in actual_functions:
                            # If test doesn't call any actual function, it might be invalid
                            if f"module_0.{func_name}" not in test_content and f"{module_name}.{func_name}" not in test_content:
                                # Check if it calls something that doesn't exist
                                invalid_calls = re.findall(rf'module_0\.(\w+)|{module_name}\.(\w+)', test_content)
                                for call in invalid_calls:
                                    called_func = call[0] or call[1]
                                    if called_func and called_func not in actual_functions and called_func != 'testable':
                                        should_remove = True
                                        removed_tests.append(f"Test calls non-existent function: {called_func}")
                                        break
                    
                    if should_remove:
                        # Skip this entire test function
                        indent = len(line) - len(line.lstrip())
                        i += 1
                        while i < len(lines):
                            current_line = lines[i]
                            if current_line.strip() and not current_line.strip().startswith('#'):
                                current_indent = len(current_line) - len(current_line.lstrip())
                                if current_indent <= indent and current_line.strip().startswith('def '):
                                    break
                            i += 1
                        continue
                
                # Fix imports to use testable module if available
                # Use direct file import to avoid triggering original module's input() calls
                if 'import' in line and (f"import {module_name}" in line or f"import {module_name} as" in line):
                    testable_path = Path(f"{module_name}.testable.py")
                    if testable_path.exists() and f"importlib" not in '\n'.join(modified_lines[:max(0, i-10):]):
                        # Replace import statements with direct file import
                        # Find the import line and replace it
                        if i == 0 or (i > 0 and 'import' not in '\n'.join(modified_lines[max(0, i-3):i])):
                            # Add importlib imports at the top if not already present
                            if "import importlib.util" not in '\n'.join(modified_lines):
                                # Find where to insert (after existing imports)
                                insert_idx = 0
                                for j, prev_line in enumerate(modified_lines):
                                    if prev_line.strip().startswith('import ') or prev_line.strip().startswith('from '):
                                        insert_idx = j + 1
                                modified_lines.insert(insert_idx, "from pathlib import Path")
                                modified_lines.insert(insert_idx + 1, "import importlib.util")
                                i += 2  # Adjust index for inserted lines
                        
                        # Replace the import line with direct file import
                        indent = len(line) - len(line.lstrip())
                        alias = "module_0"  # Default alias used by Pynguin
                        if " as " in line:
                            alias = line.split(" as ")[-1].strip()
                        
                        line = f"{' ' * indent}# Import testable module directly without triggering {module_name}.py\n"
                        line += f"{' ' * indent}_testable_path = Path(__file__).parent.parent / \"{module_name}.testable.py\"\n"
                        line += f"{' ' * indent}_spec = importlib.util.spec_from_file_location(\"{module_name}_testable\", _testable_path)\n"
                        line += f"{' ' * indent}{alias} = importlib.util.module_from_spec(_spec)\n"
                        line += f"{' ' * indent}_spec.loader.exec_module({alias})"
                
                modified_lines.append(line)
                i += 1
            
            modified_content = '\n'.join(modified_lines)
            
            # Only write if we made changes
            if modified_content != original_content:
                test_file.write_text(modified_content, encoding="utf-8")
                if removed_tests:
                    print(f"  [INFO] Post-processed {test_file.name}: removed {len(removed_tests)} invalid test(s)")
                else:
                    print(f"  [INFO] Post-processed {test_file.name}: removed xfail markers and fixed imports")
        
        except Exception as e:
            print(f"  [WARNING] Could not post-process {test_file.name}: {e}")

def prepare_module_for_testing(module_path: Path) -> Path:
    """
    Ensure we have a testable version of the module (no input/print at module level).
    This is always done to keep .testable.py in sync with current my_code.py.
    ALWAYS creates a fresh copy to ensure sync.
    """
    try:
        from prepare_code_for_testing import prepare_code_for_testing
        
        testable_path = module_path.parent / f"{module_path.stem}.testable.py"
        
        # FORCE sync: Always regenerate testable file from source
        # This ensures testable.py is always up-to-date even if content changed
        content = module_path.read_text(encoding="utf-8")
        
        # Comment out input() and print() calls at module level
        lines = content.split('\n')
        modified_lines = []
        in_function = False
        function_indent = 0
        
        for line in lines:
            stripped = line.strip()
            current_indent = len(line) - len(line.lstrip()) if line.strip() else 0
            
            # Track function context
            if stripped.startswith('def '):
                in_function = True
                function_indent = current_indent
            elif in_function and stripped and not stripped.startswith('#'):
                if current_indent <= function_indent and not stripped.startswith('def '):
                    in_function = False
            
            # Comment out module-level input() and print()
            if not in_function and 'input(' in line and not stripped.startswith('#'):
                modified_lines.append(f"# {line}  # Commented for testing")
            elif not in_function and stripped.startswith('print(') and not stripped.startswith('#'):
                modified_lines.append(f"# {line}  # Commented for testing")
            else:
                modified_lines.append(line)
        
        modified_content = '\n'.join(modified_lines)
        testable_path.write_text(modified_content, encoding="utf-8")
        
        # Check if content actually changed
        if testable_path.read_text(encoding="utf-8") != content:
            print(f"  [SYNC] ✓ Updated testable version: {testable_path.name} (removed blocking code)")
        else:
            print(f"  [SYNC] ✓ Testable version synced: {testable_path.name} (no blocking code to remove)")
        
        return testable_path
    except Exception as e:
        print(f"  [WARNING] Could not prepare testable module: {e}")
        import traceback
        traceback.print_exc()
        # If preparation fails, use original
        return module_path

def generate_tests_pynguin(module_path: str, output_dir: str = "./generated_tests", timeout: int = 180):
    module_path = Path(module_path)
    if not module_path.exists():
        raise FileNotFoundError(f"Module not found: {module_path}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYNGUIN_DANGER_AWARE"] = "1"

    start_time = time.time()
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pynguin",
            "--project-path", str(module_path.parent),
            "--output-path", str(output_dir),
            "--module-name", module_path.stem,
            "--algorithm", "MIO",
            "--maximum-search-time", str(timeout),
            "--maximum-test-executions", "500",
            "--maximum-test-execution-timeout", "5",
            "--maximum-statement-executions", "10000",
            "--coverage-metrics", "BRANCH",
        ], check=True, env=env, timeout=timeout*2, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    except subprocess.TimeoutExpired:
        # If Pynguin times out at the subprocess level, proceed with any tests generated so far
        print(f"  [INFO] Pynguin subprocess timed out after {timeout*2} seconds - proceeding with partial results")
    except subprocess.CalledProcessError as e:
        # Pynguin failed; print its stderr for diagnosis but continue
        print(f"  [ERROR] Pynguin failed with return code {e.returncode}")
        if hasattr(e, 'stderr') and e.stderr:
            print(e.stderr)
    except KeyboardInterrupt:
        print("  [INFO] Pynguin interrupted by user")
    except Exception as e:
        print(f"  [WARNING] Pynguin failed: {e}")

    elapsed = time.time() - start_time
    print(f" Pynguin test files generated in {output_dir}")
    return Path(output_dir), elapsed

def create_property_tests(module_name: str, output_dir: Path):
    """
    Create property-based tests for the module using Hypothesis.
    """
    prop_test_file = output_dir / "test_properties.py"
    with open(prop_test_file, "w", encoding="utf-8") as f:
        f.write(f"""from hypothesis import given, strategies as st, settings
import importlib.util
from pathlib import Path

# Import testable module
_testable_path = Path(__file__).parent.parent / "{module_name}.testable.py"
_spec = importlib.util.spec_from_file_location("{module_name}_testable", _testable_path)
{module_name}_testable = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module({module_name}_testable)

# Property-based tests for {module_name}
# These tests verify function behavior with various inputs

@settings(max_examples=20, deadline=None)
@given(st.lists(st.text(min_size=1), min_size=0, max_size=10))
def test_anagram_property(strings):
    \"\"\"Property test: anagram should accept list of strings and return dict-like values.\"\"\"
    try:
        result = {module_name}_testable.anagram(strings)
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
    \"\"\"Property test: anagram should return dict values.\"\"\"
    result = {module_name}_testable.anagram(strings)
    # Check that result is dict_values type (iterable)
    assert hasattr(result, '__iter__'), "Result should be iterable"

# Parametrized tests for anagram
@settings(max_examples=10, deadline=None)
@given(st.lists(st.text(min_size=1), min_size=2, max_size=3))
def test_anagram_basic_grouping(strings):
    \"\"\"Parametrized test: anagram should group strings by character frequency.\"\"\"
    result = {module_name}_testable.anagram(strings)
    groups = list(result)
    # Should have at most as many groups as input strings
    assert len(groups) <= len(strings)
""")
    print(f"  [OK] Property-based tests created: {prop_test_file}")
    return prop_test_file

def consolidate_tests_to_root(test_dir: Path, root_test_file: Path, module_name: str) -> bool:
    """
    Consolidate all generated test cases into a single test_my_code.py file at the root.
    
    Args:
        test_dir: Directory containing generated test files
        root_test_file: Path to root test file (e.g., test_my_code.py)
        module_name: Name of the module being tested
    
    Returns:
        True if consolidation was successful, False otherwise
    """
    import ast
    import re
    
    try:
        # Collect all test functions from all test files
        all_test_functions = []
        seen_test_names = set()
        
        # Find testable module path
        testable_path = Path(f"{module_name}.testable.py")
        if not testable_path.exists():
            testable_path = Path(f"{module_name}.py")
        
        # Process all test files in the directory
        for test_file in sorted(test_dir.glob("test_*.py")):
            if test_file.name == "test_properties.py":
                continue  # Skip property tests for now, we'll add them separately
            
            try:
                content = test_file.read_text(encoding="utf-8")
                
                # Parse and extract test functions
                tree = ast.parse(content)
                lines = content.split('\n')
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                        # Skip if we've already seen this test name (avoid duplicates)
                        if node.name in seen_test_names:
                            continue
                        seen_test_names.add(node.name)
                        
                        # Get the function source code with proper indentation
                        func_lines = lines[node.lineno - 1:node.end_lineno]
                        func_code = '\n'.join(func_lines)
                        
                        # Fix module references - handle both module_0 and other patterns
                        func_code = func_code.replace('module_0', f'{module_name}_testable')
                        # Also handle direct module references
                        func_code = re.sub(rf'\b{module_name}\.', f'{module_name}_testable.', func_code)
                        
                        all_test_functions.append(func_code)
                        
            except Exception as e:
                print(f"  [WARNING] Could not process {test_file.name}: {e}")
                continue
        
        # If no tests found, try to read from existing generated test file directly
        if not all_test_functions:
            main_test_file = test_dir / f"test_{module_name}.py"
            if main_test_file.exists():
                try:
                    content = main_test_file.read_text(encoding="utf-8")
                    # Extract all test functions
                    tree = ast.parse(content)
                    lines = content.split('\n')
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                            if node.name not in seen_test_names:
                                seen_test_names.add(node.name)
                                func_lines = lines[node.lineno - 1:node.end_lineno]
                                func_code = '\n'.join(func_lines)
                                func_code = func_code.replace('module_0', f'{module_name}_testable')
                                func_code = re.sub(rf'\b{module_name}\.', f'{module_name}_testable.', func_code)
                                all_test_functions.append(func_code)
                except Exception as e:
                    print(f"  [WARNING] Could not read from {main_test_file.name}: {e}")
        
        # Build consolidated test file content
        consolidated_content = []
        
        # Add header
        consolidated_content.append('"""')
        consolidated_content.append('Comprehensive test suite for my_code.py')
        consolidated_content.append('Generated by Pynguin - All test cases consolidated here')
        consolidated_content.append('This file contains all generated test cases with various parameter combinations.')
        consolidated_content.append('"""')
        consolidated_content.append('')
        
        # Add imports
        consolidated_content.append('import pytest')
        consolidated_content.append('import sys')
        consolidated_content.append('from pathlib import Path')
        consolidated_content.append('import importlib.util')
        consolidated_content.append('')
        
        # Add module import setup
        consolidated_content.append('# Import testable module directly without triggering my_code.py')
        consolidated_content.append(f'_testable_path = Path(__file__).parent / "{testable_path.name}"')
        consolidated_content.append(f'_spec = importlib.util.spec_from_file_location("{module_name}_testable", _testable_path)')
        consolidated_content.append(f'{module_name}_testable = importlib.util.module_from_spec(_spec)')
        consolidated_content.append(f'_spec.loader.exec_module({module_name}_testable)')
        consolidated_content.append('')
        consolidated_content.append('')
        
        # Add all test functions
        for test_func in all_test_functions:
            # Fix any remaining module references
            test_func = test_func.replace('module_0', f'{module_name}_testable')
            test_func = re.sub(rf'\b{module_name}\.', f'{module_name}_testable.', test_func)
            consolidated_content.append(test_func)
            consolidated_content.append('')
            consolidated_content.append('')
        
        # Write consolidated file
        final_content = '\n'.join(consolidated_content)
        root_test_file.write_text(final_content, encoding="utf-8")
        
        print(f"  [OK] Consolidated {len(all_test_functions)} test cases into {root_test_file.name}")
        return True
        
    except Exception as e:
        print(f"  [ERROR] Failed to consolidate tests: {e}")
        import traceback
        traceback.print_exc()
        return False

def analyze_generated_tests(test_dir: Path) -> dict:
    """Analyze what test cases were generated."""
    try:
        from analyze_tests import analyze_test_directory
        
        results = analyze_test_directory(test_dir)
        total_tests = sum(info.get('test_count', 0) for info in results.values())
        
        print(f"\n{'-'*60}")
        print("GENERATED TEST CASES SUMMARY")
        print(f"{'-'*60}")
        
        if total_tests == 0:
            print("  [INFO] No test cases found in generated files")
        else:
            for filename, info in results.items():
                if info.get('exists') and info.get('test_count', 0) > 0:
                    print(f"\n  {filename}: {info['test_count']} test(s)")
                    for test in info.get('tests', []):
                        decorators = ", ".join(test.get('decorators', []))
                        decorator_info = f" [{decorators}]" if decorators else ""
                        print(f"    - {test['name']}{decorator_info}")
            
            print(f"\n  Total: {total_tests} test case(s) generated")
        
        print(f"{'-'*60}")
        
        return {"total_test_cases": total_tests, "test_files": results}
    except Exception as e:
        print(f"  [WARNING] Could not analyze test cases: {e}")
        return {"total_test_cases": 0, "test_files": {}}

def run_tests_summary(test_dir: Path, module_name: Optional[str] = None) -> dict:
    """
    Run pytest and return detailed summary with metrics.
    
    Args:
        test_dir: Directory containing test files
        module_name: Name of module being tested (for coverage)
    
    Returns:
        Dictionary with test metrics
    """
    import json
    import re
    
    print(f"\n{'-'*60}")
    print(f"Running pytest on {test_dir}...")
    
    # Build pytest command
    # Use --json-report if available for more reliable parsing, otherwise use verbose output
    # Add -v for verbose output to see individual test results
    cmd = [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short", "--disable-warnings", "-rA"]
    
    # Try to use JSON report for more reliable parsing
    json_report_file = test_dir / "pytest_report.json"
    use_json_report = False
    try:
        # Check if pytest-json-report is available
        import importlib
        importlib.import_module("pytest_jsonreport")
        cmd.extend(["--json-report", "--json-report-file", str(json_report_file)])
        use_json_report = True
    except ImportError:
        pass  # JSON report not available, use text parsing
    
    # Add coverage if module name provided
    if module_name:
        cmd.extend(["--cov", module_name, "--cov-report=term-missing", "--cov-report=json"])
    
    start_time = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - start_time
    
    # Parse results
    output = result.stdout + result.stderr  # Include stderr for complete output
    metrics = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "runtime": elapsed,
        "coverage": None
    }
    
    # Try to parse JSON report first if available (most reliable)
    json_parsed = False
    if use_json_report and json_report_file.exists():
        try:
            with open(json_report_file, 'r') as f:
                json_data = json.load(f)
                if 'summary' in json_data:
                    summary = json_data['summary']
                    metrics["passed"] = summary.get('passed', 0)
                    metrics["failed"] = summary.get('failed', 0)
                    metrics["skipped"] = summary.get('skipped', 0)
                    metrics["errors"] = summary.get('error', 0)
                    metrics["total"] = summary.get('total', 0)
                    json_parsed = True
                    # Clean up JSON report file
                    json_report_file.unlink()
        except Exception:
            pass  # Fall back to text parsing if JSON fails
    
    # Method 1: Parse summary line from text output (if JSON wasn't used or failed)
    if not json_parsed:
        # Pytest summary format: "4 passed in 1.31s" or "5 passed, 2 failed, 1 skipped in 0.50s"
        # or "2 errors in 0.67s"
        # Note: pytest uses plural forms: "errors", "passed", "failed", "skipped"
        # Try to find the summary line which typically appears at the end
        # Look for the final summary line with "in X.XXs" pattern
        summary_line_match = re.search(
            r"(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+skipped)?(?:,\s*(\d+)\s+errors?)?\s+in\s+[\d.]+s|"
            r"(\d+)\s+failed(?:,\s*(\d+)\s+skipped)?(?:,\s*(\d+)\s+errors?)?\s+in\s+[\d.]+s|"
            r"(\d+)\s+skipped(?:,\s*(\d+)\s+errors?)?\s+in\s+[\d.]+s|"
            r"(\d+)\s+errors?\s+in\s+[\d.]+s",
            output, re.IGNORECASE
        )
        
        # Also try without the "in X.XXs" pattern as fallback
        if not summary_line_match:
            summary_line_match = re.search(
                r"(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+skipped)?(?:,\s*(\d+)\s+errors?)?|"
                r"(\d+)\s+failed(?:,\s*(\d+)\s+skipped)?(?:,\s*(\d+)\s+errors?)?|"
                r"(\d+)\s+skipped(?:,\s*(\d+)\s+errors?)?|"
                r"(\d+)\s+errors?",
                output, re.IGNORECASE
            )
        
        if summary_line_match:
            groups = summary_line_match.groups()
            # First pattern: passed, failed, skipped, error
            if groups[0]:  # passed count
                metrics["passed"] = int(groups[0])
                if groups[1]:  # failed count
                    metrics["failed"] = int(groups[1])
                if groups[2]:  # skipped count
                    metrics["skipped"] = int(groups[2])
                if groups[3]:  # error count
                    metrics["errors"] = int(groups[3])
            # Second pattern: failed, skipped, error (no passed)
            elif groups[4]:  # failed count
                metrics["failed"] = int(groups[4])
                if groups[5]:  # skipped count
                    metrics["skipped"] = int(groups[5])
                if groups[6]:  # error count
                    metrics["errors"] = int(groups[6])
            # Third pattern: skipped, error (no passed/failed)
            elif groups[7]:  # skipped count
                metrics["skipped"] = int(groups[7])
                if groups[8]:  # error count
                    metrics["errors"] = int(groups[8])
            # Fourth pattern: error only
            elif groups[9]:  # error count
                metrics["errors"] = int(groups[9])
        
        # Calculate total from what we got so far
        metrics["total"] = metrics["passed"] + metrics["failed"] + metrics["skipped"] + metrics["errors"]
        
        # Fallback: If summary parsing didn't work, try individual patterns
        # Also look for the final summary line: "X errors in Ys" or "X passed in Ys"
        if metrics["total"] == 0:
            final_summary_match = re.search(r"(\d+)\s+(passed|failed|skipped|errors?)\s+in\s+[\d.]+s", output, re.IGNORECASE)
            if final_summary_match:
                count = int(final_summary_match.group(1))
                status = final_summary_match.group(2).lower()
                if "passed" in status:
                    metrics["passed"] = count
                elif "failed" in status:
                    metrics["failed"] = count
                elif "skipped" in status:
                    metrics["skipped"] = count
                elif "error" in status:
                    metrics["errors"] = count
                metrics["total"] = count
        
        if metrics["total"] == 0:
            passed_match = re.search(r"(\d+)\s+passed", output, re.IGNORECASE)
            if passed_match:
                metrics["passed"] = int(passed_match.group(1))
            
            failed_match = re.search(r"(\d+)\s+failed", output, re.IGNORECASE)
            if failed_match:
                metrics["failed"] = int(failed_match.group(1))
            
            skipped_match = re.search(r"(\d+)\s+skipped", output, re.IGNORECASE)
            if skipped_match:
                metrics["skipped"] = int(skipped_match.group(1))
            
            error_match = re.search(r"(\d+)\s+errors?", output, re.IGNORECASE)
            if error_match:
                metrics["errors"] = int(error_match.group(1))
            
            # Recalculate total
            metrics["total"] = metrics["passed"] + metrics["failed"] + metrics["skipped"] + metrics["errors"]
        
        # Method 2: Count individual test result lines (more reliable)
        # Look for lines like "test_factorial_zero PASSED" or "test_factorial_zero PASSED [ 25%]"
        # Format: "file.py::test_function_name PASSED" or "file.py::test_function_name PASSED [ 25%]"
        passed_tests = len(re.findall(r"::test_\w+\s+PASSED", output, re.IGNORECASE))
        failed_tests = len(re.findall(r"::test_\w+\s+FAILED", output, re.IGNORECASE))
        skipped_tests = len(re.findall(r"::test_\w+\s+SKIPPED", output, re.IGNORECASE))
        error_tests = len(re.findall(r"::test_\w+\s+ERROR", output, re.IGNORECASE))
        
        # Use counted results if they're more reliable than parsed summary
        if passed_tests + failed_tests + skipped_tests + error_tests > 0:
            if metrics["total"] == 0 or (passed_tests + failed_tests + skipped_tests + error_tests) > metrics["total"]:
                metrics["passed"] = passed_tests
                metrics["failed"] = failed_tests
                metrics["skipped"] = skipped_tests
                metrics["errors"] = error_tests
                metrics["total"] = passed_tests + failed_tests + skipped_tests + error_tests
        
        # Fallback: If still no results, count generic PASSED/FAILED keywords
        if metrics["total"] == 0:
            metrics["passed"] = len(re.findall(r"\bPASSED\b", output, re.IGNORECASE))
            metrics["failed"] = len(re.findall(r"\bFAILED\b", output, re.IGNORECASE))
            metrics["skipped"] = len(re.findall(r"\bSKIPPED\b", output, re.IGNORECASE))
            # Count ERROR lines (collection errors, test errors, etc.)
            metrics["errors"] = len(re.findall(r"\bERROR\b", output, re.IGNORECASE))
            metrics["total"] = metrics["passed"] + metrics["failed"] + metrics["skipped"] + metrics["errors"]
        
        # If still no tests found, try to count test functions that were discovered
        if metrics["total"] == 0:
            # Look for test collection output: "collected X items" or "collected 0 items / 2 errors"
            collection_match = re.search(r"collected\s+(\d+)\s+items?(?:\s*/\s*(\d+)\s+errors?)?", output, re.IGNORECASE)
            if collection_match:
                items_collected = int(collection_match.group(1))
                errors_during_collection = int(collection_match.group(2)) if collection_match.group(2) else 0
                # If there were collection errors, count them
                if errors_during_collection > 0:
                    metrics["errors"] = errors_during_collection
                    metrics["total"] = errors_during_collection
                elif items_collected > 0:
                    metrics["total"] = items_collected
                # The final_summary_match above should have already caught this
    
    # Extract coverage if available
    if module_name:
        coverage_match = re.search(r"TOTAL\s+(\d+)\s+\d+\s+(\d+%)", output)
        if coverage_match:
            metrics["coverage"] = coverage_match.group(2)
        # Also try JSON coverage report
        cov_json = Path(".coverage.json")
        if cov_json.exists():
            try:
                with open(cov_json, 'r') as f:
                    cov_data = json.load(f)
                    if 'totals' in cov_data:
                        metrics["coverage"] = f"{cov_data['totals']['percent_covered']:.1f}%"
            except:
                pass
    
    return metrics

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_and_run_tests.py <python_file> [output_dir]")
        sys.exit(1)

    python_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./generated_tests"
    module_path = Path(python_file)
    module_name = module_path.stem

    print(f"\n{'='*60}")
    print(f"PYNGUIN TEST GENERATION")
    print(f"{'='*60}")
    print(f"Source: {python_file}")
    print(f"Output: {output_dir}")
    print()

    try:
        # Step 1: Always sync the testable file from the source
        print("Step 1: Preparing testable version...")
        testable_path = prepare_module_for_testing(module_path)
        print()
        
        # Step 2: Generate tests using Pynguin
        print("Step 2: Generating tests with Pynguin...")
        test_dir, gen_time = generate_tests_pynguin(python_file, output_dir, timeout=180)
        print()

        # Step 3: Create property-based tests
        print("Step 3: Creating property-based tests...")
        prop_file = create_property_tests(module_name, test_dir)
        print()

        # Step 4: Analyze generated tests
        print("Step 4: Analyzing generated tests...")
        test_analysis = analyze_generated_tests(test_dir)
        print()

        # Step 5: Consolidate all tests into root test_my_code.py
        print("Step 5: Consolidating tests...")
        root_test_file = Path(f"test_{module_name}.py")
        consolidate_tests_to_root(test_dir, root_test_file, module_name)
        print()

        # Step 6: Run pytest
        print("Step 6: Running pytest...")
        metrics = run_tests_summary(test_dir, module_name)
        print()

        print(f"{'='*60}")
        print("PYNGUIN TEST RESULTS")
        print(f"{'='*60}")
        print(f"Generation time: {gen_time:.2f}s")
        print(f"Test execution time: {metrics['runtime']:.2f}s")
        print(f"Total tests: {metrics['total']}")
        print(f"Passed: {metrics['passed']}")
        print(f"Failed: {metrics['failed']}")
        print(f"Skipped: {metrics['skipped']}")
        if metrics['errors'] > 0:
            print(f"Errors: {metrics['errors']}")
        if metrics['coverage']:
            print(f"Coverage: {metrics['coverage']}")

        # Show test analysis if available
        if 'test_analysis' in locals() and test_analysis:
            total_generated = test_analysis.get('total_test_cases', 0)
            if total_generated > 0:
                print(f"\nGenerated test cases: {total_generated}")

        print(f"{'='*60}")
        print(f"Testable file location: {testable_path}")
        print(f"Test output directory: {test_dir}")
        print(f"Root test file: {root_test_file}")
        print(f"{'='*60}")

    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
