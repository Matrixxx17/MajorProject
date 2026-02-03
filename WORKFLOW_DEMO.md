# Auto-Sync Testable File Workflow

## How It Works

The system now automatically keeps `my_code.testable.py` in sync with `my_code.py` whenever you run the test generator.

### Workflow Steps

1. **Source File (`my_code.py`)**: Your main code file with functions to test
2. **Testable File (`my_code.testable.py`)**: Auto-generated copy without blocking `input()/print()` calls
3. **Pynguin**: Uses the testable file to generate test cases
4. **Property Tests**: Hypothesis-based tests generated for your functions
5. **Pytest**: Runs all generated tests and reports metrics

### The Process

```bash
python generate_and_run_tests.py my_code.py
```

**Step-by-step:**

1. ✅ **Prepare testable version**
   - Reads `my_code.py`
   - Creates/Updates `my_code.testable.py`
   - Removes `input()` and module-level `print()` calls
   - Reports sync status: "Testable version is up-to-date" or "Updated testable version"

2. ✅ **Generate tests with Pynguin**
   - Uses `my_code.testable.py` (no blocking calls)
   - Generates test cases based on code analysis
   - Runs for ~180 seconds with configurable parameters
   - Outputs: `generated_tests/test_my_code.py`

3. ✅ **Create property-based tests**
   - Generates Hypothesis-based property tests
   - Outputs: `generated_tests/test_properties.py`
   - Tests verify function behavior with various inputs

4. ✅ **Analyze generated tests**
   - Reports number and types of test cases
   - Shows which functions have tests

5. ✅ **Consolidate tests**
   - Merges all tests into root-level `test_my_code.py`
   - Fixes imports to use testable module

6. ✅ **Run pytest**
   - Executes all tests
   - Reports: passed, failed, skipped, errors
   - Shows coverage percentage if available

### Example Output

```
============================================================
PYNGUIN TEST GENERATION
============================================================
Source: my_code.py
Output: ./generated_tests

Step 1: Preparing testable version...
  [SYNC] Testable version is up-to-date: my_code.testable.py

Step 2: Generating tests with Pynguin...
[WARNING] Experienced timeout from test-case execution (internal Pynguin message)

Step 3: Creating property-based tests...
  [OK] Property-based tests created: generated_tests\test_properties.py

Step 4: Analyzing generated tests...
  Total: 4 test case(s) generated

Step 5: Consolidating tests...
  [OK] Consolidated 1 test cases into test_my_code.py

Step 6: Running pytest...

============================================================
PYNGUIN TEST RESULTS
============================================================
Generation time: 233.70s
Test execution time: 7.08s
Total tests: 4
Passed: X
Failed: Y
Coverage: Z%
============================================================
```

## When Code Changes

Whenever you modify `my_code.py`:

1. Add/update/remove functions
2. Change function logic
3. Any other code changes

**Simply run:**
```bash
python generate_and_run_tests.py my_code.py
```

The system will:
- ✅ Auto-detect changes in `my_code.py`
- ✅ Automatically update `my_code.testable.py` to match
- ✅ Report: "Updated testable version" or "Testable version is up-to-date"
- ✅ Generate fresh tests for the new/changed code
- ✅ Remove old test files and create new ones
- ✅ Run pytest and report all metrics

## Files Involved

| File | Purpose |
|------|---------|
| `my_code.py` | Your main source code (EDIT THIS) |
| `my_code.testable.py` | Auto-synced copy for Pynguin (AUTO-GENERATED) |
| `generate_and_run_tests.py` | Orchestrator script (RUN THIS) |
| `prepare_code_for_testing.py` | Helper for syncing testable file |
| `generated_tests/test_my_code.py` | Pynguin-generated tests (AUTO-GENERATED) |
| `generated_tests/test_properties.py` | Hypothesis property tests (AUTO-GENERATED) |
| `test_my_code.py` | Consolidated root test file (AUTO-GENERATED) |

## Commands

### Generate/Update tests
```bash
python generate_and_run_tests.py my_code.py
```

### Run only Pynguin
```bash
python -m pynguin --project-path . --output-path ./generated_tests --module-name my_code
```

### Run only pytest
```bash
python -m pytest test_my_code.py -v
```

### Check testable file sync status
```bash
python prepare_code_for_testing.py my_code.py my_code.testable.py
```

## Key Features

✅ **Automatic Sync** - Testable file always matches source  
✅ **No Blocking Calls** - `input()` and `print()` removed automatically  
✅ **Complete Workflow** - One command does everything  
✅ **Multiple Test Types** - Both Pynguin + property-based tests  
✅ **Clean Reports** - Structured output with metrics  
✅ **Consolidation** - All tests in one file for easy access  
