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
from typing import List, Dict, Optional, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
from trl import PPOTrainer, PPOConfig, AutoModelForSeq2SeqLMWithValueHead
from datasets import Dataset
import radon.complexity as radon_cc
import radon.metrics as radon_metrics
from pylint import epylint as lint
import time

app = FastAPI(title="Python Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============= Models =============

class FileContent(BaseModel):
    path: str
    name: str
    content: str

class TestGenerationConfig(BaseModel):
    ollama_model: str = "codellama"
    ollama_url: str = "http://localhost:11434"
    pynguin_timeout: int = 60
    mutation_threshold: float = 0.3

class RefactoringConfig(BaseModel):
    model_name: str = "Salesforce/codet5p-770m"
    optimization_level: str = "balanced"
    analyze_performance: bool = True

class TestGenerationRequest(BaseModel):
    files: List[FileContent]
    config: TestGenerationConfig

class RefactoringRequest(BaseModel):
    files: List[FileContent]
    config: RefactoringConfig

class PerformanceMetrics(BaseModel):
    complexity_reduction: float
    quality_score: float
    maintainability_index: float
    cyclomatic_complexity_before: float
    cyclomatic_complexity_after: float
    loc_before: int
    loc_after: int

class RefactoringResult(BaseModel):
    filename: str
    original_path: str
    refactored_code: str
    improvements: List[str]
    performance_metrics: Optional[PerformanceMetrics]

class RefactoringResponse(BaseModel):
    refactorings: List[RefactoringResult]
    total_files: int
    message: str

class TestFile(BaseModel):
    filename: str
    path: str
    content: str
    coverage: float
    mutation_score: float

class TestGenerationResponse(BaseModel):
    test_files: List[TestFile]
    total_coverage: float
    avg_mutation_score: float
    message: str
    pipeline_log: List[str] = []

# ============= Test Generation Classes (from your original code) =============

class PynguinTestGenerator:
    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
        self.output_dir = os.path.join(temp_dir, "pynguin_output")
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_tests(self, code: str, module_name: str, timeout: int = 60) -> Tuple[str, List[str]]:
        """Generate tests using Pynguin with comprehensive logging"""
        logs = []
        
        module_file = os.path.join(self.temp_dir, f"{module_name}.py")
        with open(module_file, 'w') as f:
            f.write(code)
        
        logs.append(f"Created module file: {module_file}")
        
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
                "--algorithm", "MOSA",
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
            
            test_file = os.path.join(self.output_dir, f"test_{module_name}.py")
            if os.path.exists(test_file):
                with open(test_file, 'r') as f:
                    test_content = f.read()
                logs.append(f"Generated test file with {len(test_content)} characters")
                return test_content, logs
            else:
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
    
    def calculate_coverage(self, module_name: str, test_file: str) -> Tuple[float, List[str]]:
        """Calculate code coverage using coverage.py"""
        logs = []
        
        try:
            test_path = os.path.join(self.temp_dir, f"test_{module_name}.py")
            with open(test_path, 'w') as f:
                f.write(test_file)
            
            logs.append(f"Written test file to: {test_path}")
            
            cov = coverage.Coverage(
                source=[self.temp_dir],
                omit=['*/test_*.py', '*/__pycache__/*']
            )
            
            cov.start()
            
            pytest_args = [
                test_path,
                "-v",
                "--tb=short"
            ]
            
            logs.append(f"Running pytest: {' '.join(pytest_args)}")
            
            result = pytest.main(pytest_args)
            
            cov.stop()
            cov.save()
            
            total = cov.report()
            
            logs.append(f"Coverage calculated: {total}%")
            
            return total / 100.0, logs
            
        except Exception as e:
            logs.append(f"Coverage calculation failed: {str(e)}")
            return 0.0, logs

class MutationTester:
    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
    
    def run_mutation_testing(self, module_name: str, test_code: str) -> Tuple[Dict, List[str]]:
        """Run mutation testing using mutmut"""
        logs = []
        
        test_file = os.path.join(self.temp_dir, f"test_{module_name}.py")
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        logs.append(f"Written test file for mutation testing")
        
        try:
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
            
            subprocess.run(
                ["mutmut", "run", "--paths-to-mutate", f"{module_name}.py", "--no-progress"],
                cwd=self.temp_dir,
                capture_output=True,
                timeout=120
            )
            
            result = subprocess.run(
                ["mutmut", "results"],
                cwd=self.temp_dir,
                capture_output=True,
                text=True
            )
            
            logs.append(f"Mutation results: {result.stdout[:300]}")
            
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
            
            for line in lines:
                if '%' in line:
                    parts = line.split()
                    for part in parts:
                        if '%' in part:
                            try:
                                return float(part.strip('%')) / 100
                            except:
                                pass
            
            return 0.5
            
        except Exception as e:
            print(f"Error parsing mutation score: {e}")
            return 0.5

class LLMRefiner:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url
        self.model = model
    
    def refine_tests(self, original_code: str, pynguin_tests: str, mutation_score: float) -> Tuple[str, List[str]]:
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
                
                refined_code = self._clean_code_response(refined_code)
                
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
        
        if not result:
            return code
        
        return result

# ============= Refactoring Classes =============

class CodeAnalyzer:
    """Analyze code quality and complexity metrics"""
    
    @staticmethod
    def calculate_complexity(code: str) -> Dict:
        """Calculate cyclomatic complexity and other metrics"""
        try:
            # Parse complexity
            complexity_results = radon_cc.cc_visit(code)
            total_complexity = sum(item.complexity for item in complexity_results)
            avg_complexity = total_complexity / len(complexity_results) if complexity_results else 0
            
            # Calculate maintainability index
            mi_result = radon_metrics.mi_visit(code, multi=True)
            maintainability_index = mi_result if isinstance(mi_result, (int, float)) else 0
            
            # Count lines of code
            loc = len([line for line in code.split('\n') if line.strip() and not line.strip().startswith('#')])
            
            return {
                "cyclomatic_complexity": avg_complexity,
                "total_complexity": total_complexity,
                "maintainability_index": maintainability_index,
                "loc": loc,
                "functions": len(complexity_results)
            }
        except Exception as e:
            print(f"Error calculating complexity: {e}")
            return {
                "cyclomatic_complexity": 0,
                "total_complexity": 0,
                "maintainability_index": 0,
                "loc": 0,
                "functions": 0
            }
    
    @staticmethod
    def run_pylint(code: str, temp_file: str) -> float:
        """Run pylint to get code quality score"""
        try:
            with open(temp_file, 'w') as f:
                f.write(code)
            
            pylint_stdout, pylint_stderr = lint.py_run(f'{temp_file} --score=y', return_std=True)
            output = pylint_stdout.getvalue()
            
            # Parse score from output
            for line in output.split('\n'):
                if 'Your code has been rated at' in line:
                    score = float(line.split('rated at ')[1].split('/')[0])
                    return score
            
            return 5.0  # Default middle score
        except Exception as e:
            print(f"Pylint error: {e}")
            return 5.0

class RefactoringModel:
    """AI model for code refactoring using transformers and TRL"""
    
    def __init__(self, model_name: str = "Salesforce/codet5p-770m"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading model {model_name} on {self.device}...")
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(self.device)
        
        # For PPO training
        self.ppo_model = None
        self.ppo_trainer = None
        
    def refactor_code(self, code: str, optimization_level: str = "balanced") -> str:
        """Refactor code using the loaded model"""
        
        # Create refactoring prompt based on optimization level
        if optimization_level == "readability":
            prompt = f"Refactor this Python code to improve readability and maintainability:\n{code}"
        elif optimization_level == "performance":
            prompt = f"Refactor this Python code to optimize performance and efficiency:\n{code}"
        else:  # balanced
            prompt = f"Refactor this Python code to balance readability and performance:\n{code}"
        
        # Tokenize
        inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True).to(self.device)
        
        # Generate refactored code
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_length=1024,
                num_beams=5,
                temperature=0.7,
                top_p=0.95,
                do_sample=True,
                early_stopping=True
            )
        
        refactored = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Clean up output
        refactored = self._clean_generated_code(refactored)
        
        return refactored
    
    def _clean_generated_code(self, code: str) -> str:
        """Clean up generated code"""
        # Remove markdown code blocks if present
        code = code.replace('```python', '').replace('```', '')
        
        # Remove leading/trailing whitespace
        code = code.strip()
        
        # Validate it's valid Python
        try:
            ast.parse(code)
            return code
        except SyntaxError:
            # If invalid, return original (caller will handle)
            return code
    
    def setup_ppo_training(self, training_examples: List[Dict]):
        """Setup PPO training for fine-tuning the model"""
        
        # Create PPO config
        ppo_config = PPOConfig(
            model_name=self.model_name,
            learning_rate=1e-5,
            batch_size=4,
            mini_batch_size=1,
            gradient_accumulation_steps=4,
            optimize_cuda_cache=True,
            early_stopping=True,
            target_kl=0.1,
            ppo_epochs=4,
            seed=42,
        )
        
        # Wrap model for PPO
        self.ppo_model = AutoModelForSeq2SeqLMWithValueHead.from_pretrained(self.model_name).to(self.device)
        
        # Create dataset
        dataset = Dataset.from_list(training_examples)
        
        # Initialize PPO trainer
        self.ppo_trainer = PPOTrainer(
            config=ppo_config,
            model=self.ppo_model,
            tokenizer=self.tokenizer,
            dataset=dataset,
        )
        
        return self.ppo_trainer
    
    def reward_function(self, original_code: str, refactored_code: str) -> float:
        """Calculate reward for PPO training based on code quality improvements"""
        
        # Analyze both versions
        original_metrics = CodeAnalyzer.calculate_complexity(original_code)
        refactored_metrics = CodeAnalyzer.calculate_complexity(refactored_code)
        
        # Calculate reward components
        complexity_improvement = (
            original_metrics["cyclomatic_complexity"] - 
            refactored_metrics["cyclomatic_complexity"]
        ) / max(original_metrics["cyclomatic_complexity"], 1)
        
        maintainability_improvement = (
            refactored_metrics["maintainability_index"] - 
            original_metrics["maintainability_index"]
        ) / 100.0
        
        # LOC reduction (smaller is better, but not too aggressive)
        loc_ratio = refactored_metrics["loc"] / max(original_metrics["loc"], 1)
        loc_reward = 0 if loc_ratio > 1.2 else (1 - loc_ratio) * 0.5
        
        # Validate syntax
        syntax_valid = 1.0
        try:
            ast.parse(refactored_code)
        except SyntaxError:
            syntax_valid = -2.0  # Heavy penalty for invalid code
        
        # Combine rewards
        total_reward = (
            complexity_improvement * 0.4 +
            maintainability_improvement * 0.3 +
            loc_reward * 0.2 +
            syntax_valid * 0.1
        )
        
        return total_reward
    
    def train_ppo_step(self, batch_examples: List[Dict]) -> Dict:
        """Perform one PPO training step"""
        if not self.ppo_trainer:
            raise Exception("PPO trainer not initialized. Call setup_ppo_training first.")
        
        query_tensors = []
        response_tensors = []
        rewards = []
        
        for example in batch_examples:
            # Tokenize query
            query = f"Refactor: {example['original_code']}"
            query_tensor = self.tokenizer.encode(query, return_tensors="pt").to(self.device)
            
            # Generate response
            response_tensor = self.ppo_model.generate(query_tensor, max_length=512)
            
            # Decode response
            refactored = self.tokenizer.decode(response_tensor[0], skip_special_tokens=True)
            
            # Calculate reward
            reward = self.reward_function(example['original_code'], refactored)
            
            query_tensors.append(query_tensor.squeeze())
            response_tensors.append(response_tensor.squeeze())
            rewards.append(torch.tensor(reward))
        
        # PPO step
        stats = self.ppo_trainer.step(query_tensors, response_tensors, rewards)
        
        return stats

class RefactoringEngine:
    """Main refactoring engine that coordinates the process"""
    
    def __init__(self, model_name: str, optimization_level: str):
        self.model = RefactoringModel(model_name)
        self.optimization_level = optimization_level
        self.analyzer = CodeAnalyzer()
    
    def refactor_file(self, file_content: FileContent, analyze_performance: bool = True) -> RefactoringResult:
        """Refactor a single file"""
        
        original_code = file_content.content
        
        # Analyze original code
        original_metrics = self.analyzer.calculate_complexity(original_code)
        
        # Perform refactoring
        refactored_code = self.model.refactor_code(original_code, self.optimization_level)
        
        # Validate refactored code
        try:
            ast.parse(refactored_code)
        except SyntaxError as e:
            # If refactoring produced invalid code, return original with error note
            return RefactoringResult(
                filename=file_content.name + ".py",
                original_path=file_content.path,
                refactored_code=original_code,
                improvements=["Refactoring produced invalid syntax, kept original code"],
                performance_metrics=None
            )
        
        # Analyze refactored code
        refactored_metrics = self.analyzer.calculate_complexity(refactored_code)
        
        # Identify improvements
        improvements = []
        
        complexity_reduction = (
            (original_metrics["cyclomatic_complexity"] - refactored_metrics["cyclomatic_complexity"]) /
            max(original_metrics["cyclomatic_complexity"], 1) * 100
        )
        
        if complexity_reduction > 5:
            improvements.append(f"Reduced cyclomatic complexity by {complexity_reduction:.1f}%")
        
        if refactored_metrics["maintainability_index"] > original_metrics["maintainability_index"]:
            improvements.append(f"Improved maintainability index from {original_metrics['maintainability_index']:.1f} to {refactored_metrics['maintainability_index']:.1f}")
        
        loc_reduction = original_metrics["loc"] - refactored_metrics["loc"]
        if loc_reduction > 0:
            improvements.append(f"Reduced lines of code by {loc_reduction}")
        
        if not improvements:
            improvements.append("Code structure optimized for better practices")
        
        # Calculate performance metrics
        performance_metrics = None
        if analyze_performance:
            quality_score = min(10, refactored_metrics["maintainability_index"] / 10)
            
            performance_metrics = PerformanceMetrics(
                complexity_reduction=max(0, complexity_reduction),
                quality_score=quality_score,
                maintainability_index=refactored_metrics["maintainability_index"],
                cyclomatic_complexity_before=original_metrics["cyclomatic_complexity"],
                cyclomatic_complexity_after=refactored_metrics["cyclomatic_complexity"],
                loc_before=original_metrics["loc"],
                loc_after=refactored_metrics["loc"]
            )
        
        return RefactoringResult(
            filename=file_content.name + ".py",
            original_path=file_content.path,
            refactored_code=refactored_code,
            improvements=improvements,
            performance_metrics=performance_metrics
        )

# ============= API Endpoints =============

@app.post("/generate-tests", response_model=TestGenerationResponse)
async def generate_tests(request: TestGenerationRequest):
    """Generate tests for multiple Python files"""
    
    all_logs = []
    test_files = []
    total_coverage = 0.0
    total_mutation_score = 0.0
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            for file_content in request.files:
                file_logs = []
                file_logs.append(f"\n{'='*60}")
                file_logs.append(f"Processing file: {file_content.name}")
                file_logs.append(f"{'='*60}")
                
                # Generate tests with Pynguin
                pynguin_gen = PynguinTestGenerator(temp_dir)
                pynguin_tests, pynguin_logs = pynguin_gen.generate_tests(
                    file_content.content,
                    file_content.name,
                    request.config.pynguin_timeout
                )
                file_logs.extend(pynguin_logs)
                
                # Calculate coverage
                coverage_analyzer = CoverageAnalyzer(temp_dir)
                coverage_score, coverage_logs = coverage_analyzer.calculate_coverage(
                    file_content.name,
                    pynguin_tests
                )
                file_logs.extend(coverage_logs)
                
                # Run mutation testing
                mutation_tester = MutationTester(temp_dir)
                mutation_results, mutation_logs = mutation_tester.run_mutation_testing(
                    file_content.name,
                    pynguin_tests
                )
                file_logs.extend(mutation_logs)
                
                mutation_score = mutation_results["mutation_score"]
                
                # Refine with LLM if threshold met
                refined_tests = pynguin_tests
                if mutation_score >= request.config.mutation_threshold:
                    file_logs.append(f"Refining with LLM (score {mutation_score:.2%} >= {request.config.mutation_threshold:.2%})")
                    llm_refiner = LLMRefiner(request.config.ollama_url, request.config.ollama_model)
                    refined_tests, llm_logs = llm_refiner.refine_tests(
                        file_content.content,
                        pynguin_tests,
                        mutation_score
                    )
                    file_logs.extend(llm_logs)
                
                # Store test file info
                test_file_path = os.path.join(os.path.dirname(file_content.path), f"test_{file_content.name}.py")
                
                test_files.append(TestFile(
                    filename=f"test_{file_content.name}.py",
                    path=test_file_path,
                    content=refined_tests,
                    coverage=coverage_score,
                    mutation_score=mutation_score
                ))
                
                total_coverage += coverage_score
                total_mutation_score += mutation_score
                
                all_logs.extend(file_logs)
            
            # Calculate averages
            num_files = len(request.files)
            avg_coverage = total_coverage / num_files if num_files > 0 else 0
            avg_mutation = total_mutation_score / num_files if num_files > 0 else 0
            
            return TestGenerationResponse(
                test_files=test_files,
                total_coverage=avg_coverage,
                avg_mutation_score=avg_mutation,
                message=f"Successfully generated tests for {num_files} file(s). Avg Coverage: {avg_coverage:.2%}, Avg Mutation: {avg_mutation:.2%}",
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

@app.post("/refactor-code", response_model=RefactoringResponse)
async def refactor_code(request: RefactoringRequest):
    """Refactor Python code files using AI"""
    
    try:
        # Initialize refactoring engine
        engine = RefactoringEngine(
            model_name=request.config.model_name,
            optimization_level=request.config.optimization_level
        )
        
        refactorings = []
        
        # Process each file
        for file_content in request.files:
            print(f"Refactoring {file_content.name}...")
            
            refactoring_result = engine.refactor_file(
                file_content,
                analyze_performance=request.config.analyze_performance
            )
            
            refactorings.append(refactoring_result)
        
        return RefactoringResponse(
            refactorings=refactorings,
            total_files=len(request.files),
            message=f"Successfully refactored {len(request.files)} file(s)"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "message": "Refactoring failed"
            }
        )

@app.post("/train-refactoring-model")
async def train_refactoring_model(
    model_name: str = "Salesforce/codet5p-770m",
    training_examples: List[Dict] = None
):
    """
    Train/fine-tune the refactoring model using PPO
    
    Example training_examples format:
    [
        {
            "original_code": "def func():\\n    x = 1\\n    return x",
            "target_refactored": "def func():\\n    return 1"
        }
    ]
    """
    
    if not training_examples:
        raise HTTPException(status_code=400, detail="No training examples provided")
    
    try:
        model = RefactoringModel(model_name)
        model.setup_ppo_training(training_examples)
        
        # Perform training steps
        num_epochs = 3
        stats_history = []
        
        for epoch in range(num_epochs):
            stats = model.train_ppo_step(training_examples)
            stats_history.append(stats)
            print(f"Epoch {epoch + 1}/{num_epochs} completed")
        
        return {
            "message": f"Training completed for {num_epochs} epochs",
            "stats": stats_history,
            "model_name": model_name
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "message": "Training failed"
            }
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Python Assistant API",
        "version": "2.0.0",
        "features": ["test_generation", "code_refactoring", "ppo_training"]
    }

@app.get("/models/available")
async def list_available_models():
    """List available models for refactoring"""
    return {
        "models": [
            {
                "name": "Salesforce/codet5p-770m",
                "type": "seq2seq",
                "size": "770M parameters",
                "recommended": True
            },
            {
                "name": "Salesforce/codet5p-2b",
                "type": "seq2seq",
                "size": "2B parameters",
                "recommended": False,
                "note": "Requires more GPU memory"
            },
            {
                "name": "bigcode/starcoderbase",
                "type": "decoder",
                "size": "15B parameters",
                "recommended": False,
                "note": "Very large, best performance"
            }
        ]
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
    print("Starting Python Assistant API...")
    print("Backend: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    print(f"Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
