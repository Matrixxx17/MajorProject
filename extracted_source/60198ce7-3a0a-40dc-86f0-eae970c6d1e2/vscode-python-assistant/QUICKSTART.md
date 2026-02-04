# Quick Start Guide

## 5-Minute Setup

### 1. Install Prerequisites

**Required:**
- Python 3.8+ ([download](https://www.python.org/downloads/))
- Node.js 18+ ([download](https://nodejs.org/))
- VS Code ([download](https://code.visualstudio.com/))

**Optional (but recommended):**
- Ollama for test refinement ([download](https://ollama.ai))
- CUDA for GPU acceleration ([download](https://developer.nvidia.com/cuda-downloads))

### 2. Run Setup Script

```bash
# Make script executable (Linux/Mac)
chmod +x setup.sh

# Run setup
./setup.sh
```

Or manually:

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Extension
cd ..
npm install
npm run compile
```

### 3. Start Backend

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
python main.py
```

You should see:
```
Starting Python Assistant API...
Backend: http://localhost:8000
Docs: http://localhost:8000/docs
Device: CUDA  # or CPU
```

### 4. Start Extension

1. Open the project folder in VS Code
2. Press `F5` to launch Extension Development Host
3. A new VS Code window will open with the extension loaded

### 5. Use the Extension

In the new window:

1. Click the Python Assistant icon in the left sidebar
2. Click "Select File(s)" and choose a Python file
3. Switch to "Test Generation" or "Refactoring" tab
4. Click "Generate Tests" or "Refactor Code"

## Example Usage

### Test Generation

```python
# example.py
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n-1)
```

**Steps:**
1. Select `example.py`
2. Go to Test Generation tab
3. Set Pynguin Timeout: 30 seconds
4. Click "Generate Tests"
5. Review generated `test_example.py`

**Expected Output:**
- Coverage: ~95%
- Mutation Score: ~70%
- Refined test file with clear assertions

### Code Refactoring

```python
# messy_code.py
def process_data(data):
    result = []
    for i in range(len(data)):
        if data[i] > 0:
            temp = data[i] * 2
            result.append(temp)
    return result
```

**Steps:**
1. Select `messy_code.py`
2. Go to Refactoring tab
3. Select Optimization: "Balanced"
4. Click "Refactor Code"
5. Review suggested improvements

**Expected Output:**
```python
def process_data(data):
    return [item * 2 for item in data if item > 0]
```

## Troubleshooting

### Backend won't start

```bash
# Check if port 8000 is in use
lsof -i :8000  # Mac/Linux
netstat -ano | findstr :8000  # Windows

# Kill the process if needed
kill -9 <PID>  # Mac/Linux
taskkill /PID <PID> /F  # Windows
```

### Extension doesn't appear

1. Check you pressed `F5` (not `Ctrl+F5`)
2. Look for "Extension Development Host" window title
3. Check Output panel for errors

### "Cannot connect to backend"

1. Verify backend is running: `curl http://localhost:8000/health`
2. Check backend URL in extension settings
3. Look at backend terminal for error messages

### Pynguin errors

```bash
# Reinstall Pynguin
pip uninstall pynguin
pip install pynguin==0.36.0
```

### Out of memory (GPU)

Edit `backend/main.py`:
```python
# Use smaller model
model_name = "Salesforce/codet5p-770m"  # Instead of 2b

# Or disable GPU
device = "cpu"
```

## Advanced: Training the Model

### Prepare Training Data

Create `custom_training.json`:
```json
[
  {
    "original_code": "def bad_code():\n    x = 1\n    return x",
    "target_refactored": "def good_code():\n    return 1"
  }
]
```

### Run Training

```bash
cd models
python train_refactoring_ppo.py \
    --data custom_training.json \
    --epochs 5 \
    --batch-size 4 \
    --output-dir ./my_model
```

### Use Trained Model

Update `backend/main.py`:
```python
model_name = "./models/my_model"  # Your trained model path
```

## Testing the Installation

### Test Backend API

```bash
curl -X GET http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "Python Assistant API",
  "version": "2.0.0",
  "features": ["test_generation", "code_refactoring", "ppo_training"]
}
```

### Test with Python Script

```python
import requests

# Test generation
response = requests.post(
    "http://localhost:8000/generate-tests",
    json={
        "files": [{
            "path": "/tmp/test.py",
            "name": "test",
            "content": "def add(a, b):\n    return a + b"
        }],
        "config": {
            "ollama_model": "codellama",
            "ollama_url": "http://localhost:11434",
            "pynguin_timeout": 30,
            "mutation_threshold": 0.3
        }
    }
)

print(response.json())
```

## Next Steps

1. **Read the full README** for detailed documentation
2. **Try the examples** in the `examples/` folder
3. **Customize settings** in VS Code preferences
4. **Train your own model** with your coding style
5. **Contribute** by reporting issues or suggesting features

## Common Workflows

### Daily Development

1. Write code
2. Select file in Python Assistant
3. Generate tests → Review → Accept
4. Refactor suggestions → Review → Apply
5. Commit tested, clean code

### Code Review

1. Select files to review
2. Run refactoring analysis
3. Compare metrics (complexity, quality)
4. Apply improvements
5. Verify with tests

### Legacy Code Improvement

1. Select legacy module
2. Generate tests first (establish baseline)
3. Run refactoring with "Readability" focus
4. Review improvements
5. Verify tests still pass
6. Iterate as needed

## Resources

- **Documentation**: See `README.md`
- **API Docs**: http://localhost:8000/docs
- **Issues**: [GitHub Issues]
- **Examples**: See `examples/` folder

## Getting Help

If you encounter issues:

1. Check this guide's Troubleshooting section
2. Check the main README.md
3. Look at backend logs
4. Check VS Code Output panel
5. Open an issue with:
   - Error message
   - Steps to reproduce
   - System info (OS, Python version, etc.)

Happy coding! 🚀
