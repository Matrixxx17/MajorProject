# Python Assistant - VS Code Extension

An intelligent VS Code extension for Python developers that provides automated test case generation and AI-powered code refactoring.

## Features

### 🧪 Automated Test Generation
- Uses **Pynguin** for initial automated test generation
- **Mutation testing** with mutmut to ensure test quality
- **LLM refinement** via Ollama to improve test readability and completeness
- Coverage analysis to validate test effectiveness
- Support for single files, multiple files, or entire codebases

### ✨ AI-Powered Refactoring
- Leverages **transformer models** (CodeT5+, StarCoder) for intelligent refactoring
- **PPO-based fine-tuning** using TRL (Transformer Reinforcement Learning)
- Performance metrics including:
  - Cyclomatic complexity reduction
  - Maintainability index improvement
  - Code quality scores
  - Lines of code optimization
- Multiple optimization levels:
  - **Readability Focus**: Prioritizes clean, maintainable code
  - **Balanced**: Optimizes both readability and performance
  - **Performance Focus**: Maximizes execution efficiency

## Installation

### Prerequisites

1. **Python 3.8+** installed
2. **Node.js 18+** and npm
3. **Ollama** installed and running (for test refinement)
4. **CUDA** (optional, for GPU acceleration)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the backend server
python main.py
```

The backend will start on `http://localhost:8000`

### Extension Setup

```bash
# Install dependencies
npm install

# Compile TypeScript
npm run compile

# Package extension (optional)
npm install -g @vscode/vsce
vsce package
```

### Install in VS Code

1. Open VS Code
2. Press `Ctrl+Shift+P` (Cmd+Shift+P on Mac)
3. Type "Extensions: Install from VSIX"
4. Select the generated `.vsix` file

Or for development:
1. Open the project in VS Code
2. Press `F5` to launch Extension Development Host

## Usage

### Opening the Assistant

1. Click on the Python Assistant icon in the Activity Bar (left sidebar)
2. Or use Command Palette: `Python Assistant: Open Python Assistant`

### Test Generation Workflow

1. **Select Context**:
   - Click "Select File(s)" to choose one or more Python files
   - Click "Select Folder" to analyze an entire Python project

2. **Configure Settings** (in Test Generation tab):
   - Ollama Model: Choose your preferred model (e.g., `codellama`)
   - Ollama URL: Default `http://localhost:11434`
   - Pynguin Timeout: Time limit for test generation (seconds)
   - Mutation Threshold: Minimum mutation score for LLM refinement

3. **Generate Tests**:
   - Click "Generate Tests"
   - Wait for the pipeline to complete:
     - Pynguin generates initial tests
     - Coverage analysis runs
     - Mutation testing validates quality
     - LLM refines tests (if threshold met)

4. **Review Results**:
   - View coverage and mutation scores
   - Review generated test files
   - Choose to create test files in your project

### Refactoring Workflow

1. **Select Context**:
   - Choose files or folder to refactor

2. **Configure Settings** (in Refactoring tab):
   - Model: Select transformer model
     - `Salesforce/codet5p-770m` (recommended, faster)
     - `Salesforce/codet5p-2b` (better quality, slower)
     - `bigcode/starcoderbase` (best quality, requires GPU)
   - Optimization Level:
     - Readability Focus
     - Balanced (recommended)
     - Performance Focus
   - Enable/disable performance metrics analysis

3. **Refactor Code**:
   - Click "Refactor Code"
   - Wait for AI analysis and refactoring

4. **Review Changes**:
   - View side-by-side diff of original vs refactored code
   - Review performance metrics:
     - Complexity reduction
     - Quality score improvements
     - Maintainability index
   - Choose to apply or skip each refactoring

## Architecture

### Frontend (VS Code Extension)
- **TypeScript** with VS Code Extension API
- Webview-based UI for configuration and results
- File system analysis and management
- Diff viewer for refactoring suggestions

### Backend (FastAPI)
- **FastAPI** server handling requests
- Parallel processing of multiple files
- Integration with:
  - Pynguin (test generation)
  - pytest & coverage.py (coverage analysis)
  - mutmut (mutation testing)
  - Ollama (LLM refinement)
  - Transformers (code models)
  - TRL (PPO training)

### AI Components

#### Test Generation
```
Python Code → Pynguin → Initial Tests → Coverage Analysis → 
Mutation Testing → (if score > threshold) → Ollama LLM → Refined Tests
```

#### Refactoring
```
Python Code → Code Analysis → Transformer Model → 
Refactored Code → Metrics Comparison → Performance Report
```

#### PPO Training (Optional)
```
Training Examples → PPO Config → Reward Function → 
Fine-tuned Model → Improved Refactoring
```

## API Endpoints

### Test Generation
```http
POST /generate-tests
Content-Type: application/json

{
  "files": [
    {
      "path": "/path/to/file.py",
      "name": "module_name",
      "content": "def foo(): pass"
    }
  ],
  "config": {
    "ollama_model": "codellama",
    "ollama_url": "http://localhost:11434",
    "pynguin_timeout": 60,
    "mutation_threshold": 0.3
  }
}
```

### Code Refactoring
```http
POST /refactor-code
Content-Type: application/json

{
  "files": [
    {
      "path": "/path/to/file.py",
      "name": "module_name",
      "content": "def foo(): pass"
    }
  ],
  "config": {
    "model_name": "Salesforce/codet5p-770m",
    "optimization_level": "balanced",
    "analyze_performance": true
  }
}
```

### Model Training
```http
POST /train-refactoring-model
Content-Type: application/json

{
  "model_name": "Salesforce/codet5p-770m",
  "training_examples": [
    {
      "original_code": "def bad(): x=1; return x",
      "target_refactored": "def good(): return 1"
    }
  ]
}
```

## Configuration

### VS Code Settings

Access via `File > Preferences > Settings` and search for "Python Assistant":

```json
{
  "pythonAssistant.backendUrl": "http://localhost:8000",
  "pythonAssistant.ollamaUrl": "http://localhost:11434",
  "pythonAssistant.defaultModel": "Salesforce/codet5p-770m"
}
```

### Environment Variables

Create `.env` file in backend directory:

```env
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
OLLAMA_URL=http://localhost:11434
DEFAULT_MODEL=Salesforce/codet5p-770m
CUDA_VISIBLE_DEVICES=0
```

## Performance Tips

### For Test Generation
- Start with shorter timeout (30-60s) for initial exploration
- Increase timeout for complex modules
- Use mutation threshold 0.3-0.5 for balanced quality
- Ensure Ollama is running with appropriate model

### For Refactoring
- Use `codet5p-770m` for fast iterations
- Use `codet5p-2b` or `starcoderbase` for production refactoring
- Enable GPU if available (10-100x faster)
- Process files in batches for large codebases

### PPO Training
- Collect 50+ example pairs before training
- Use diverse examples (different complexity levels)
- Train for 3-5 epochs maximum
- Monitor reward function to avoid overfitting

## Troubleshooting

### Backend won't start
```bash
# Check Python version
python --version  # Should be 3.8+

# Check dependencies
pip install -r requirements.txt

# Check port availability
lsof -i :8000  # On Unix
netstat -ano | findstr :8000  # On Windows
```

### Pynguin errors
```bash
# Install/reinstall Pynguin
pip install --upgrade pynguin

# Check project structure has __init__.py
touch __init__.py
```

### Ollama connection issues
```bash
# Start Ollama
ollama serve

# Pull required model
ollama pull codellama

# Check status
curl http://localhost:11434/api/tags
```

### GPU not detected
```python
import torch
print(torch.cuda.is_available())  # Should be True
print(torch.cuda.get_device_name(0))  # Shows GPU name
```

### Out of memory
- Reduce batch size in PPO config
- Use smaller model (`codet5p-770m` instead of `2b`)
- Process fewer files simultaneously
- Enable gradient checkpointing

## Advanced Usage

### Custom Reward Function

Modify the reward function in `RefactoringModel` class:

```python
def custom_reward_function(self, original, refactored):
    # Your custom logic here
    score = 0.0
    
    # Example: Penalize long lines
    max_line_length = max(len(line) for line in refactored.split('\n'))
    if max_line_length > 80:
        score -= 0.1
    
    # Add other criteria...
    return score
```

### Training with Custom Dataset

```python
training_data = [
    {
        "original_code": "...",
        "target_refactored": "..."
    },
    # ... more examples
]

# Send to API
import requests
response = requests.post(
    "http://localhost:8000/train-refactoring-model",
    json={
        "model_name": "Salesforce/codet5p-770m",
        "training_examples": training_data
    }
)
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- **Pynguin** - Automated unit test generation
- **Hugging Face** - Transformer models and TRL library
- **Salesforce** - CodeT5+ models
- **BigCode** - StarCoder models
- **Ollama** - Local LLM inference

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check the documentation
- Review existing issues for solutions

---

**Note**: This extension requires significant computational resources for refactoring, especially with larger models. GPU acceleration is highly recommended for production use.
