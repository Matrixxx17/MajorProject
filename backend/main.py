from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import tempfile
import os
import ast
import json
from pathlib import Path
import requests
import coverage
import pytest

app = FastAPI(title="Test Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TestGenerationRequest(BaseModel):
    code: str
    module_name: str
    directory: str
    file_path: str
    ollama_model: str = "deepseek-coder:1.3b"
    ollama_url: str = "http://localhost:11434"
    pynguin_timeout: int = 60
    mutation_threshold: float = 0.3

class TestGenerationResponse(BaseModel):
    tests: str
    mutation_score: float
    coverage: float
    message: str
    pynguin_tests: str = None
    refined_tests: str = None
    pipeline_log: list = []

class PynguinTestGenerator:
    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
        self.output_dir = os.path.join(temp_dir, "pynguin_output")
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_tests(self, code: str, module_name: str, timeout: int = 60) -> tuple[str, list]:
        """Generate tests using Pynguin with comprehensive logging"""
        logs = []
        
        # Write code to temporary file
        module_file = os.path.join(self.temp_dir, f"{module_name}.py")
        with open(module_file, 'w') as f:
            f.write(code)
        
        logs.append(f"Created module file: {module_file}")
        
        # Create __init__.py for proper module structure
        init_file = os.path.join(self.temp_dir, "__init__.py")
        with open(init_file, 'w') as f:
            f.write("")
        
        try:
            cmd = [
                "pynguin",
                "--project-path", self.temp_dir,
                "--module-name", module_name,
                "--output-path", self.output_dir,
                "--maximum-search-time", str(timeout),
                "--assertion-generation", "MUTATION_ANALYSIS",
                "--algorithm", "MOSA",  # Many-objective sorting algorithm
                "--create-coverage-report", "TRUE",
                "--show-progress", "FALSE",
            ]
            
            logs.append(f"Running Pynguin command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
                cwd=self.temp_dir
            )
            
            logs.append(f"Pynguin stdout: {result.stdout[:500]}")
            
            if result.returncode != 0:
                logs.append(f"Pynguin stderr: {result.stderr}")
                raise Exception(f"Pynguin failed with return code {result.returncode}")
            
            # Read generated test file
            test_file = os.path.join(self.output_dir, f"test_{module_name}.py")
            if os.path.exists(test_file):
                with open(test_file, 'r') as f:
                    test_content = f.read()
                logs.append(f"Generated test file with {len(test_content)} characters")
                return test_content, logs
            else:
                # Try alternative naming
                test_files = list(Path(self.output_dir).glob("test_*.py"))
                if test_files:
                    with open(test_files[0], 'r') as f:
                        test_content = f.read()
                    logs.append(f"Found alternative test file: {test_files[0]}")
                    return test_content, logs
                else:
                    raise Exception("Pynguin did not generate test file")
                
        except subprocess.TimeoutExpired:
            logs.append("Pynguin execution timed out")
            raise Exception("Pynguin execution timed out")
        except Exception as e:
            logs.append(f"Error running Pynguin: {str(e)}")
            raise Exception(f"Error running Pynguin: {str(e)}")

class CoverageAnalyzer:
    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
    
    def calculate_coverage(self, module_name: str, test_file: str) -> tuple[float, list]:
        """Calculate code coverage using coverage.py"""
        logs = []
        
        try:
            # Write test file
            test_path = os.path.join(self.temp_dir, f"test_{module_name}.py")
            with open(test_path, 'w') as f:
                f.write(test_file)
            
            logs.append(f"Written test file to: {test_path}")
            
            # Initialize coverage
            cov = coverage.Coverage(
                source=[self.temp_dir],
                omit=['*/test_*.py', '*/__pycache__/*']
            )
            
            cov.start()
            
            # Run tests with pytest
            pytest_args = [
                test_path,
                "-v",
                "--tb=short"
            ]
            
            logs.append(f"Running pytest: {' '.join(pytest_args)}")
            
            result = pytest.main(pytest_args)
            
            cov.stop()
            cov.save()
            
            # Get coverage data
            total = cov.report()
            
            logs.append(f"Coverage calculated: {total}%")
            
            return total / 100.0, logs
            
        except Exception as e:
            logs.append(f"Coverage calculation failed: {str(e)}")
            return 0.0, logs

class MutationTester:
    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
    
    def run_mutation_testing(self, module_name: str, test_code: str) -> tuple[dict, list]:
        """Run mutation testing using mutmut"""
        logs = []
        
        # Write test file
        test_file = os.path.join(self.temp_dir, f"test_{module_name}.py")
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        logs.append(f"Written test file for mutation testing")
        
        try:
            # First, run the tests to ensure they pass
            pytest_result = subprocess.run(
                ["pytest", test_file, "-v"],
                cwd=self.temp_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if pytest_result.returncode != 0:
                logs.append(f"Tests failed before mutation: {pytest_result.stdout}")
                return {
                    "mutation_score": 0.0,
                    "details": "Tests must pass before mutation testing"
                }, logs
            
            logs.append("Tests passed, starting mutation testing")
            
            # Run mutmut
            subprocess.run(
                ["mutmut", "run", "--paths-to-mutate", f"{module_name}.py", "--no-progress"],
                cwd=self.temp_dir,
                capture_output=True,
                timeout=120
            )
            
            # Get results
            result = subprocess.run(
                ["mutmut", "results"],
                cwd=self.temp_dir,
                capture_output=True,
                text=True
            )
            
            logs.append(f"Mutation results: {result.stdout[:300]}")
            
            # Parse mutation score
            output = result.stdout
            score = self._parse_mutation_score(output)
            
            return {
                "mutation_score": score,
                "details": output
            }, logs
            
        except subprocess.TimeoutExpired:
            logs.append("Mutation testing timed out")
            return {
                "mutation_score": 0.0,
                "details": "Mutation testing timed out"
            }, logs
        except Exception as e:
            logs.append(f"Mutation testing failed: {str(e)}")
            return {
                "mutation_score": 0.0,
                "details": str(e)
            }, logs
    
    def _parse_mutation_score(self, output: str) -> float:
        """Parse mutation score from mutmut output"""
        try:
            # Look for pattern like "10 killed, 2 survived"
            lines = output.split('\n')
            killed = 0
            total = 0
            
            for line in lines:
                if 'killed' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'killed' in part.lower() and i > 0:
                            try:
                                killed = int(parts[i-1])
                            except:
                                pass
                if 'survived' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'survived' in part.lower() and i > 0:
                            try:
                                survived = int(parts[i-1])
                                total = killed + survived
                            except:
                                pass
            
            if total > 0:
                return killed / total
            
            # Fallback: look for percentage
            for line in lines:
                if '%' in line:
                    parts = line.split()
                    for part in parts:
                        if '%' in part:
                            try:
                                return float(part.strip('%')) / 100
                            except:
                                pass
            
            return 0.5  # Default fallback
            
        except Exception as e:
            print(f"Error parsing mutation score: {e}")
            return 0.5

class LLMRefiner:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url
        self.model = model
    
    def refine_tests(self, original_code: str, pynguin_tests: str, mutation_score: float) -> tuple[str, list]:
        """Use Ollama to refine Pynguin-generated tests"""
        logs = []
        
        prompt = f"""You are an expert Python test engineer. Analyze and improve the following test code.

Original Code:
```python
{original_code}
```

Generated Tests (by Pynguin):
```python
{pynguin_tests}
```

Current Mutation Score: {mutation_score:.2%}

Please improve these tests by:
1. Adding more meaningful assertion messages explaining what is being tested
2. Simplifying redundant test cases while maintaining coverage
3. Improving test function names to be more descriptive (use test_<function>_<scenario> pattern)
4. Adding comprehensive docstrings to explain what each test validates
5. Ensuring assertions are semantically meaningful and test the right behavior
6. Removing any unnecessary or duplicate tests
7. Adding edge case tests for boundary conditions if missing
8. Ensuring proper setup and teardown if needed
9. Using appropriate pytest fixtures if beneficial
10. Adding parametrize decorators for similar test cases

Return ONLY the improved Python test code as valid, executable Python. Do not include markdown formatting, explanations, or comments outside the code."""

        try:
            logs.append(f"Sending request to Ollama at {self.ollama_url}")
            
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "num_predict": 2048,
                    }
                },
                timeout=180
            )
            
            logs.append(f"Ollama response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                refined_code = result.get("response", "")
                
                logs.append(f"Received {len(refined_code)} characters from LLM")
                
                # Clean up the response
                refined_code = self._clean_code_response(refined_code)
                
                # Validate it's valid Python
                try:
                    ast.parse(refined_code)
                    logs.append("LLM generated valid Python code")
                    return refined_code, logs
                except SyntaxError as e:
                    logs.append(f"LLM generated invalid Python: {str(e)}")
                    logs.append("Falling back to original Pynguin tests")
                    return pynguin_tests, logs
            else:
                logs.append(f"Ollama request failed: {response.text}")
                return pynguin_tests, logs
                
        except requests.exceptions.Timeout:
            logs.append("LLM request timed out")
            return pynguin_tests, logs
        except Exception as e:
            logs.append(f"LLM refinement failed: {str(e)}")
            return pynguin_tests, logs
    
    def _clean_code_response(self, code: str) -> str:
        """Remove markdown code blocks and extra text"""
        lines = code.strip().split('\n')
        
        # Remove markdown code fences
        cleaned_lines = []
        in_code_block = False
        
        for line in lines:
            stripped = line.strip()
            
            if stripped.startswith('```python') or stripped.startswith('```'):
                in_code_block = not in_code_block
                continue
            
            if in_code_block or not stripped.startswith('```'):
                cleaned_lines.append(line)
        
        result = '\n'.join(cleaned_lines).strip()
        
        # If we got empty result, return original
        if not result:
            return code
        
        return result

@app.post("/generate-tests", response_model=TestGenerationResponse)
async def generate_tests(request: TestGenerationRequest):
    """
    Main endpoint for test generation pipeline:
    1. Generate tests with Pynguin
    2. Calculate coverage
    3. Run mutation testing
    4. Refine tests with LLM if quality threshold met
    """
    
    all_logs = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Step 1: Generate tests with Pynguin
            all_logs.append("=== Step 1: Pynguin Test Generation ===")
            pynguin_gen = PynguinTestGenerator(temp_dir)
            pynguin_tests, pynguin_logs = pynguin_gen.generate_tests(
                request.code,
                request.module_name,
                request.pynguin_timeout
            )
            all_logs.extend(pynguin_logs)
            
            # Step 2: Calculate coverage
            all_logs.append("\n=== Step 2: Coverage Analysis ===")
            coverage_analyzer = CoverageAnalyzer(temp_dir)
            coverage_score, coverage_logs = coverage_analyzer.calculate_coverage(
                request.module_name,
                pynguin_tests
            )
            all_logs.extend(coverage_logs)
            
            # Step 3: Run mutation testing
            all_logs.append("\n=== Step 3: Mutation Testing ===")
            mutation_tester = MutationTester(temp_dir)
            mutation_results, mutation_logs = mutation_tester.run_mutation_testing(
                request.module_name,
                pynguin_tests
            )
            all_logs.extend(mutation_logs)
            
            mutation_score = mutation_results["mutation_score"]
            
            # Step 4: Refine with LLM if mutation score meets threshold
            refined_tests = pynguin_tests
            if mutation_score >= request.mutation_threshold:
                all_logs.append(f"\n=== Step 4: LLM Refinement (score {mutation_score:.2%} >= {request.mutation_threshold:.2%}) ===")
                llm_refiner = LLMRefiner(request.ollama_url, request.ollama_model)
                refined_tests, llm_logs = llm_refiner.refine_tests(
                    request.code,
                    pynguin_tests,
                    mutation_score
                )
                all_logs.extend(llm_logs)
            else:
                all_logs.append(f"\n=== Step 4: Skipping LLM Refinement (score {mutation_score:.2%} < {request.mutation_threshold:.2%}) ===")
            
            all_logs.append("\n=== Pipeline Complete ===")
            
            return TestGenerationResponse(
                tests=refined_tests,
                mutation_score=mutation_score,
                coverage=coverage_score,
                message=f"Successfully generated tests. Coverage: {coverage_score:.2%}, Mutation Score: {mutation_score:.2%}",
                pynguin_tests=pynguin_tests,
                refined_tests=refined_tests if refined_tests != pynguin_tests else None,
                pipeline_log=all_logs
            )
            
        except Exception as e:
            all_logs.append(f"\n=== ERROR: {str(e)} ===")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": str(e),
                    "logs": all_logs
                }
            )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Pynguin Test Generator",
        "version": "1.0.0"
    }

@app.get("/ollama-status")
async def check_ollama():
    """Check if Ollama is available"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return {
                "status": "connected",
                "models": [m["name"] for m in models]
            }
        return {"status": "error", "message": "Unexpected response"}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    print("Starting Pynguin Test Generator API...")
    print("Backend: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)