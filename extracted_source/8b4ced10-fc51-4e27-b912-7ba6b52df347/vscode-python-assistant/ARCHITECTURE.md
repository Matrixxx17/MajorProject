# Python Assistant - Architecture Documentation

## Project Structure

```
vscode-python-assistant/
├── src/                          # VS Code Extension (TypeScript)
│   └── extension.ts              # Main extension logic
├── backend/                      # FastAPI Backend (Python)
│   ├── main.py                   # API server with all endpoints
│   └── requirements.txt          # Python dependencies
├── models/                       # Model training scripts
│   ├── train_refactoring_ppo.py  # PPO training script
│   └── training_data.json        # Sample training data
├── package.json                  # Extension manifest
├── tsconfig.json                 # TypeScript configuration
├── setup.sh                      # Automated setup script
├── README.md                     # Full documentation
├── QUICKSTART.md                 # Quick start guide
└── .gitignore                    # Git ignore rules
```

## Architecture Overview

### High-Level Flow

```
┌─────────────────┐
│   VS Code UI   │
│  (TypeScript)   │
└────────┬────────┘
         │
         │ HTTP/REST
         ▼
┌─────────────────┐
│  FastAPI Server │
│    (Python)     │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌──────────┐
│Pynguin │ │Transformers│
│+Ollama │ │  + TRL    │
└────────┘ └──────────┘
   Test       Refactor
```

## Component Details

### 1. VS Code Extension (`src/extension.ts`)

**Purpose**: User interface and VS Code integration

**Key Classes**:
- `PythonAssistantViewProvider`: Manages webview UI
- `FileInfo`: File metadata structure
- `AnalysisResult`: Context analysis results

**Main Functions**:
```typescript
- activate(): Extension entry point
- handleFileSelection(): File picker dialog
- handleFolderSelection(): Folder picker dialog
- analyzeContext(): Analyzes Python files
- handleTestGeneration(): Triggers test generation
- handleRefactoring(): Triggers refactoring
- createTestFiles(): Creates test files in workspace
- showRefactoringDiffs(): Shows before/after comparison
```

**UI Features**:
- Tabbed interface (Test Gen / Refactoring)
- Context analysis (single file / multiple / codebase)
- Real-time status updates
- Collapsible result sections
- Configuration inputs

### 2. Backend Server (`backend/main.py`)

**Purpose**: Core processing logic and AI integration

**Main Components**:

#### Test Generation Pipeline

1. **PynguinTestGenerator**
   - Runs Pynguin automated test generation
   - Configures search algorithms (MOSA)
   - Manages timeout and output paths

2. **CoverageAnalyzer**
   - Uses `coverage.py` for code coverage
   - Runs pytest to execute tests
   - Calculates coverage percentage

3. **MutationTester**
   - Uses `mutmut` for mutation testing
   - Validates test quality
   - Parses mutation scores

4. **LLMRefiner**
   - Sends tests to Ollama for refinement
   - Improves test readability
   - Validates generated code

**Pipeline Flow**:
```
Code → Pynguin → Coverage → Mutation → (if score > threshold) → LLM → Final Tests
```

#### Refactoring Pipeline

1. **CodeAnalyzer**
   - Calculates cyclomatic complexity (radon)
   - Measures maintainability index
   - Runs pylint for quality scores
   - Counts lines of code

2. **RefactoringModel**
   - Loads transformer models (CodeT5+, StarCoder)
   - Generates refactored code
   - Validates syntax
   - Supports PPO training

3. **RefactoringEngine**
   - Coordinates refactoring process
   - Compares metrics before/after
   - Identifies improvements
   - Generates performance reports

**Pipeline Flow**:
```
Code → Analyze → Transform → Validate → Compare → Report
```

### 3. PPO Training (`models/train_refactoring_ppo.py`)

**Purpose**: Fine-tune models with reinforcement learning

**Key Components**:

1. **CodeQualityReward**
   ```python
   Reward = 0.4 * complexity_improvement
          + 0.3 * maintainability_improvement  
          + 0.2 * conciseness_reward
          + 0.1 * syntax_validity
   ```

2. **RefactoringPPOTrainer**
   - Manages PPO training loop
   - Handles model generation
   - Calculates rewards
   - Updates model weights

**Training Process**:
```
1. Load base model (CodeT5+)
2. Prepare training examples
3. For each epoch:
   a. Generate refactored code
   b. Calculate reward
   c. Update model with PPO
4. Save fine-tuned model
```

## API Endpoints

### POST /generate-tests

Generate tests for Python files.

**Request**:
```json
{
  "files": [
    {
      "path": "/path/to/file.py",
      "name": "module_name",
      "content": "def func(): pass"
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

**Response**:
```json
{
  "test_files": [
    {
      "filename": "test_module_name.py",
      "path": "/path/to/test_module_name.py",
      "content": "import pytest...",
      "coverage": 0.95,
      "mutation_score": 0.75
    }
  ],
  "total_coverage": 0.95,
  "avg_mutation_score": 0.75,
  "message": "Success...",
  "pipeline_log": ["Step 1...", "Step 2..."]
}
```

### POST /refactor-code

Refactor Python code with AI.

**Request**:
```json
{
  "files": [
    {
      "path": "/path/to/file.py",
      "name": "module_name",
      "content": "def func(): pass"
    }
  ],
  "config": {
    "model_name": "Salesforce/codet5p-770m",
    "optimization_level": "balanced",
    "analyze_performance": true
  }
}
```

**Response**:
```json
{
  "refactorings": [
    {
      "filename": "module_name.py",
      "original_path": "/path/to/file.py",
      "refactored_code": "def func():\n    return None",
      "improvements": [
        "Reduced complexity by 25%",
        "Improved maintainability index"
      ],
      "performance_metrics": {
        "complexity_reduction": 25.0,
        "quality_score": 8.5,
        "maintainability_index": 75.0,
        "cyclomatic_complexity_before": 10.0,
        "cyclomatic_complexity_after": 7.5,
        "loc_before": 50,
        "loc_after": 35
      }
    }
  ],
  "total_files": 1,
  "message": "Successfully refactored 1 file(s)"
}
```

### POST /train-refactoring-model

Train/fine-tune refactoring model with PPO.

**Request**:
```json
{
  "model_name": "Salesforce/codet5p-770m",
  "training_examples": [
    {
      "original_code": "def bad():\n    x=1\n    return x",
      "target_refactored": "def good():\n    return 1"
    }
  ]
}
```

**Response**:
```json
{
  "message": "Training completed for 3 epochs",
  "stats": [...],
  "model_name": "Salesforce/codet5p-770m"
}
```

### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "healthy",
  "service": "Python Assistant API",
  "version": "2.0.0",
  "features": [
    "test_generation",
    "code_refactoring", 
    "ppo_training"
  ]
}
```

### GET /models/available

List available refactoring models.

**Response**:
```json
{
  "models": [
    {
      "name": "Salesforce/codet5p-770m",
      "type": "seq2seq",
      "size": "770M parameters",
      "recommended": true
    }
  ]
}
```

### GET /ollama-status

Check Ollama availability.

**Response**:
```json
{
  "status": "connected",
  "models": ["codellama", "llama2"]
}
```

## Data Flow

### Test Generation Flow

```
User Action:
├─ Select Python files → analyzeContext()
├─ Configure settings (Ollama, timeout, etc.)
└─ Click "Generate Tests"
   │
   ├─ Extension: handleTestGeneration()
   │  ├─ Read file contents
   │  └─ POST /generate-tests
   │
   ├─ Backend: generate_tests()
   │  ├─ For each file:
   │  │  ├─ PynguinTestGenerator.generate_tests()
   │  │  ├─ CoverageAnalyzer.calculate_coverage()
   │  │  ├─ MutationTester.run_mutation_testing()
   │  │  └─ (if threshold met) LLMRefiner.refine_tests()
   │  └─ Return test files
   │
   └─ Extension: Display results
      ├─ Show coverage/mutation scores
      └─ Offer to create test files
         └─ createTestFiles() → Write to disk
```

### Refactoring Flow

```
User Action:
├─ Select Python files → analyzeContext()
├─ Configure settings (model, optimization)
└─ Click "Refactor Code"
   │
   ├─ Extension: handleRefactoring()
   │  ├─ Read file contents
   │  └─ POST /refactor-code
   │
   ├─ Backend: refactor_code()
   │  ├─ Initialize RefactoringEngine
   │  ├─ For each file:
   │  │  ├─ CodeAnalyzer.calculate_complexity() [before]
   │  │  ├─ RefactoringModel.refactor_code()
   │  │  ├─ Validate syntax
   │  │  ├─ CodeAnalyzer.calculate_complexity() [after]
   │  │  └─ Calculate performance metrics
   │  └─ Return refactoring results
   │
   └─ Extension: Display results
      ├─ Show metrics comparison
      └─ showRefactoringDiffs()
         ├─ Create temp refactored file
         ├─ Open diff view
         └─ Prompt: Apply/Skip/Cancel
            └─ If Apply: Write refactored code
```

## Model Architecture

### CodeT5+ (Recommended)

```
Input: "Refactor this Python code: def foo()..."
  │
  ├─ Encoder (Transformer)
  │  └─ Contextual embeddings
  │
  ├─ Decoder (Transformer)
  │  └─ Generate refactored code
  │
  └─ Output: "def foo():\n    return ..."
```

**Sizes**:
- 770M params: Good balance (recommended)
- 2B params: Better quality, slower
- 16B params: Best quality, requires GPU

### PPO Training Architecture

```
┌──────────────────────────────┐
│      Base Model (CodeT5+)     │
│         + Value Head          │
└──────────────┬────────────────┘
               │
               ├─ Generate refactoring
               │
               ├─ Calculate reward
               │  ├─ Complexity improvement
               │  ├─ Maintainability
               │  ├─ Conciseness
               │  └─ Syntax validity
               │
               ├─ PPO Update
               │  ├─ Policy gradient
               │  ├─ Value function
               │  └─ Clip objective
               │
               └─ Iterate
```

**Reward Components**:
```
Total Reward = w1 * complexity_improvement    (0.4)
             + w2 * maintainability_gain      (0.3)
             + w3 * conciseness_reward        (0.2)
             + w4 * syntax_validity           (0.1)
```

## Configuration

### Extension Settings

Located in `package.json` → `contributes.configuration`:

```json
{
  "pythonAssistant.backendUrl": "http://localhost:8000",
  "pythonAssistant.ollamaUrl": "http://localhost:11434",
  "pythonAssistant.defaultModel": "Salesforce/codet5p-770m"
}
```

### Backend Configuration

Environment variables (`.env`):

```env
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
OLLAMA_URL=http://localhost:11434
DEFAULT_MODEL=Salesforce/codet5p-770m
CUDA_VISIBLE_DEVICES=0
```

### PPO Training Configuration

In `train_refactoring_ppo.py`:

```python
ppo_config = PPOConfig(
    model_name=model_name,
    learning_rate=1e-5,
    batch_size=4,
    mini_batch_size=1,
    gradient_accumulation_steps=4,
    ppo_epochs=4,
    target_kl=0.1,
    seed=42
)
```

## Performance Optimization

### Backend Optimizations

1. **Batch Processing**: Process multiple files in parallel
2. **Caching**: Cache model loads between requests
3. **GPU Acceleration**: Use CUDA when available
4. **Model Quantization**: Use INT8 for faster inference

### Extension Optimizations

1. **Lazy Loading**: Load webview only when needed
2. **Debouncing**: Debounce file selection events
3. **Streaming**: Stream results for large outputs
4. **Caching**: Cache analysis results

### Training Optimizations

1. **Gradient Accumulation**: Effective larger batch size
2. **Mixed Precision**: Use FP16 for faster training
3. **Gradient Checkpointing**: Reduce memory usage
4. **Early Stopping**: Stop when converged

## Security Considerations

1. **Input Validation**: Validate all file paths and code
2. **Sandbox Execution**: Run tests in isolated environment
3. **Rate Limiting**: Limit API requests
4. **Authentication**: Add API keys for production
5. **Code Injection**: Sanitize generated code

## Testing Strategy

### Unit Tests
- Test individual components (analyzer, generator)
- Mock external dependencies (Ollama, Pynguin)

### Integration Tests  
- Test full pipelines (test gen, refactoring)
- Use sample Python files

### End-to-End Tests
- Test extension → backend → response
- Verify file creation and diff view

## Deployment

### Development
```bash
# Backend
cd backend && python main.py

# Extension  
Press F5 in VS Code
```

### Production

**Backend**:
```bash
# Docker
docker build -t python-assistant-backend .
docker run -p 8000:8000 python-assistant-backend

# Or systemd service
sudo systemctl start python-assistant
```

**Extension**:
```bash
# Package
vsce package

# Publish
vsce publish
```

## Monitoring

### Metrics to Track

1. **Test Generation**:
   - Average coverage percentage
   - Average mutation score
   - Generation time
   - Success rate

2. **Refactoring**:
   - Average complexity reduction
   - Quality score improvement
   - Processing time
   - User acceptance rate

3. **System**:
   - API response time
   - Memory usage
   - GPU utilization
   - Error rate

### Logging

Logs are written to:
- Backend: stdout (can redirect to file)
- Extension: VS Code Output panel
- Training: WandB (if enabled)

## Future Enhancements

1. **Multi-language Support**: JavaScript, TypeScript, Java
2. **Custom Reward Functions**: User-defined quality metrics
3. **Incremental Refactoring**: Refactor specific functions
4. **Team Sharing**: Share trained models
5. **CI/CD Integration**: Automate in pipelines
6. **Web Interface**: Standalone web app
7. **Collaborative Editing**: Real-time collaboration

## Resources

- **Pynguin Docs**: https://pynguin.readthedocs.io
- **Transformers**: https://huggingface.co/docs/transformers
- **TRL**: https://huggingface.co/docs/trl
- **VS Code Extension API**: https://code.visualstudio.com/api

---

For questions or contributions, see README.md and CONTRIBUTING.md
