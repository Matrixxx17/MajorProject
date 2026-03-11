"""
Ensemble Test Generator

Generates tests using multiple LLM models and intelligently merges results.
This is a KEY DIFFERENTIATOR from Claude/ChatGPT - they can only use one model.
We use multiple models and vote on the best tests.

High cyclomatic complexity through:
- Multi-model orchestration
- Voting and conflict resolution
- Quality-based merging
- Fallback strategies
"""

import subprocess
import time
import asyncio
from typing import Dict, Any, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import ast
import re
from concurrent.futures import ThreadPoolExecutor, as_completed


class ModelType(Enum):
    """Supported LLM models"""
    DEEPSEEK_CODER = "deepseek-coder:1.3b"
    STARCODER = "starcoder"
    CODELLAMA = "codellama:7b"
    LLAMA_CODE = "llama3:code"


@dataclass
class ModelResult:
    """Result from a single model"""
    model: ModelType
    test_code: Optional[str]
    generation_time: float
    success: bool
    error: Optional[str] = None
    quality_score: float = 0.0
    num_tests: int = 0
    has_edge_cases: bool = False


@dataclass
class EnsembleResult:
    """Final ensemble result"""
    final_test_code: str
    models_used: List[ModelType]
    best_model: ModelType
    quality_score: float
    generation_time: float
    voting_details: Dict[str, Any]
    merged_from: List[str] = field(default_factory=list)


class EnsembleTestGenerator:
    """
    Multi-model test generator with intelligent voting and merging.
    This is what makes us BETTER than Claude/ChatGPT!
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._default_config()
        self.timeout_per_model = self.config.get('timeout_per_model', 60)
        self.parallel_execution = self.config.get('parallel_execution', True)
        
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration"""
        return {
            'models': [
                ModelType.DEEPSEEK_CODER,
                ModelType.STARCODER,
                ModelType.CODELLAMA
            ],
            'timeout_per_model': 60,
            'parallel_execution': True,
            'voting_strategy': 'quality_weighted',  # 'majority', 'quality_weighted', 'best_of'
            'merge_strategy': 'complementary',  # 'best_only', 'complementary', 'all'
            'min_quality_threshold': 50.0,
            'weights': {
                ModelType.DEEPSEEK_CODER: 1.0,
                ModelType.STARCODER: 0.9,
                ModelType.CODELLAMA: 0.8
            }
        }
    
    def generate_ensemble_tests(self, code: str, source_file: Optional[str] = None) -> EnsembleResult:
        """
        Generate tests using multiple models and merge results.
        High cyclomatic complexity through multi-path execution and merging logic.
        """
        start_time = time.time()
        models = self.config['models']
        
        print(f"[ENSEMBLE] Generating tests with {len(models)} models...")
        
        # Generate tests from all models
        if self.parallel_execution:
            model_results = self._generate_parallel(code, models)
        else:
            model_results = self._generate_sequential(code, models)
        
        # Filter successful results
        successful_results = [r for r in model_results if r.success and r.test_code]
        
        if not successful_results:
            # All models failed - return error
            elapsed = time.time() - start_time
            return EnsembleResult(
                final_test_code="# All models failed to generate tests\nimport pytest\n\ndef test_placeholder():\n    assert True",
                models_used=[],
                best_model=models[0],
                quality_score=0.0,
                generation_time=elapsed,
                voting_details={'error': 'All models failed'},
                merged_from=[]
            )
        
        # Score each result
        scored_results = self._score_results(successful_results)
        
        # Apply voting strategy
        voting_details = self._apply_voting_strategy(scored_results)
        
        # Merge results based on strategy
        final_code, merged_from = self._merge_results(scored_results, voting_details)
        
        # Determine best model
        best_result = max(scored_results, key=lambda r: r.quality_score)
        
        elapsed = time.time() - start_time
        
        return EnsembleResult(
            final_test_code=final_code,
            models_used=[r.model for r in successful_results],
            best_model=best_result.model,
            quality_score=best_result.quality_score,
            generation_time=elapsed,
            voting_details=voting_details,
            merged_from=merged_from
        )
    
    def _generate_parallel(self, code: str, models: List[ModelType]) -> List[ModelResult]:
        """Generate tests from multiple models in parallel"""
        results = []
        
        with ThreadPoolExecutor(max_workers=len(models)) as executor:
            future_to_model = {
                executor.submit(self._generate_from_model, code, model): model
                for model in models
            }
            
            for future in as_completed(future_to_model):
                model = future_to_model[future]
                try:
                    result = future.result()
                    results.append(result)
                    print(f"[ENSEMBLE] {model.value}: {'✓' if result.success else '✗'}")
                except Exception as e:
                    print(f"[ENSEMBLE] {model.value}: Error - {e}")
                    results.append(ModelResult(
                        model=model,
                        test_code=None,
                        generation_time=0.0,
                        success=False,
                        error=str(e)
                    ))
        
        return results
    
    def _generate_sequential(self, code: str, models: List[ModelType]) -> List[ModelResult]:
        """Generate tests from multiple models sequentially"""
        results = []
        
        for model in models:
            result = self._generate_from_model(code, model)
            results.append(result)
            print(f"[ENSEMBLE] {model.value}: {'✓' if result.success else '✗'}")
        
        return results
    
    def _generate_from_model(self, code: str, model: ModelType) -> ModelResult:
        """Generate tests from a single model"""
        start_time = time.time()
        
        # Determine prompt style based on model
        if "starcoder" in model.value:
            prompt = self._create_starcoder_prompt(code)
        else:
            prompt = self._create_chat_prompt(code, model)
        
        try:
            result = subprocess.run(
                ["ollama", "run", model.value, prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout_per_model,
                encoding='utf-8',
                errors='ignore'
            )
            
            elapsed = time.time() - start_time
            
            if result.returncode != 0:
                return ModelResult(
                    model=model,
                    test_code=None,
                    generation_time=elapsed,
                    success=False,
                    error=f"Exit code {result.returncode}"
                )
            
            # Clean and extract test code
            test_code = self._extract_test_code(result.stdout)
            
            if not test_code:
                return ModelResult(
                    model=model,
                    test_code=None,
                    generation_time=elapsed,
                    success=False,
                    error="No valid test code extracted"
                )
            
            # Quick analysis
            num_tests = test_code.count('def test_')
            has_edge_cases = any(keyword in test_code.lower() 
                               for keyword in ['empty', 'none', 'null', 'invalid', 'edge'])
            
            return ModelResult(
                model=model,
                test_code=test_code,
                generation_time=elapsed,
                success=True,
                num_tests=num_tests,
                has_edge_cases=has_edge_cases
            )
            
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            return ModelResult(
                model=model,
                test_code=None,
                generation_time=elapsed,
                success=False,
                error=f"Timeout after {self.timeout_per_model}s"
            )
        except Exception as e:
            elapsed = time.time() - start_time
            return ModelResult(
                model=model,
                test_code=None,
                generation_time=elapsed,
                success=False,
                error=str(e)
            )
    
    def _create_starcoder_prompt(self, code: str) -> str:
        """Create completion-style prompt for StarCoder"""
        return f"""<filename>test_code.py
# Imports
import pytest
import sys

# Code to test
{code}

# Instructions: Write comprehensive pytest test cases for the above code.
# Include edge cases (empty inputs, None), happy paths, and error handling.
# Begin:
import pytest

def test_"""
    
    def _create_chat_prompt(self, code: str, model: ModelType) -> str:
        """Create chat-style prompt for other models"""
        return f"""You are an expert QA engineer. Generate comprehensive pytest test cases for this code.

Requirements:
1. Cover edge cases: empty inputs, None, boundary values, invalid types
2. Test happy paths with typical inputs
3. Test error handling and exceptions
4. Use clear, descriptive test names
5. Return ONLY valid Python code in a markdown code block

Code to test:
{code}

Generate complete test file:"""
    
    def _extract_test_code(self, output: str) -> Optional[str]:
        """Extract test code from model output"""
        # Remove ANSI codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        output = ansi_escape.sub('', output)
        
        # Try to extract from markdown code blocks
        if "```python" in output:
            parts = output.split("```python")
            if len(parts) > 1:
                code_part = parts[1].split("```")[0].strip()
                if code_part:
                    return code_part
        elif "```" in output:
            parts = output.split("```")
            if len(parts) > 1:
                for i in range(1, len(parts), 2):
                    candidate = parts[i].strip()
                    if candidate and ("import" in candidate or "def test" in candidate.lower()):
                        return candidate
        
        # Find start of code
        match = re.search(r'(import|def test_|from)', output, re.IGNORECASE)
        if match:
            output = output[match.start():].strip()
        
        # Validate it looks like test code
        if "def test_" in output.lower() or "import pytest" in output:
            return output
        
        return None
    
    def _score_results(self, results: List[ModelResult]) -> List[ModelResult]:
        """
        Score each result based on quality metrics.
        High cyclomatic complexity through multi-factor scoring.
        """
        from test_quality_analyzer import analyze_test_quality
        
        for result in results:
            if not result.test_code:
                continue
            
            # Analyze quality
            try:
                quality = analyze_test_quality(result.test_code)
                base_score = quality.overall_score
            except:
                base_score = 50.0  # Default if analysis fails
            
            # Apply model-specific weights
            model_weight = self.config['weights'].get(result.model, 1.0)
            
            # Bonus for edge cases
            edge_case_bonus = 10 if result.has_edge_cases else 0
            
            # Bonus for number of tests
            if result.num_tests >= 5:
                test_count_bonus = 10
            elif result.num_tests >= 3:
                test_count_bonus = 5
            else:
                test_count_bonus = 0
            
            # Penalty for slow generation
            time_penalty = 0
            if result.generation_time > 30:
                time_penalty = 5
            elif result.generation_time > 60:
                time_penalty = 10
            
            # Calculate final score
            final_score = (base_score * model_weight) + edge_case_bonus + test_count_bonus - time_penalty
            result.quality_score = min(100.0, max(0.0, final_score))
        
        return results
    
    def _apply_voting_strategy(self, results: List[ModelResult]) -> Dict[str, Any]:
        """
        Apply voting strategy to select best result(s).
        High cyclomatic complexity through multiple voting strategies.
        """
        strategy = self.config['voting_strategy']
        
        if strategy == 'best_of':
            # Simple: pick the highest quality
            best = max(results, key=lambda r: r.quality_score)
            return {
                'strategy': 'best_of',
                'winner': best.model.value,
                'score': best.quality_score,
                'selected_models': [best.model.value]
            }
        
        elif strategy == 'quality_weighted':
            # Weighted voting based on quality scores
            threshold = self.config['min_quality_threshold']
            qualified = [r for r in results if r.quality_score >= threshold]
            
            if not qualified:
                # Fallback to best available
                best = max(results, key=lambda r: r.quality_score)
                return {
                    'strategy': 'quality_weighted_fallback',
                    'winner': best.model.value,
                    'score': best.quality_score,
                    'selected_models': [best.model.value],
                    'note': 'No models met threshold, using best available'
                }
            
            # Calculate weighted votes
            total_weight = sum(r.quality_score for r in qualified)
            votes = {r.model.value: r.quality_score / total_weight for r in qualified}
            
            # Select top models (those above average weight)
            avg_weight = 1.0 / len(qualified)
            selected = [model for model, weight in votes.items() if weight >= avg_weight]
            
            return {
                'strategy': 'quality_weighted',
                'votes': votes,
                'selected_models': selected,
                'threshold': threshold
            }
        
        elif strategy == 'majority':
            # Majority voting based on test similarity
            # For simplicity, use quality-based selection
            median_score = sorted([r.quality_score for r in results])[len(results) // 2]
            selected = [r.model.value for r in results if r.quality_score >= median_score]
            
            return {
                'strategy': 'majority',
                'median_score': median_score,
                'selected_models': selected
            }
        
        else:
            # Default to best_of
            best = max(results, key=lambda r: r.quality_score)
            return {
                'strategy': 'default',
                'winner': best.model.value,
                'selected_models': [best.model.value]
            }
    
    def _merge_results(self, results: List[ModelResult], 
                      voting_details: Dict[str, Any]) -> Tuple[str, List[str]]:
        """
        Merge test results from multiple models.
        High cyclomatic complexity through different merge strategies.
        """
        merge_strategy = self.config['merge_strategy']
        selected_models = voting_details.get('selected_models', [])
        
        # Filter to selected models
        selected_results = [r for r in results if r.model.value in selected_models]
        
        if not selected_results:
            # Fallback to best
            best = max(results, key=lambda r: r.quality_score)
            return best.test_code, [best.model.value]
        
        if merge_strategy == 'best_only':
            # Just use the best one
            best = max(selected_results, key=lambda r: r.quality_score)
            return best.test_code, [best.model.value]
        
        elif merge_strategy == 'complementary':
            # Merge complementary tests from different models
            return self._merge_complementary(selected_results)
        
        elif merge_strategy == 'all':
            # Combine all tests (may have duplicates)
            return self._merge_all(selected_results)
        
        else:
            # Default to best
            best = max(selected_results, key=lambda r: r.quality_score)
            return best.test_code, [best.model.value]
    
    def _merge_complementary(self, results: List[ModelResult]) -> Tuple[str, List[str]]:
        """
        Merge complementary tests - avoid duplicates, keep unique tests.
        Complex logic for identifying and merging unique tests.
        """
        all_test_functions = []
        test_signatures = set()
        merged_from = []
        
        # Sort by quality (best first)
        sorted_results = sorted(results, key=lambda r: r.quality_score, reverse=True)
        
        for result in sorted_results:
            if not result.test_code:
                continue
            
            try:
                tree = ast.parse(result.test_code)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                        # Create signature from function name and body structure
                        signature = self._create_test_signature(node)
                        
                        # Only add if unique
                        if signature not in test_signatures:
                            test_signatures.add(signature)
                            all_test_functions.append(ast.unparse(node))
                            if result.model.value not in merged_from:
                                merged_from.append(result.model.value)
            except:
                # If parsing fails, skip this result
                continue
        
        if not all_test_functions:
            # Fallback to best result
            best = sorted_results[0]
            return best.test_code, [best.model.value]
        
        # Combine into final test file
        imports = "import pytest\nimport sys\nfrom typing import Any\n\n"
        tests = "\n\n".join(all_test_functions)
        final_code = imports + tests
        
        return final_code, merged_from
    
    def _merge_all(self, results: List[ModelResult]) -> Tuple[str, List[str]]:
        """Merge all tests from all models"""
        all_code = []
        merged_from = []
        
        for result in results:
            if result.test_code:
                all_code.append(f"# Tests from {result.model.value}\n{result.test_code}\n")
                merged_from.append(result.model.value)
        
        return "\n\n".join(all_code), merged_from
    
    def _create_test_signature(self, func_node: ast.FunctionDef) -> str:
        """Create a signature for test function to detect duplicates"""
        # Use function name and number of assertions as signature
        name = func_node.name
        num_assertions = sum(1 for node in ast.walk(func_node) if isinstance(node, ast.Assert))
        
        # Extract key patterns from test name
        name_parts = name.lower().split('_')
        key_parts = [p for p in name_parts if len(p) > 3 and p not in {'test', 'with', 'when', 'then'}]
        
        signature = f"{'-'.join(key_parts)}:{num_assertions}"
        return signature


def generate_ensemble_tests(code: str, config: Optional[Dict[str, Any]] = None) -> EnsembleResult:
    """
    Convenience function to generate tests using ensemble approach.
    
    Args:
        code: Source code to generate tests for
        config: Optional configuration dictionary
        
    Returns:
        EnsembleResult with final merged tests
    """
    generator = EnsembleTestGenerator(config)
    return generator.generate_ensemble_tests(code)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    if len(sys.argv) < 2:
        print("Usage: python ensemble_test_generator.py <python_file>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    code = file_path.read_text(encoding='utf-8')
    
    print(f"\n{'='*60}")
    print("ENSEMBLE TEST GENERATION")
    print(f"{'='*60}")
    print(f"Source: {file_path}\n")
    
    result = generate_ensemble_tests(code)
    
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Models Used: {', '.join([m.value for m in result.models_used])}")
    print(f"Best Model: {result.best_model.value}")
    print(f"Quality Score: {result.quality_score:.1f}/100")
    print(f"Generation Time: {result.generation_time:.2f}s")
    print(f"Merged From: {', '.join(result.merged_from)}")
    print(f"\nVoting Details: {result.voting_details}")
    print(f"\n{'='*60}")
    print("GENERATED TESTS")
    print(f"{'='*60}\n")
    print(result.final_test_code)
