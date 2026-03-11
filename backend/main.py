from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import tempfile
import os
import ast
import json
import zipfile
import uuid
import shutil
import time
import threading
from pathlib import Path
import requests
import traceback
import sys

app = FastAPI(title="Codexter Test Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Directory setup ────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER  = os.path.join(BASE_DIR, "uploads")
EXTRACT_FOLDER = os.path.join(BASE_DIR, "extracted_source")
TESTS_FOLDER   = os.path.join(BASE_DIR, "generated_tests")

for d in (UPLOAD_FOLDER, EXTRACT_FOLDER, TESTS_FOLDER):
    os.makedirs(d, exist_ok=True)

# ── In-memory job store ────────────────────────────────────────────────────────
jobs: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic models
# ══════════════════════════════════════════════════════════════════════════════

class SingleFileRequest(BaseModel):
    code: str
    module_name: str
    directory: str
    file_path: str
    ollama_model:   str = "deepseek-coder:1.3b"
    ollama_url:     str = "http://localhost:11434"
    ollama_timeout: int = 120

class MultipleFileRequest(BaseModel):
    files: list  # list of {code, module_name, directory, file_path}
    ollama_model:   str = "deepseek-coder:1.3b"
    ollama_url:     str = "http://localhost:11434"
    ollama_timeout: int = 120

class SingleFileResponse(BaseModel):
    tests: str
    coverage: float
    mutation_score: float
    message: str
    pipeline_log: list = []

class RefactorRequest(BaseModel):
    code: str
    module_name: str
    file_path: str
    ollama_model:   str = "deepseek-coder:1.3b"
    ollama_url:     str = "http://localhost:11434"
    ollama_timeout: int = 120

class RefactorResponse(BaseModel):
    refactored_code: str
    summary: str
    message: str


# ══════════════════════════════════════════════════════════════════════════════
# Ollama helpers
# ══════════════════════════════════════════════════════════════════════════════

def call_ollama(prompt: str, ollama_url: str, model: str, timeout: int) -> str:
    response = requests.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def generate_tests_ollama(
    code: str,
    module_name: str,
    context: str = "",
    ollama_url: str = "http://localhost:11434",
    model: str = "deepseek-coder:1.3b",
    timeout: int = 120,
) -> str:
    context_block = f"\n\n# Context from other project files:\n{context}" if context else ""
    prompt = f"""You are an expert Python test engineer. Write comprehensive pytest tests for the following Python module.

Module name: {module_name}

Source code:
```python
{code}{context_block}
```

Requirements:
1. Use pytest framework only
2. Import the module correctly using `from {module_name} import *` or specific imports
3. Test all public functions and classes
4. Cover edge cases and boundary conditions
5. Use descriptive test function names: test_<function>_<scenario>
6. Add a one-line docstring to each test function
7. Use pytest.mark.parametrize for similar test cases
8. Use pytest.raises for exception testing
9. Return ONLY valid, executable Python — no markdown fences, no explanations

Start your response directly with `import pytest`."""

    raw = call_ollama(prompt, ollama_url, model, timeout)
    return _clean_code(raw)


def refactor_code_ollama(
    code: str,
    module_name: str,
    ollama_url: str = "http://localhost:11434",
    model: str = "deepseek-coder:1.3b",
    timeout: int = 120,
) -> tuple[str, str]:
    prompt = f"""You are an expert Python software engineer specialising in clean code and refactoring.

Refactor the following Python module to improve:
- Readability and clarity
- Code structure and organisation
- Performance where obvious improvements exist
- PEP 8 compliance
- Type hints (add where missing)
- Docstrings (add where missing)
- Removal of dead code or redundancy

Module: {module_name}

```python
{code}
```

Respond in exactly two sections, using these exact headers:

REFACTORED_CODE:
```python
<the complete refactored module here>
```

SUMMARY:
<bullet-point list of changes made>"""

    raw = call_ollama(prompt, ollama_url, model, timeout)
    return _parse_refactor_response(raw, code)


def _parse_refactor_response(raw: str, original: str) -> tuple[str, str]:
    code_part    = original
    summary_part = "No summary provided."

    if "REFACTORED_CODE:" in raw and "SUMMARY:" in raw:
        parts        = raw.split("SUMMARY:", 1)
        summary_part = parts[1].strip()
        code_section = parts[0].split("REFACTORED_CODE:", 1)[1].strip()
        code_part    = _clean_code(code_section)
    else:
        cleaned = _clean_code(raw)
        if cleaned:
            code_part = cleaned

    return code_part, summary_part


def _clean_code(raw: str) -> str:
    lines = raw.strip().split("\n")
    cleaned, in_block, found_fence = [], False, False

    for line in lines:
        s = line.strip()
        if s.startswith("```python"):
            in_block, found_fence = True, True
            continue
        if s.startswith("```") and in_block:
            in_block = False
            continue
        if s.startswith("```") and not found_fence:
            in_block, found_fence = True, True
            continue
        if not found_fence or in_block:
            cleaned.append(line)

    result = "\n".join(cleaned).strip()
    return result if result else raw


# ══════════════════════════════════════════════════════════════════════════════
# Project context extraction
# ══════════════════════════════════════════════════════════════════════════════

def get_file_context(target_file: str, all_files: list) -> str:
    context = []
    for fp in all_files:
        if fp == target_file:
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
            rel  = os.path.basename(fp)
            summary = [f"# File: {rel}"]

            doc = ast.get_docstring(tree)
            if doc:
                summary.append(f'"""{doc}"""')

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                    args = [a.arg for a in node.args.args]
                    line = f"def {node.name}({', '.join(args)}):"
                    fn_doc = ast.get_docstring(node)
                    if fn_doc:
                        line += f"  # {fn_doc.splitlines()[0]}"
                    summary.append(line)
                elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    summary.append(f"class {node.name}:")
                    cls_doc = ast.get_docstring(node)
                    if cls_doc:
                        summary.append(f'    """{cls_doc.splitlines()[0]}"""')
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            m_args = [a.arg for a in item.args.args]
                            m_line = f"    def {item.name}({', '.join(m_args)}):"
                            m_doc  = ast.get_docstring(item)
                            if m_doc:
                                m_line += f"  # {m_doc.splitlines()[0]}"
                            summary.append(m_line)

            if len(summary) > 1:
                context.append("\n".join(summary))
        except Exception:
            pass

    return "\n\n".join(context)


# ══════════════════════════════════════════════════════════════════════════════
# Metrics
# ══════════════════════════════════════════════════════════════════════════════

def calculate_coverage(module_path: str, test_path: str, work_dir: str) -> tuple[float, list]:
    logs = []
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", test_path,
                f"--cov={module_path}",
                "--cov-report=json",
                "-v", "--tb=short", "-p", "no:cacheprovider",
            ],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHONPATH": work_dir},
        )
        logs.append(f"pytest exit code: {result.returncode}")

        cov_json = os.path.join(work_dir, "coverage.json")
        if os.path.exists(cov_json):
            with open(cov_json) as f:
                data = json.load(f)
            pct = data.get("totals", {}).get("percent_covered", 0.0)
            logs.append(f"Coverage: {pct:.1f}%")
            return pct / 100.0, logs

        for line in result.stdout.split("\n"):
            if "TOTAL" in line:
                for part in line.split():
                    if part.endswith("%"):
                        try:
                            return float(part.rstrip("%")) / 100.0, logs
                        except ValueError:
                            pass

        logs.append("Could not parse coverage — defaulting to 0.0")
        return 0.0, logs

    except subprocess.TimeoutExpired:
        logs.append("Coverage timed out")
        return 0.0, logs
    except Exception as e:
        logs.append(f"Coverage error: {e}")
        return 0.0, logs


def calculate_mutation_score(module_name: str, test_path: str, work_dir: str) -> tuple[float, list]:
    logs = []
    try:
        pre = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "--tb=short", "-p", "no:cacheprovider"],
            cwd=work_dir, capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": work_dir},
        )
        if pre.returncode != 0:
            logs.append("Tests failed pre-mutation — skipping mutmut, using default score 0.3")
            return 0.3, logs

        subprocess.run(
            [sys.executable, "-m", "mutmut", "run",
             "--paths-to-mutate", f"{module_name}.py", "--no-progress"],
            cwd=work_dir, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": work_dir},
        )

        res = subprocess.run(
            [sys.executable, "-m", "mutmut", "results"],
            cwd=work_dir, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": work_dir},
        )
        logs.append(f"mutmut output: {res.stdout[:300]}")
        score = _parse_mutation_score(res.stdout)
        logs.append(f"Mutation score: {score:.2%}")
        return score, logs

    except subprocess.TimeoutExpired:
        logs.append("Mutation testing timed out — using default 0.3")
        return 0.3, logs
    except Exception as e:
        logs.append(f"Mutation error: {e}")
        return 0.3, logs


def _parse_mutation_score(output: str) -> float:
    killed, survived = 0, 0
    for line in output.split("\n"):
        parts = line.split()
        for i, part in enumerate(parts):
            if "killed" in part.lower() and i > 0:
                try: killed = int(parts[i - 1])
                except (ValueError, IndexError): pass
            if "survived" in part.lower() and i > 0:
                try: survived = int(parts[i - 1])
                except (ValueError, IndexError): pass
    total = killed + survived
    if total > 0:
        return killed / total
    for line in output.split("\n"):
        for part in line.split():
            if part.endswith("%"):
                try: return float(part.rstrip("%")) / 100
                except ValueError: pass
    return 0.5


# ══════════════════════════════════════════════════════════════════════════════
# Shared: process one file inside a job (used by single + multiple workers)
# ══════════════════════════════════════════════════════════════════════════════

def _process_one_file(
    job_id: str,
    code: str,
    module_name: str,
    file_path: str,
    ollama_url: str,
    model: str,
    timeout: int,
    context: str = "",
) -> dict:
    """
    Generate tests + metrics for a single file.
    Updates jobs[job_id]['current_file'] while running.
    Returns a result dict (same schema as ZIP job results).
    """
    jobs[job_id]["current_file"] = f"{module_name}.py"
    work_dir = tempfile.mkdtemp(prefix="codexter_")
    entry = {"file": f"{module_name}.py", "status": "pending"}

    try:
        # Write source so pytest can import it
        src_path = os.path.join(work_dir, f"{module_name}.py")
        with open(src_path, "w") as f:
            f.write(code)
        with open(os.path.join(work_dir, "__init__.py"), "w") as f:
            f.write("")

        # ── Generate tests ────────────────────────────────────────────────
        tests = generate_tests_ollama(
            code=code,
            module_name=module_name,
            context=context,
            ollama_url=ollama_url,
            model=model,
            timeout=timeout,
        )
        if not tests or not tests.strip():
            raise ValueError("Ollama returned empty tests")

        ast.parse(tests)  # validate syntax

        # Save to TESTS_FOLDER so it can be bundled into a download ZIP
        out_name = f"test_{module_name}.py"
        out_path = os.path.join(TESTS_FOLDER, out_name)
        with open(out_path, "w") as tf:
            tf.write(tests)

        test_path = os.path.join(work_dir, out_name)
        with open(test_path, "w") as tf:
            tf.write(tests)

        # ── Metrics ───────────────────────────────────────────────────────
        try:
            cov, _ = calculate_coverage(src_path, test_path, work_dir)
            mut, _ = calculate_mutation_score(module_name, test_path, work_dir)
            metrics = {
                "coverage_percent": round(cov * 100, 2),
                "mutation_score":   round(mut, 4),
                "has_errors":       False,
            }
        except Exception:
            cov, mut = 0.0, 0.0
            metrics = {"coverage_percent": 0.0, "mutation_score": 0.0, "has_errors": True}

        entry.update({
            "status":      "success",
            "test_file":   out_name,
            "full_path":   out_path,
            "content":     tests,
            "coverage":    cov,
            "mutation_score": mut,
            "metrics":     metrics,
        })

    except SyntaxError as e:
        entry["status"] = "failed"
        entry["error"]  = f"LLM returned invalid Python: {e}"
    except Exception as e:
        entry["status"] = "failed"
        entry["error"]  = str(e)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return entry


# ══════════════════════════════════════════════════════════════════════════════
# Background workers
# ══════════════════════════════════════════════════════════════════════════════

def process_single_job(
    job_id: str,
    code: str,
    module_name: str,
    file_path: str,
    ollama_url: str,
    model: str,
    timeout: int,
):
    """Background worker for a single-file job."""
    jobs[job_id]["status"]   = "processing"
    jobs[job_id]["progress"] = 0
    jobs[job_id]["total_files"] = 1

    try:
        entry = _process_one_file(
            job_id=job_id,
            code=code,
            module_name=module_name,
            file_path=file_path,
            ollama_url=ollama_url,
            model=model,
            timeout=timeout,
        )

        jobs[job_id]["results"]  = [entry]
        jobs[job_id]["progress"] = 100

        if entry["status"] == "success":
            cov = entry.get("coverage", 0.0)
            mut = entry.get("mutation_score", 0.0)
            jobs[job_id]["status"]  = "completed"
            jobs[job_id]["message"] = (
                f"Tests generated. Coverage: {cov:.1%}, Mutation: {mut:.1%}"
            )
            # Build a single-file download ZIP
            results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
            with zipfile.ZipFile(results_zip, "w") as zout:
                zout.write(entry["full_path"], entry["test_file"])
            jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        else:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = entry.get("error", "Unknown error")

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


def process_multiple_job(
    job_id: str,
    files: list,       # list of dicts: {code, module_name, directory, file_path}
    ollama_url: str,
    model: str,
    timeout: int,
):
    """Background worker for a multiple-file job."""
    jobs[job_id]["status"]      = "processing"
    jobs[job_id]["progress"]    = 0
    jobs[job_id]["results"]     = []
    jobs[job_id]["total_files"] = len(files)

    # Build a list of real file paths for cross-file context
    # (only those that are actual paths on disk; code passed directly won't have them)
    all_real_paths = [f["file_path"] for f in files if os.path.isfile(f.get("file_path", ""))]

    try:
        for i, file_info in enumerate(files):
            code        = file_info["code"]
            module_name = file_info["module_name"]
            file_path   = file_info.get("file_path", "")

            jobs[job_id]["current_file"] = f"{module_name}.py"

            # Build context from sibling files (mirrors ZIP behaviour)
            context = get_file_context(file_path, all_real_paths) if all_real_paths else ""

            entry = _process_one_file(
                job_id=job_id,
                code=code,
                module_name=module_name,
                file_path=file_path,
                ollama_url=ollama_url,
                model=model,
                timeout=timeout,
                context=context,
            )

            jobs[job_id]["results"].append(entry)
            jobs[job_id]["progress"] = int(((i + 1) / len(files)) * 100)

        # Bundle all generated test files into a download ZIP
        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for r in jobs[job_id]["results"]:
                if r["status"] == "success" and "full_path" in r:
                    zout.write(r["full_path"], r["test_file"])

        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["status"]       = "completed"
        jobs[job_id]["message"]      = "All files processed"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


def process_zip_job(
    job_id: str,
    zip_path: str,
    extract_path: str,
    model: str,
    ollama_url: str,
    timeout: int,
):
    jobs[job_id]["status"]   = "processing"
    jobs[job_id]["progress"] = 0
    jobs[job_id]["results"]  = []

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_path)

        python_files = [
            os.path.join(root, f)
            for root, _, files in os.walk(extract_path)
            for f in files
            if f.endswith(".py") and not f.startswith("test_")
        ]

        total = len(python_files)
        jobs[job_id]["total_files"] = total

        if total == 0:
            jobs[job_id]["status"]  = "completed"
            jobs[job_id]["message"] = "No Python files found in ZIP."
            return

        for i, py_file in enumerate(python_files):
            file_name   = os.path.basename(py_file)
            module_name = os.path.splitext(file_name)[0]
            jobs[job_id]["current_file"] = file_name

            with open(py_file, "r", encoding="utf-8") as f:
                code = f.read()

            context = get_file_context(py_file, python_files)
            entry   = {"file": file_name, "status": "pending"}

            try:
                tests = generate_tests_ollama(
                    code=code,
                    module_name=module_name,
                    context=context,
                    ollama_url=ollama_url,
                    model=model,
                    timeout=timeout,
                )
                if not tests or not tests.strip():
                    raise ValueError("Ollama returned empty tests")

                ast.parse(tests)

                out_name = f"test_{module_name}.py"
                out_path = os.path.join(TESTS_FOLDER, out_name)
                with open(out_path, "w", encoding="utf-8") as tf:
                    tf.write(tests)

                try:
                    cov, _ = calculate_coverage(py_file, out_path, extract_path)
                    mut, _ = calculate_mutation_score(module_name, out_path, extract_path)
                    metrics_summary = {
                        "coverage_percent": round(cov * 100, 2),
                        "mutation_score":   round(mut, 4),
                        "has_errors":       False,
                    }
                except Exception:
                    metrics_summary = {"coverage_percent": 0.0, "mutation_score": 0.0, "has_errors": True}

                entry.update({
                    "status":    "success",
                    "test_file": out_name,
                    "full_path": out_path,
                    "content":   tests,
                    "metrics":   metrics_summary,
                })

            except SyntaxError as e:
                entry["status"] = "failed"
                entry["error"]  = f"LLM returned invalid Python: {e}"
            except Exception as e:
                entry["status"] = "failed"
                entry["error"]  = str(e)

            jobs[job_id]["results"].append(entry)
            jobs[job_id]["progress"] = int(((i + 1) / total) * 100)

        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for r in jobs[job_id]["results"]:
                if r["status"] == "success" and "full_path" in r:
                    zout.write(r["full_path"], r["test_file"])

        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["status"]       = "completed"
        jobs[job_id]["message"]      = "Analysis complete"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/generate-tests")
async def generate_tests_endpoint(req: SingleFileRequest):
    """
    Single-file test generation — now job-based (same as ZIP).
    Returns {job_id} immediately; poll /status/{job_id} for results.
    """
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status":       "queued",
        "submitted_at": time.time(),
        "filename":     f"{req.module_name}.py",
        "scope":        "single",
    }

    thread = threading.Thread(
        target=process_single_job,
        args=(
            job_id,
            req.code,
            req.module_name,
            req.file_path,
            req.ollama_url,
            req.ollama_model,
            req.ollama_timeout,
        ),
        daemon=True,
    )
    thread.start()

    return {"message": "Job submitted", "job_id": job_id, "scope": "single"}


@app.post("/generate-tests-multiple")
async def generate_tests_multiple_endpoint(req: MultipleFileRequest):
    """
    Multiple-file test generation — job-based.
    
    Expected body:
    {
      "files": [
        {"code": "...", "module_name": "foo", "directory": "/path", "file_path": "/path/foo.py"},
        ...
      ],
      "ollama_model": "deepseek-coder:1.3b",
      "ollama_url": "http://localhost:11434",
      "ollama_timeout": 120
    }

    Returns {job_id} immediately; poll /status/{job_id} for results.
    """
    if not req.files:
        raise HTTPException(status_code=400, detail="No files provided")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status":       "queued",
        "submitted_at": time.time(),
        "total_files":  len(req.files),
        "scope":        "multiple",
    }

    thread = threading.Thread(
        target=process_multiple_job,
        args=(
            job_id,
            req.files,
            req.ollama_url,
            req.ollama_model,
            req.ollama_timeout,
        ),
        daemon=True,
    )
    thread.start()

    return {"message": "Job submitted", "job_id": job_id, "scope": "multiple"}


@app.post("/refactor", response_model=RefactorResponse)
async def refactor_endpoint(req: RefactorRequest):
    """Refactor a Python file using Ollama (synchronous — fast enough)."""
    try:
        refactored, summary = refactor_code_ollama(
            code=req.code,
            module_name=req.module_name,
            ollama_url=req.ollama_url,
            model=req.ollama_model,
            timeout=req.ollama_timeout,
        )
        return RefactorResponse(
            refactored_code=refactored,
            summary=summary,
            message="Refactoring complete",
        )
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=500, detail={
            "error": f"Cannot connect to Ollama at {req.ollama_url}"})
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.post("/analyze_zip")
async def analyze_zip(
    file:           UploadFile = File(...),
    ollama_model:   str = "deepseek-coder:1.3b",
    ollama_url:     str = "http://localhost:11434",
    ollama_timeout: int = 120,
):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    job_id  = str(uuid.uuid4())
    job_dir = os.path.join(EXTRACT_FOLDER, job_id)
    os.makedirs(job_dir)

    zip_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{file.filename}")
    contents = await file.read()
    with open(zip_path, "wb") as f:
        f.write(contents)

    jobs[job_id] = {
        "status":       "queued",
        "submitted_at": time.time(),
        "filename":     file.filename,
        "scope":        "zip",
    }

    thread = threading.Thread(
        target=process_zip_job,
        args=(job_id, zip_path, job_dir, ollama_model, ollama_url, ollama_timeout),
        daemon=True,
    )
    thread.start()

    return {"message": "Job submitted", "job_id": job_id}


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/download_tests/{job_id}")
async def download_tests(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    zip_path = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="Results ZIP not ready yet")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"generated_tests_{jobs[job_id].get('filename', job_id)}.zip",
    )


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "Codexter", "version": "2.1.0"}


@app.get("/ollama-status")
async def ollama_status(ollama_url: str = "http://localhost:11434"):
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            return {"status": "connected", "models": models}
        return {"status": "error", "message": "Unexpected response"}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    print("Starting Codexter API — http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)