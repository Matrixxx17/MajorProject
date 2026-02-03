# Quick Start Guide

## Installation

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Ollama (if not already installed)
# Visit https://ollama.ai and download
# Then pull the model:
ollama pull starcoder
```

## Run All Tests

**Main Command:**
```bash
python run_all_tests.py my_code.py
```

This single command will:
1. ✅ Generate tests using **Ollama** (LLM-based)
2. ✅ Generate tests using **Pynguin** (automated)
3. ✅ Create **property-based tests** (Hypothesis)
4. ✅ Run all generated tests
5. ✅ Generate comprehensive report with metrics

## Output

### Test Files Location
All test files are saved in: `generated_tests/`

- `test_my_code_ollama.py` - Ollama-generated tests
- `test_my_code.py` - Pynguin-generated tests  
- `test_properties.py` - Property-based tests

### Reports

**Terminal Report:** Displayed automatically with:
- Generation times
- Execution times
- Test counts (total, passed, failed)
- Pass rates
- Code coverage

**JSON Report:** Saved to `generated_tests/test_report.json`

## Individual Methods

### Ollama Only
```bash
python generate_test.py my_code.py
```

### Pynguin Only
```bash
python generate_and_run_tests.py my_code.py
```

## Custom Output Directory

```bash
python run_all_tests.py my_code.py ./custom_tests
```

## View Test Cases

After running, view generated tests:
```bash
# Windows
type generated_tests\test_my_code_ollama.py
type generated_tests\test_my_code.py
type generated_tests\test_properties.py

# Linux/Mac
cat generated_tests/test_my_code_ollama.py
cat generated_tests/test_my_code.py
cat generated_tests/test_properties.py
```

## Run Tests Manually

```bash
# Run all tests
pytest generated_tests/ -v

# Run with coverage
pytest generated_tests/ --cov=my_code --cov-report=term-missing
```

## Troubleshooting

**Ollama not found?**
- Install from https://ollama.ai
- Ensure `ollama` is in PATH
- Run: `ollama pull starcoder`

**Pynguin timeout?**
- Tests will still be generated (partial results)
- Increase timeout in `generate_and_run_tests.py` if needed

**No tests generated?**
- Check that `my_code.py` exists
- Verify functions are properly defined
- Check terminal for error messages


