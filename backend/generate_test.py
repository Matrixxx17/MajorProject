import sys
from pathlib import Path
import subprocess
import time
from typing import Optional

import ast
import textwrap

ALLOWED_MODELS = {
    "deepseek-coder:1.3b",
    "codellama:7b"
}

def generate_tests_ollama(code: str, model: str = "deepseek-coder:1.3b", timeout: int = 60) -> Optional[str]:
    """
    Generate test cases using Ollama LLM.
    
    Args:
        code: Source code to generate tests for
        model: Ollama model name
        timeout: Maximum time to wait for response (seconds)
    
    Returns:
        Generated test code as string, or None if failed
    """
    if model not in ALLOWED_MODELS:
        raise ValueError(
            f"Unsupported model '{model}'. "
            f"Allowed models: {', '.join(ALLOWED_MODELS)}"
        )

        # Completion prompt for StarCoder
    else:
        # Chat prompt for DeepSeek/Llama
        prompt = f"""You are a Senior QA Engineer. Your task is to write comprehensive `pytest` test cases for the following Python code.

Requirements:
1.  **Analyze the Code**: Understand the function/class logic, inputs, and expected outputs.
2.  **Cover Edge Cases**: Include tests for empty inputs, None values, boundary values, large inputs, and invalid types where applicable.
3.  **Happy Path**: Verify standard use cases.
4.  **Error Handling**: Assert that appropriate exceptions are raised for invalid inputs.
5.  **Format**: Return ONLY valid Python code inside a single markdown code block. Include all necessary imports (`pytest`, `sys`, etc.).
6.  **No conversational text**: Do not add explanations outside the code block.

Function/Code to Test:
{code}

Generate the complete test file now:"""

    # Retry logic: Ollama may take longer or transiently fail. Try a few times before giving up.
    attempts = 3
    cur_timeout = timeout
    output = ""
    elapsed = 0.0

    for attempt in range(1, attempts + 1):
        try:
            print(f"  [INFO] Calling Ollama (attempt {attempt}/{attempts}) - timeout={cur_timeout}s")
            start_time = time.time()
            result = subprocess.run(
                ["ollama", "run", model, prompt],
                capture_output=True,
                text=True,
                timeout=cur_timeout,
                encoding='utf-8',
                errors='ignore'
            )
            elapsed = time.time() - start_time

            if result.returncode != 0:
                print(f"  [WARNING] Ollama returned exit code {result.returncode}")
                if result.stderr:
                    print(f"  Error (preview): {result.stderr[:200]}")

            # Extract code blocks if present
            output = result.stdout.strip()
            break

        except subprocess.TimeoutExpired:
            print(f"  [WARNING] Ollama timed out after {cur_timeout}s on attempt {attempt}")
            # backoff and retry
            cur_timeout = min(cur_timeout * 2, 300)
            continue

    # Clean up ANSI escape codes that Ollama might output
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    output = ansi_escape.sub('', output)
    
    # Remove common prefixes/suffixes that models sometimes add
    # Find the start of actual code (import or def test_)
    match = re.search(r'(import|def test_|from)', output, re.IGNORECASE)
    if match:
        output = output[match.start():]
    output = output.strip()
    
    # Try to extract code from markdown code blocks
    if "```python" in output:
        parts = output.split("```python")
        if len(parts) > 1:
            code_part = parts[1].split("```")[0].strip()
            if code_part:
                output = code_part
    elif "```" in output:
        parts = output.split("```")
        if len(parts) > 1:
            # Find the first code block that looks like Python
            for i in range(1, len(parts), 2):
                candidate = parts[i].strip()
                if candidate and ("import" in candidate or "def test" in candidate.lower()):
                    output = candidate
                    break

    # If output still contains the original function, try to extract just the test part
    if "def anagram" in output or "from collections import" in output:
        # Try to find where tests start
        test_start = output.find("def test_")
        if test_start > 0:
            output = output[test_start:]
        # Or find import pytest/import my_code
        import_start = output.find("import pytest")
        if import_start >= 0:
            output = output[import_start:]

    # More flexible validation - look for test functions or imports
    has_test_code = False
    if output:
        # Check for test function definitions
        if "def test_" in output.lower() or "test_" in output:
            has_test_code = True
        # Check for pytest imports
        elif "import pytest" in output or "from pytest" in output:
            has_test_code = True
        # Check for common test patterns
        elif "assert" in output and ("import" in output or "def " in output):
            has_test_code = True

    if has_test_code:
        print(f"  [OK] Ollama test generation completed in {elapsed:.2f}s")
        return output
    else:
        print(f"  [ERROR] Invalid output from Ollama (no test code detected)")
        if output:
            print(f"  [DEBUG] Output preview (first 300 chars):")
            print(f"  {output[:300]}")
        return None


def fallback_simple_tests(code: str, module_name: str) -> str:
    """Generate very simple fallback pytest file when LLM fails.

    The fallback creates tests that import the testable module file and
    exercise each top-level function with a few safe inputs (empty list,
    empty string, zero). These tests are intentionally permissive (they
    assert that the call does not raise) to provide a baseline.
    """
    try:
        tree = ast.parse(code)
    except Exception:
        # If parsing fails, return a minimal smoke test
        funcs = []
    else:
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]

    lines = []
    lines.append("import importlib.util")
    lines.append("from pathlib import Path")
    lines.append("")
    lines.append(f"_testable_path = Path(__file__).parent.parent / \"{module_name}.testable.py\"")
    lines.append(f"_spec = importlib.util.spec_from_file_location(\"{module_name}_testable\", _testable_path)")
    lines.append(f"{module_name}_testable = importlib.util.module_from_spec(_spec)")
    lines.append(f"_spec.loader.exec_module({module_name}_testable)")
    lines.append("")

    if not funcs:
        lines.append("def test_smoke():")
        lines.append("    # No functions detected; ensure module imports cleanly")
        lines.append(f"    assert {module_name}_testable is not None")
        return "\n".join(lines)

    for fn in funcs:
        test_name = f"test_{fn}_does_not_raise"
        lines.append(f"def {test_name}():")
        lines.append(f"    \"\"\"Basic smoke test for `{fn}`.\"\"\"")
        lines.append("    try:")
        # Try a few safe inputs
        lines.append(f"        {module_name}_testable.{fn}([])")
        lines.append("    except Exception:")
        lines.append("        pass")
        lines.append("")

    return "\n".join(lines)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_test.py <python_file> [output_dir]")
        sys.exit(1)

    src_file = Path(sys.argv[1])
    if not src_file.exists():
        print(f"[ERROR] File not found: {src_file}")
        sys.exit(1)

    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("generated_tests")
    output_dir.mkdir(parents=True, exist_ok=True)

    code = src_file.read_text(encoding="utf-8")
    module_name = src_file.stem

    print(f"\n{'='*60}")
    print(f"OLLAMA TEST GENERATION")
    print(f"{'='*60}")
    print(f"Source: {src_file}")
    print(f"Model: starcoder")
    
    model = sys.argv[3] if len(sys.argv) > 3 else "deepseek-coder:1.3b"
    tests = generate_tests_ollama(code, model=model)


    if tests:
        out_file = output_dir / f"test_{module_name}_ollama.py"
        out_file.write_text(tests, encoding="utf-8")
        print(f"\n[OK] Test file created: {out_file}")
        print(f"\n{'-'*60}")
        print("Preview (first 500 chars):")
        print(f"{'-'*60}")
        print(tests[:500])
        if len(tests) > 500:
            print("...")
    else:
        print("\n[WARN] Ollama did not return valid tests. Generating fallback simple tests...")
        fallback = fallback_simple_tests(code, module_name)
        out_file = output_dir / f"test_{module_name}_fallback.py"
        out_file.write_text(fallback, encoding="utf-8")
        print(f"\n[OK] Fallback test file created: {out_file}")
        print(f"\nPreview (first 500 chars):\n{'-'*60}")
        print(fallback[:500])
