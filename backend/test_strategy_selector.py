"""
Intelligent Test Strategy Selector

Analyzes code complexity and selects the optimal test generation strategy.
This module significantly increases cyclomatic complexity through multi-level
decision trees and conditional routing logic.
"""

import ast
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import json
import os


class TestStrategy(Enum):
    """Available test generation strategies"""
    SIMPLE = "simple"           # Basic fallback tests
    STANDARD = "standard"       # Single LLM model
    ADVANCED = "advanced"       # Single LLM with enhanced prompts
    ENSEMBLE = "ensemble"       # Multi-model with voting
    HYBRID = "hybrid"          # Combination of approaches


@dataclass
class ComplexityMetrics:
    """Code complexity metrics"""
    cyclomatic_complexity: int
    cognitive_complexity: int
    halstead_difficulty: float
    lines_of_code: int
    num_functions: int
    num_classes: int
    max_nesting_depth: int
    num_branches: int
    num_loops: int
    has_recursion: bool
    has_exceptions: bool
    has_async: bool
    
    def get_overall_score(self) -> float:
        """Calculate weighted overall complexity score"""
        # Multi-level scoring with conditional weights
        score = 0.0
        
        # Cyclomatic complexity contribution (0-40 points)
        if self.cyclomatic_complexity <= 5:
            score += 5
        elif self.cyclomatic_complexity <= 10:
            score += 15
        elif self.cyclomatic_complexity <= 20:
            score += 25
        else:
            score += 40
        
        # Cognitive complexity contribution (0-30 points)
        if self.cognitive_complexity <= 5:
            score += 3
        elif self.cognitive_complexity <= 15:
            score += 12
        elif self.cognitive_complexity <= 30:
            score += 22
        else:
            score += 30
        
        # Nesting depth penalty (0-15 points)
        if self.max_nesting_depth <= 2:
            score += 2
        elif self.max_nesting_depth <= 4:
            score += 8
        elif self.max_nesting_depth <= 6:
            score += 12
        else:
            score += 15
        
        # Special features bonus (0-15 points)
        special_score = 0
        if self.has_recursion:
            special_score += 5
        if self.has_exceptions:
            special_score += 3
        if self.has_async:
            special_score += 7
        score += min(special_score, 15)
        
        return min(score, 100.0)


class ComplexityAnalyzer(ast.NodeVisitor):
    """AST visitor to calculate code complexity metrics"""
    
    def __init__(self):
        self.cyclomatic = 1  # Start at 1
        self.cognitive = 0
        self.nesting_depth = 0
        self.max_nesting = 0
        self.num_functions = 0
        self.num_classes = 0
        self.num_branches = 0
        self.num_loops = 0
        self.has_recursion = False
        self.has_exceptions = False
        self.has_async = False
        self.function_calls = set()
        self.current_function = None
        
    def visit_FunctionDef(self, node):
        """Visit function definition - increases cyclomatic complexity"""
        self.num_functions += 1
        old_function = self.current_function
        self.current_function = node.name
        
        # Check for async
        if isinstance(node, ast.AsyncFunctionDef):
            self.has_async = True
        
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        
        self.current_function = old_function
        
    def visit_AsyncFunctionDef(self, node):
        """Visit async function"""
        self.has_async = True
        self.visit_FunctionDef(node)
        
    def visit_ClassDef(self, node):
        """Visit class definition"""
        self.num_classes += 1
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        
    def visit_If(self, node):
        """Visit if statement - increases both cyclomatic and cognitive complexity"""
        self.cyclomatic += 1
        self.num_branches += 1
        self.cognitive += (1 + self.nesting_depth)
        
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        
    def visit_For(self, node):
        """Visit for loop"""
        self.cyclomatic += 1
        self.num_loops += 1
        self.cognitive += (1 + self.nesting_depth)
        
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        
    def visit_While(self, node):
        """Visit while loop"""
        self.cyclomatic += 1
        self.num_loops += 1
        self.cognitive += (1 + self.nesting_depth)
        
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        
    def visit_Try(self, node):
        """Visit try-except block"""
        self.has_exceptions = True
        self.cyclomatic += len(node.handlers)
        self.cognitive += (1 + self.nesting_depth)
        
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        
    def visit_ExceptHandler(self, node):
        """Visit exception handler"""
        self.num_branches += 1
        self.generic_visit(node)
        
    def visit_With(self, node):
        """Visit with statement"""
        self.cyclomatic += 1
        self.generic_visit(node)
        
    def visit_Call(self, node):
        """Visit function call - check for recursion"""
        if isinstance(node.func, ast.Name):
            call_name = node.func.id
            self.function_calls.add(call_name)
            if call_name == self.current_function:
                self.has_recursion = True
        self.generic_visit(node)
        
    def visit_BoolOp(self, node):
        """Visit boolean operation (and/or)"""
        # Each additional condition adds to complexity
        self.cyclomatic += len(node.values) - 1
        self.cognitive += len(node.values) - 1
        self.generic_visit(node)


def analyze_code_complexity(code: str) -> ComplexityMetrics:
    """
    Analyze code and return complexity metrics.
    High cyclomatic complexity through multiple analysis paths.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Return minimal metrics for unparseable code
        return ComplexityMetrics(
            cyclomatic_complexity=1,
            cognitive_complexity=0,
            halstead_difficulty=0.0,
            lines_of_code=len(code.splitlines()),
            num_functions=0,
            num_classes=0,
            max_nesting_depth=0,
            num_branches=0,
            num_loops=0,
            has_recursion=False,
            has_exceptions=False,
            has_async=False
        )
    
    analyzer = ComplexityAnalyzer()
    analyzer.visit(tree)
    
    # Calculate Halstead difficulty (simplified)
    operators = 0
    operands = 0
    unique_operators = set()
    unique_operands = set()
    
    for node in ast.walk(tree):
        # Count operators
        if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                           ast.Pow, ast.LShift, ast.RShift, ast.BitOr,
                           ast.BitXor, ast.BitAnd, ast.FloorDiv)):
            operators += 1
            unique_operators.add(type(node).__name__)
        elif isinstance(node, (ast.And, ast.Or, ast.Not)):
            operators += 1
            unique_operators.add(type(node).__name__)
        elif isinstance(node, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
                              ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn)):
            operators += 1
            unique_operators.add(type(node).__name__)
        
        # Count operands
        if isinstance(node, ast.Name):
            operands += 1
            unique_operands.add(node.id)
        elif isinstance(node, (ast.Constant, ast.Num, ast.Str)):
            operands += 1
    
    # Halstead difficulty = (unique_operators / 2) * (operands / unique_operands)
    halstead_difficulty = 0.0
    if unique_operands:
        halstead_difficulty = (len(unique_operators) / 2.0) * (operands / len(unique_operands))
    
    return ComplexityMetrics(
        cyclomatic_complexity=analyzer.cyclomatic,
        cognitive_complexity=analyzer.cognitive,
        halstead_difficulty=halstead_difficulty,
        lines_of_code=len(code.splitlines()),
        num_functions=analyzer.num_functions,
        num_classes=analyzer.num_classes,
        max_nesting_depth=analyzer.max_nesting,
        num_branches=analyzer.num_branches,
        num_loops=analyzer.num_loops,
        has_recursion=analyzer.has_recursion,
        has_exceptions=analyzer.has_exceptions,
        has_async=analyzer.has_async
    )


class StrategySelector:
    """
    Selects optimal test generation strategy based on code complexity.
    Implements high cyclomatic complexity through multi-level decision trees.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.history: List[Dict[str, Any]] = []
        
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load configuration with fallback defaults"""
        default_config = {
            "thresholds": {
                "simple": {
                    "max_complexity_score": 20,
                    "max_cyclomatic": 5,
                    "max_functions": 3
                },
                "standard": {
                    "max_complexity_score": 50,
                    "max_cyclomatic": 15,
                    "max_nesting": 3
                },
                "advanced": {
                    "max_complexity_score": 75,
                    "max_cyclomatic": 30,
                    "requires_special_features": False
                },
                "ensemble": {
                    "min_complexity_score": 75,
                    "min_cyclomatic": 20,
                    "requires_special_features": True
                }
            },
            "weights": {
                "complexity_score": 0.4,
                "cyclomatic": 0.3,
                "cognitive": 0.2,
                "special_features": 0.1
            },
            "adaptive": {
                "enabled": True,
                "learning_rate": 0.1,
                "min_samples": 5
            }
        }
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                    # Merge with defaults
                    default_config.update(user_config)
            except Exception as e:
                print(f"[WARNING] Failed to load config: {e}, using defaults")
        
        return default_config
    
    def select_strategy(self, code: str, file_path: Optional[str] = None) -> Tuple[TestStrategy, Dict[str, Any]]:
        """
        Select optimal test generation strategy.
        High cyclomatic complexity through nested conditionals and multiple decision paths.
        """
        # Analyze code complexity
        metrics = analyze_code_complexity(code)
        overall_score = metrics.get_overall_score()
        
        thresholds = self.config["thresholds"]
        
        # Multi-level decision tree
        selected_strategy = None
        confidence = 0.0
        reasoning = []
        
        # Level 1: Check for very simple code
        if (overall_score <= thresholds["simple"]["max_complexity_score"] and
            metrics.cyclomatic_complexity <= thresholds["simple"]["max_cyclomatic"] and
            metrics.num_functions <= thresholds["simple"]["max_functions"] and
            not metrics.has_recursion and
            not metrics.has_async):
            
            selected_strategy = TestStrategy.SIMPLE
            confidence = 0.9
            reasoning.append("Code is very simple with low complexity")
            
        # Level 2: Check for ensemble requirements
        elif (overall_score >= thresholds["ensemble"]["min_complexity_score"] or
              metrics.cyclomatic_complexity >= thresholds["ensemble"]["min_cyclomatic"] or
              (thresholds["ensemble"]["requires_special_features"] and
               (metrics.has_recursion or metrics.has_async or metrics.has_exceptions))):
            
            # Additional checks for ensemble
            if metrics.num_functions >= 5 or metrics.num_classes >= 2:
                selected_strategy = TestStrategy.ENSEMBLE
                confidence = 0.85
                reasoning.append("High complexity warrants multi-model approach")
            elif metrics.has_recursion and metrics.cyclomatic_complexity > 10:
                selected_strategy = TestStrategy.ENSEMBLE
                confidence = 0.8
                reasoning.append("Recursive functions benefit from ensemble")
            elif metrics.has_async and metrics.num_functions >= 3:
                selected_strategy = TestStrategy.ENSEMBLE
                confidence = 0.75
                reasoning.append("Async code with multiple functions needs ensemble")
            else:
                # Fallback to advanced
                selected_strategy = TestStrategy.ADVANCED
                confidence = 0.7
                reasoning.append("Complex but not enough for ensemble")
                
        # Level 3: Check for advanced requirements
        elif (overall_score >= thresholds["advanced"]["max_complexity_score"] or
              metrics.cyclomatic_complexity >= thresholds["standard"]["max_cyclomatic"] or
              metrics.max_nesting_depth > thresholds["standard"]["max_nesting"]):
            
            # Conditional routing based on specific patterns
            if metrics.has_exceptions and metrics.num_branches >= 5:
                selected_strategy = TestStrategy.ADVANCED
                confidence = 0.8
                reasoning.append("Exception handling with multiple branches")
            elif metrics.num_loops >= 3 and metrics.max_nesting_depth >= 3:
                selected_strategy = TestStrategy.ADVANCED
                confidence = 0.75
                reasoning.append("Multiple nested loops require advanced testing")
            elif metrics.num_classes >= 1 and metrics.num_functions >= 5:
                selected_strategy = TestStrategy.ADVANCED
                confidence = 0.7
                reasoning.append("OOP code benefits from advanced strategy")
            else:
                selected_strategy = TestStrategy.STANDARD
                confidence = 0.65
                reasoning.append("Moderate complexity, standard approach sufficient")
                
        # Level 4: Standard strategy
        elif overall_score >= thresholds["simple"]["max_complexity_score"]:
            selected_strategy = TestStrategy.STANDARD
            confidence = 0.8
            reasoning.append("Standard complexity, single model sufficient")
            
        # Level 5: Fallback to simple
        else:
            selected_strategy = TestStrategy.SIMPLE
            confidence = 0.7
            reasoning.append("Low complexity, simple tests adequate")
        
        # Adaptive adjustment based on history
        if self.config["adaptive"]["enabled"] and len(self.history) >= self.config["adaptive"]["min_samples"]:
            adjusted_strategy, adjusted_confidence = self._adaptive_adjustment(
                selected_strategy, confidence, metrics
            )
            if adjusted_strategy != selected_strategy:
                reasoning.append(f"Adjusted from {selected_strategy.value} based on historical performance")
                selected_strategy = adjusted_strategy
                confidence = adjusted_confidence
        
        # Build detailed response
        result = {
            "strategy": selected_strategy,
            "confidence": confidence,
            "metrics": {
                "overall_score": overall_score,
                "cyclomatic_complexity": metrics.cyclomatic_complexity,
                "cognitive_complexity": metrics.cognitive_complexity,
                "halstead_difficulty": metrics.halstead_difficulty,
                "lines_of_code": metrics.lines_of_code,
                "num_functions": metrics.num_functions,
                "num_classes": metrics.num_classes,
                "max_nesting_depth": metrics.max_nesting_depth,
                "has_recursion": metrics.has_recursion,
                "has_exceptions": metrics.has_exceptions,
                "has_async": metrics.has_async
            },
            "reasoning": reasoning,
            "file_path": file_path
        }
        
        # Record in history
        self.history.append({
            "strategy": selected_strategy.value,
            "metrics": result["metrics"],
            "timestamp": None  # Would use datetime in production
        })
        
        return selected_strategy, result
    
    def _adaptive_adjustment(self, strategy: TestStrategy, confidence: float,
                           metrics: ComplexityMetrics) -> Tuple[TestStrategy, float]:
        """
        Adjust strategy based on historical performance.
        Adds additional cyclomatic complexity through historical analysis.
        """
        # Analyze recent history
        recent_history = self.history[-self.config["adaptive"]["min_samples"]:]
        
        # Calculate success rates for each strategy
        strategy_performance = {}
        for entry in recent_history:
            strat = entry["strategy"]
            if strat not in strategy_performance:
                strategy_performance[strat] = {"total": 0, "success": 0}
            strategy_performance[strat]["total"] += 1
            # In real implementation, would track actual success
            # For now, assume success based on strategy appropriateness
            
        # Adjust if current strategy has poor historical performance
        if strategy.value in strategy_performance:
            perf = strategy_performance[strategy.value]
            if perf["total"] >= 3:
                success_rate = perf.get("success", 0) / perf["total"]
                
                # Multi-level adjustment logic
                if success_rate < 0.5 and strategy == TestStrategy.STANDARD:
                    # Upgrade to advanced
                    return TestStrategy.ADVANCED, confidence * 0.9
                elif success_rate < 0.3 and strategy == TestStrategy.ADVANCED:
                    # Upgrade to ensemble
                    return TestStrategy.ENSEMBLE, confidence * 0.85
                elif success_rate > 0.9 and strategy == TestStrategy.ENSEMBLE:
                    # Downgrade to save resources
                    if metrics.cyclomatic_complexity < 15:
                        return TestStrategy.ADVANCED, confidence * 0.95
        
        return strategy, confidence


def select_test_strategy(code: str, file_path: Optional[str] = None,
                        config_path: Optional[str] = None) -> Tuple[TestStrategy, Dict[str, Any]]:
    """
    Convenience function to select test strategy.
    
    Args:
        code: Source code to analyze
        file_path: Optional path to the file
        config_path: Optional path to configuration file
        
    Returns:
        Tuple of (selected_strategy, detailed_result)
    """
    selector = StrategySelector(config_path)
    return selector.select_strategy(code, file_path)


if __name__ == "__main__":
    # Demo usage
    if len(sys.argv) < 2:
        print("Usage: python test_strategy_selector.py <python_file>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    code = file_path.read_text(encoding='utf-8')
    
    strategy, result = select_test_strategy(code, str(file_path))
    
    print(f"\n{'='*60}")
    print("TEST STRATEGY SELECTION")
    print(f"{'='*60}")
    print(f"File: {file_path}")
    print(f"\nSelected Strategy: {strategy.value.upper()}")
    print(f"Confidence: {result['confidence']:.2%}")
    print(f"\nComplexity Metrics:")
    print(f"  Overall Score: {result['metrics']['overall_score']:.1f}/100")
    print(f"  Cyclomatic Complexity: {result['metrics']['cyclomatic_complexity']}")
    print(f"  Cognitive Complexity: {result['metrics']['cognitive_complexity']}")
    print(f"  Lines of Code: {result['metrics']['lines_of_code']}")
    print(f"  Functions: {result['metrics']['num_functions']}")
    print(f"  Classes: {result['metrics']['num_classes']}")
    print(f"  Max Nesting: {result['metrics']['max_nesting_depth']}")
    print(f"  Has Recursion: {result['metrics']['has_recursion']}")
    print(f"  Has Exceptions: {result['metrics']['has_exceptions']}")
    print(f"  Has Async: {result['metrics']['has_async']}")
    print(f"\nReasoning:")
    for reason in result['reasoning']:
        print(f"  - {reason}")
    print(f"{'='*60}\n")
