# Testing Guide for Pynguin Test Generator

This guide walks you through testing the extension with the provided example module.

## Quick Test

### 1. Start the Services

**Terminal 1 - Start Ollama:**
```bash
ollama serve
```

**Terminal 2 - Start Backend:**
```bash
cd pynguin-backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
python main.py
```

You should see:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Verify Services

Check backend health:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "Pynguin Test Generator",
  "version": "1.0.0"
}
```

Check Ollama connection:
```bash
curl http://localhost:8000/ollama-status
```

Expected response:
```json
{
  "status": "connected",
  "models": ["codellama:latest"]
}
```

### 3. Test with Example Module

1. **Open VS Code** and load the extension (F5 in development mode)

2. **Create the example file:**
   - Create a new file `calculator.py`
   - Copy the example code from `example_module.py`

3. **Open the Extension:**
   - Click the beaker icon (🧪) in the activity bar
   - The "Pynguin Test Generator" panel opens

4. **Generate Tests:**
   - Backend URL: `http://localhost:8000` (default)
   - Click "📁 Select Python File"
   - Choose `calculator.py`
   - Directory path auto-fills
   - Click "Generate Tests"

5. **Wait for Results** (2-5 minutes):
   - Watch the progress in the panel
   - Pipeline runs: Pynguin → Coverage → Mutation → LLM

6. **Review Results:**
   - View mutation score and coverage
   - Preview generated tests
   - Click "Yes" to create test file

### 4. Verify Generated Tests

Run the generated tests:
```bash
pytest test_calculator.py -v
```

Expected output:
```
test_calculator.py::test_add_positive_numbers PASSED
test_calculator.py::test_divide_by_zero_raises_error PASSED
test_calculator.py::test_calculate_discount_valid PASSED
...
===== 15 passed in 0.5s =====
```

## Testing Different Scenarios

### Test 1: Simple Function

Create `simple.py`:
```python
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b
```

Generate tests and verify coverage > 90%.

### Test 2: Function with Validation

Create `validator.py`:
```python
def validate_email(email: str) -> bool:
    if not email:
        return False
    if '@' not in email:
        return False
    parts = email.split('@')
    if len(parts) != 2:
        return False
    return True
```

Generate tests and check edge cases are covered.

### Test 3: Class with State

Create `counter.py`:
```python
class Counter:
    def __init__(self):
        self.count = 0
    
    def increment(self):
        self.count += 1
    
    def decrement(self):
        self.count -= 1
    
    def reset(self):
        self.count = 0
    
    def get_value(self):
        return self.count
```

Generate tests and verify state transitions are tested.

## Manual API Testing

### Test Endpoint Directly

```bash
curl -X POST http://localhost:8000/generate-tests \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def add(a, b):\n    return a + b",
    "module_name": "simple",
    "directory": "/tmp/test",
    "file_path": "/tmp/test/simple.py",
    "ollama_model": "codellama",
    "ollama_url": "http://localhost:11434",
    "pynguin_timeout": 60,
    "mutation_threshold": 0.3
  }'
```

Expected response structure:
```json
{
  "tests": "import pytest\n\ndef test_add():\n    ...",
  "mutation_score": 0.85,
  "coverage": 0.92,
  "message": "Successfully generated tests...",
  "pynguin_tests": "...",
  "refined_tests": "...",
  "pipeline_log": [...]
}
```

## Troubleshooting Tests

### Backend Not Starting

**Check Python version:**
```bash
python3 --version  # Should be 3.8+
```

**Check dependencies:**
```bash
pip list | grep -E "pynguin|fastapi|mutmut"
```

**Check port availability:**
```bash
lsof -i :8000  # Should be empty or show uvicorn
```

### Ollama Connection Failed

**Verify Ollama is running:**
```bash
ollama list
```

**Test Ollama directly:**
```bash
curl http://localhost:11434/api/tags
```

**Pull model if missing:**
```bash
ollama pull codellama
```

### Pynguin Fails

**Common causes:**
- Syntax errors in code
- Missing dependencies
- Timeout too short

**Solutions:**
- Validate Python syntax first
- Increase timeout: `"pynguin_timeout": 120`
- Check module imports are available

### Tests Not Generated

**Check logs in response:**
```bash
# The response includes pipeline_log array
# Look for errors in each step
```

**Verify temp directory permissions:**
```bash
ls -la /tmp
```

### Low Mutation Score

**Causes:**
- Simple/trivial code
- Pynguin couldn't generate good assertions
- Test timeout

**Solutions:**
- Add more complex logic to test
- Increase Pynguin search time
- Manually review and enhance tests

## Performance Benchmarks

Expected timing for different code sizes:

| Code Size | Lines | Functions | Time (Pynguin) | Time (Total) |
|-----------|-------|-----------|----------------|--------------|
| Small     | <50   | 1-3       | 10-30s         | 30-60s       |
| Medium    | 50-200| 4-10      | 30-90s         | 60-180s      |
| Large     | 200+  | 10+       | 60-180s        | 120-300s     |

## Quality Metrics

Good test generation should achieve:

- **Coverage:** > 80%
- **Mutation Score:** > 60%
- **Test Count:** ~3-5 tests per function
- **Assertion Count:** ~2-4 assertions per test

## Advanced Testing

### Test with Custom Ollama Model

```json
{
  "ollama_model": "mistral",
  "ollama_url": "http://localhost:11434"
}
```

### Test with Different Mutation Threshold

```json
{
  "mutation_threshold": 0.5  // Only refine if score > 50%
}
```

### Test with Extended Timeout

```json
{
  "pynguin_timeout": 180  // 3 minutes for complex code
}
```

## Continuous Testing

### Create Test Script

`test_generator.sh`:
```bash
#!/bin/bash

# Test multiple modules
for file in src/*.py; do
    echo "Testing $file..."
    
    curl -X POST http://localhost:8000/generate-tests \
      -H "Content-Type: application/json" \
      -d "{
        \"code\": \"$(cat $file)\",
        \"module_name\": \"$(basename $file .py)\",
        \"directory\": \"$(dirname $file)\",
        \"file_path\": \"$file\"
      }" | jq '.mutation_score'
done
```

### Integration with CI/CD

Add to `.github/workflows/test-generation.yml`:
```yaml
name: Generate Tests

on: [push]

jobs:
  generate-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Start backend
        run: python main.py &
      
      - name: Generate tests
        run: ./test_generator.sh
```

## Test Coverage Analysis

After generating tests, analyze coverage:

```bash
# Run tests with coverage
pytest test_calculator.py --cov=calculator --cov-report=html

# View report
open htmlcov/index.html
```

Look for:
- Uncovered lines
- Branch coverage
- Missing edge cases

## Next Steps

1. **Iterate on tests:** Review and manually enhance
2. **Add custom assertions:** Make tests more meaningful
3. **Test edge cases:** Add tests Pynguin missed
4. **Document tests:** Add comprehensive docstrings
5. **Integrate into workflow:** Add to pre-commit hooks

## Getting Help

- Check API docs: http://localhost:8000/docs
- View logs in response: `pipeline_log` field
- Enable verbose mode in backend
- Review Pynguin documentation
- Test with simpler code first