# Codexter

> **AI-powered test case generation & code refactoring — right inside VS Code.**

Codexter is a VS Code extension backed by a local FastAPI server. It analyses your Python source files and can automatically generate unit tests using Pynguin algorithms and/or local LLMs (via Ollama), and refactor your code for improved readability, PEP 8 compliance, and reduced cyclomatic complexity — all without sending your code to the cloud.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Backend Setup](#backend-setup)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Create a Virtual Environment](#2-create-a-virtual-environment)
  - [3. Activate the Virtual Environment](#3-activate-the-virtual-environment)
  - [4. Install Python Dependencies](#4-install-python-dependencies)
  - [5. Start the Backend Server](#5-start-the-backend-server)
- [Ollama Setup (Local LLMs)](#ollama-setup-local-llms)
- [Extension Setup](#extension-setup)
  - [Running from Source](#running-from-source)
  - [Installing as a VSIX](#installing-as-a-vsix)
- [Using Codexter](#using-codexter)
  - [Test Generation — Single File](#test-generation--single-file)
  - [Test Generation — ZIP Archive](#test-generation--zip-archive)
  - [Code Refactoring](#code-refactoring)
- [Generation Approaches](#generation-approaches)
- [Refactoring Modes](#refactoring-modes)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

---

## Features

- **Automated unit test generation** for Python files using:
  - Pynguin algorithms: `RANDOM`, `WHOLE_SUITE`, `DYNAMOSA`
  - Local LLMs via Ollama: `deepseek-coder:1.3b`, `codellama:7b`
  - Hybrid mode combining both
  - Ensemble mode for batch/ZIP analysis
- **Code refactoring** via two strategies:
  - PPO-style iterative refactoring with reward scoring (cyclomatic complexity, PEP 8, Halstead metrics, LOC)
  - Multi-model refactoring using a panel of LLMs
- **Coverage & mutation scoring** reported after generation
- **Batch ZIP processing** — drop in an entire project archive and generate tests for all `.py` files
- **Auto-detection** of the active Python file in the editor
- **Fully local** — no code leaves your machine

---

## Architecture Overview

```
VS Code Extension (TypeScript)
        │
        │  HTTP (localhost:8000)
        ▼
FastAPI Backend (Python)
        │
        ├── Pynguin  (subprocess)
        ├── Ollama   (HTTP localhost:11434)
        ├── Coverage.py
        └── MutPy / Radon / Pycodestyle
```

The extension communicates with the backend over a local REST API. All LLM inference runs through Ollama, which must be running separately.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10 + | 3.11 recommended |
| Node.js | 18 + | Required to build/run the extension |
| VS Code | 1.80 + | |
| Ollama | Latest | [ollama.com](https://ollama.com) |
| Java | 11 + | Required by Pynguin internally |
| Git | Any | |

---

## Backend Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/codexter.git
cd codexter
```

### 2. Create a Virtual Environment

It is strongly recommended to isolate the backend dependencies in a virtual environment.

**macOS / Linux**
```bash
python3 -m venv venv
```

**Windows (Command Prompt)**
```cmd
python -m venv venv
```

**Windows (PowerShell)**
```powershell
python -m venv venv
```

### 3. Activate the Virtual Environment

**macOS / Linux**
```bash
source venv/bin/activate
```

**Windows (Command Prompt)**
```cmd
venv\Scripts\activate.bat
```

**Windows (PowerShell)**
```powershell
venv\Scripts\Activate.ps1
```

You should see `(venv)` prefixed in your terminal prompt once the environment is active.

### 4. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

If a `requirements.txt` is not yet present in the repo, install the core packages directly:

```bash
pip install fastapi uvicorn pynguin requests radon pycodestyle mutpy
```

> **Note:** `pynguin` requires Java 11+ to be installed and available on your `PATH`.

To verify Pynguin works:
```bash
pynguin --help
```

### 5. Start the Backend Server

With the virtual environment active, run:

```bash
python main.py
```

The API will be available at `http://localhost:8000`.  
Interactive API docs (Swagger UI) are at `http://localhost:8000/docs`.

To verify the backend is healthy:
```bash
curl http://localhost:8000/health
# {"status":"healthy","service":"Codexter","version":"2.3.0"}
```

---

## Ollama Setup (Local LLMs)

Codexter uses [Ollama](https://ollama.com) to run LLMs locally for test generation and code refactoring.

### Install Ollama

Download and install from [https://ollama.com/download](https://ollama.com/download), then start the service:

```bash
ollama serve
```

### Pull the Required Models

Codexter uses the following models. Pull them before running LLM-based features:

```bash
# For test generation
ollama pull deepseek-coder:1.3b
ollama pull codellama:7b

# For refactoring
ollama pull deepseek-coder:1.3b
ollama pull starcoder2:3b
ollama pull codellama:7b
```

To check which models are available:
```bash
ollama list
```

You can also verify Ollama connectivity through the Codexter API:
```bash
curl http://localhost:8000/ollama-status
```

---

## Extension Setup

### Running from Source

1. Open the `codexter` repository folder in VS Code.

2. Install Node.js dependencies:
   ```bash
   npm install
   ```

3. Compile the TypeScript extension:
   ```bash
   npm run compile
   ```

4. Press `F5` (or go to **Run → Start Debugging**) to launch a new VS Code Extension Development Host window with Codexter loaded.

### Installing as a VSIX

To build a packaged extension:

```bash
npm install -g @vscode/vsce
vsce package
```

This generates a `.vsix` file. To install it in VS Code:

```
Extensions sidebar → ··· (More Actions) → Install from VSIX…
```

Or via the command line:
```bash
code --install-extension codexter-*.vsix
```

---

## Using Codexter

Once both the backend server and Ollama are running, open the Codexter panel from the VS Code Activity Bar or by running the command:

```
Codexter: Open View
```

The panel includes three tabs: **Single File**, **ZIP Archive**, and **Refactor**.

### Test Generation — Single File

1. Open a `.py` file in the editor — it will be auto-detected in the panel.
2. Alternatively, click **Browse** to manually pick a Python file.
3. Select your [generation approach](#generation-approaches).
4. Click **Generate Tests**.
5. A progress bar tracks the pipeline stages. On completion, coverage and mutation scores are shown.
6. Click **Save Test File** to write the generated tests to disk.

### Test Generation — ZIP Archive

1. Click **Browse ZIP** and select a `.zip` archive containing `.py` source files.
2. Choose an analysis mode:
   - **Single** — each file is processed independently.
   - **Ensemble** — files are cross-analysed for better coverage.
3. Click **Analyse ZIP**.
4. Results are displayed in a summary table with per-file coverage, mutation scores, and status.
5. Download the full test suite as a ZIP via the **Download** link.

### Code Refactoring

1. Open a `.py` file — it will be auto-detected.
2. Choose a refactoring mode:
   - **PPO Refactor** — iterative reward-based refactoring.
   - **Multi-Model Refactor** — consensus-driven refactoring across multiple LLMs.
3. Click **Run**.
4. A diff view shows the changes. Click **Save** to overwrite the original file.

---

## Generation Approaches

| Approach | Description |
|---|---|
| **Pynguin** | Uses one or more Pynguin search-based algorithms (`RANDOM`, `WHOLE_SUITE`, `DYNAMOSA`). Fast and deterministic. |
| **LLM** | Generates tests using one or more Ollama models. More human-readable tests. |
| **Hybrid** | Combines a single Pynguin algorithm with a single LLM for the best of both. |
| **Ensemble (ZIP only)** | Runs multiple strategies across all files and picks the highest-scoring result per file. |

---

## Refactoring Modes

### PPO Refactor

Inspired by Proximal Policy Optimisation, this mode iteratively refactors the code and scores each iteration using a weighted reward function:

| Metric | Weight |
|---|---|
| Cyclomatic complexity reduction | 35% |
| PEP 8 compliance | 30% |
| Halstead difficulty reduction | 20% |
| Lines of code reduction | 15% |

The loop runs for up to 5 iterations or stops early when the reward exceeds 0.6.

### Multi-Model Refactor

Sends the code to `deepseek-coder:1.3b`, `starcoder2:3b`, and `codellama:7b` in parallel. The best-scoring result (by the same reward function) is selected as the final output.

---

## API Reference

The backend exposes the following endpoints. Full interactive docs are at `http://localhost:8000/docs`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/ollama-status` | Ollama connectivity & available models |
| `GET` | `/check-models` | Which refactor models are pulled in Ollama |
| `POST` | `/generate-tests` | Submit a single-file test generation job |
| `POST` | `/generate-tests-multiple` | Submit a multi-file test generation job |
| `POST` | `/analyze_zip` | Submit a ZIP archive for batch test generation |
| `GET` | `/status/{job_id}` | Poll job status and progress |
| `GET` | `/download_tests/{job_id}` | Download generated tests as a ZIP |
| `POST` | `/refactor` | Synchronous single-model refactor |
| `POST` | `/refactor-ppo` | Submit a PPO refactor job |
| `POST` | `/refactor-multimodel` | Submit a multi-model refactor job |
| `POST` | `/analyze_strategy` | Get recommended test strategy for a code snippet |
| `POST` | `/analyze_quality` | Score the quality of a generated test suite |
| `GET` | `/config` | Get current backend configuration |
| `POST` | `/config` | Update backend configuration |

---

## Configuration

The backend stores its configuration in `test_config.json` (created automatically on first run).

| Key | Default | Description |
|---|---|---|
| `default_strategy` | `"auto"` | Default test generation strategy |
| `enable_quality_analysis` | `true` | Run quality analysis after generation |
| `enable_ensemble` | `false` | Enable ensemble mode by default |
| `quality_threshold` | `70.0` | Minimum quality score to accept results |
| `max_concurrency` | `3` | Max parallel jobs for ZIP processing |

You can update the config at runtime via `POST /config` or by editing `test_config.json` directly and restarting the server.

---

## Troubleshooting

**Backend won't start**
- Ensure the virtual environment is activated before running `python main.py`.
- Check that port 8000 is not in use: `lsof -i :8000` (macOS/Linux) or `netstat -ano | findstr :8000` (Windows).

**Pynguin fails or is not found**
- Confirm Java 11+ is installed: `java -version`.
- Confirm Pynguin is installed in the active venv: `pip show pynguin`.
- The environment variable `PYNGUIN_DANGER_AWARE=1` is set automatically by the backend.

**Ollama models not found**
- Run `ollama list` to confirm models are pulled.
- Ensure `ollama serve` is running before starting the backend.
- The default Ollama URL is `http://localhost:11434`. If you run Ollama on a different port, update the `ollama_url` field in requests.

**Extension shows "Backend offline"**
- Confirm the backend is running at `http://localhost:8000/health`.
- Check for firewall rules blocking localhost traffic.
- Restart VS Code after starting the backend.

**PowerShell script execution policy error (Windows)**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---
