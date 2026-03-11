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
import re
from typing import Dict, Any, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

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
CONFIG_FILE    = os.path.join(BASE_DIR, "test_config.json")

for d in (UPLOAD_FOLDER, EXTRACT_FOLDER, TESTS_FOLDER):
    os.makedirs(d, exist_ok=True)

# ── In-memory job store ────────────────────────────────────────────────────────
jobs: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> Dict[str, Any]:
    """Load configuration from file or use defaults"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "default_strategy": "auto",
        "enable_quality_analysis": True,
        "enable_ensemble": False,
        "quality_threshold": 70.0,
        "max_concurrency": 3,
    }

config = load_config()


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
# Test Strategy Selector (inlined from test_strategy_selector.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategy(Enum):
    """Available test generation strategies"""
    SIMPLE   = "simple"
    STANDARD = "standard"
    ADVANCED = "advanced"
    ENSEMBLE = "ensemble"
    HYBRID   = "hybrid"


@dataclass
class ComplexityMetrics:
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
        score = 0.0
        if self.cyclomatic_complexity <= 5:
            score += 5
        elif self.cyclomatic_complexity <= 10:
            score += 15
        elif self.cyclomatic_complexity <= 20:
            score += 25
        else:
            score += 40

        if self.cognitive_complexity <= 5:
            score += 3
        elif self.cognitive_complexity <= 15:
            score += 12
        elif self.cognitive_complexity <= 30:
            score += 22
        else:
            score += 30

        if self.max_nesting_depth <= 2:
            score += 2
        elif self.max_nesting_depth <= 4:
            score += 8
        elif self.max_nesting_depth <= 6:
            score += 12
        else:
            score += 15

        special_score = 0
        if self.has_recursion:
            special_score += 5
        if self.has_exceptions:
            special_score += 3
        if self.has_async:
            special_score += 7
        score += min(special_score, 15)

        return min(score, 100.0)


class _ComplexityAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.cyclomatic = 1
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
        self.function_calls: Set[str] = set()
        self.current_function: Optional[str] = None

    def visit_FunctionDef(self, node):
        self.num_functions += 1
        old_function = self.current_function
        self.current_function = node.name
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1
        self.current_function = old_function

    def visit_AsyncFunctionDef(self, node):
        self.has_async = True
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        self.num_classes += 1
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1

    def visit_If(self, node):
        self.cyclomatic += 1
        self.num_branches += 1
        self.cognitive += (1 + self.nesting_depth)
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1

    def visit_For(self, node):
        self.cyclomatic += 1
        self.num_loops += 1
        self.cognitive += (1 + self.nesting_depth)
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1

    def visit_While(self, node):
        self.cyclomatic += 1
        self.num_loops += 1
        self.cognitive += (1 + self.nesting_depth)
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1

    def visit_Try(self, node):
        self.has_exceptions = True
        self.cyclomatic += len(node.handlers)
        self.cognitive += (1 + self.nesting_depth)
        self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node)
        self.nesting_depth -= 1

    def visit_ExceptHandler(self, node):
        self.num_branches += 1
        self.generic_visit(node)

    def visit_With(self, node):
        self.cyclomatic += 1
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            call_name = node.func.id
            self.function_calls.add(call_name)
            if call_name == self.current_function:
                self.has_recursion = True
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.cyclomatic += len(node.values) - 1
        self.cognitive += len(node.values) - 1
        self.generic_visit(node)


def _analyze_code_complexity(code: str) -> ComplexityMetrics:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ComplexityMetrics(
            cyclomatic_complexity=1, cognitive_complexity=0, halstead_difficulty=0.0,
            lines_of_code=len(code.splitlines()), num_functions=0, num_classes=0,
            max_nesting_depth=0, num_branches=0, num_loops=0,
            has_recursion=False, has_exceptions=False, has_async=False,
        )

    analyzer = _ComplexityAnalyzer()
    analyzer.visit(tree)

    operators, operands = 0, 0
    unique_operators: Set[str] = set()
    unique_operands: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                              ast.Pow, ast.LShift, ast.RShift, ast.BitOr,
                              ast.BitXor, ast.BitAnd, ast.FloorDiv,
                              ast.And, ast.Or, ast.Not,
                              ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
                              ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn)):
            operators += 1
            unique_operators.add(type(node).__name__)
        if isinstance(node, ast.Name):
            operands += 1
            unique_operands.add(node.id)
        elif isinstance(node, (ast.Constant,)):
            operands += 1

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
        has_async=analyzer.has_async,
    )


def select_test_strategy(code: str, file_path: Optional[str] = None) -> Tuple[TestStrategy, Dict[str, Any]]:
    """Select optimal test generation strategy based on code complexity."""
    metrics = _analyze_code_complexity(code)
    overall_score = metrics.get_overall_score()

    thresholds = {
        "simple":   {"max_complexity_score": 20, "max_cyclomatic": 5,  "max_functions": 3},
        "standard": {"max_complexity_score": 50, "max_cyclomatic": 15, "max_nesting": 3},
        "advanced": {"max_complexity_score": 75, "max_cyclomatic": 30},
        "ensemble": {"min_complexity_score": 75, "min_cyclomatic": 20},
    }

    selected_strategy = None
    confidence = 0.0
    reasoning = []

    if (overall_score <= thresholds["simple"]["max_complexity_score"] and
            metrics.cyclomatic_complexity <= thresholds["simple"]["max_cyclomatic"] and
            metrics.num_functions <= thresholds["simple"]["max_functions"] and
            not metrics.has_recursion and not metrics.has_async):
        selected_strategy = TestStrategy.SIMPLE
        confidence = 0.9
        reasoning.append("Code is very simple with low complexity")

    elif (overall_score >= thresholds["ensemble"]["min_complexity_score"] or
          metrics.cyclomatic_complexity >= thresholds["ensemble"]["min_cyclomatic"] or
          metrics.has_recursion or metrics.has_async or metrics.has_exceptions):
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
            selected_strategy = TestStrategy.ADVANCED
            confidence = 0.7
            reasoning.append("Complex but not enough for ensemble")

    elif (overall_score >= thresholds["advanced"]["max_complexity_score"] or
          metrics.cyclomatic_complexity >= thresholds["standard"]["max_cyclomatic"] or
          metrics.max_nesting_depth > thresholds["standard"]["max_nesting"]):
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

    elif overall_score >= thresholds["simple"]["max_complexity_score"]:
        selected_strategy = TestStrategy.STANDARD
        confidence = 0.8
        reasoning.append("Standard complexity, single model sufficient")

    else:
        selected_strategy = TestStrategy.SIMPLE
        confidence = 0.7
        reasoning.append("Low complexity, simple tests adequate")

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
            "has_async": metrics.has_async,
        },
        "reasoning": reasoning,
        "file_path": file_path,
    }
    return selected_strategy, result


# ══════════════════════════════════════════════════════════════════════════════
# Test Quality Analyzer (inlined from test_quality_analyzer.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestSmell(Enum):
    MAGIC_NUMBER        = "magic_number"
    UNCLEAR_ASSERTION   = "unclear_assertion"
    NO_ASSERTION        = "no_assertion"
    TOO_MANY_ASSERTIONS = "too_many_assertions"
    DUPLICATE_TEST      = "duplicate_test"
    EMPTY_TEST          = "empty_test"
    SLEEPY_TEST         = "sleepy_test"
    CONDITIONAL_LOGIC   = "conditional_logic"
    HARDCODED_PATH      = "hardcoded_path"
    MISSING_DOCSTRING   = "missing_docstring"
    POOR_NAMING         = "poor_naming"
    EXCEPTION_SWALLOWING = "exception_swallowing"
    RESOURCE_LEAK       = "resource_leak"
    GLOBAL_STATE        = "global_state"
    MYSTERY_GUEST       = "mystery_guest"


@dataclass
class TestSmellInstance:
    smell_type: TestSmell
    line_number: int
    severity: str
    message: str
    suggestion: str


@dataclass
class QualityScore:
    overall_score: float
    assertion_quality: float
    edge_case_coverage: float
    naming_quality: float
    documentation_quality: float
    maintainability: float
    smells_detected: List[TestSmellInstance] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)


class _TestQualityAnalyzer(ast.NodeVisitor):
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.test_functions: List[ast.FunctionDef] = []
        self.assertions: List[Tuple[int, str]] = []
        self.imports: Set[str] = set()
        self.smells: List[TestSmellInstance] = []
        self.has_fixtures = False
        self.has_parametrize = False
        self.has_mocks = False
        self.current_function = None

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.add(node.module)
            if node.module == "pytest":
                for alias in node.names:
                    if alias.name == "fixture":
                        self.has_fixtures = True
                    elif alias.name == "mark":
                        self.has_parametrize = True
            if "mock" in node.module.lower():
                self.has_mocks = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            self.test_functions.append(node)
            self.current_function = node
            if not ast.get_docstring(node):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.MISSING_DOCSTRING, line_number=node.lineno,
                    severity="low", message=f"Test function '{node.name}' lacks docstring",
                    suggestion="Add docstring explaining what is being tested",
                ))
            if not self._is_good_test_name(node.name):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.POOR_NAMING, line_number=node.lineno,
                    severity="medium", message=f"Test name '{node.name}' is not descriptive",
                    suggestion="Use pattern: test_<method>_<scenario>_<expected_result>",
                ))
            self._analyze_test_body(node)
            self.current_function = None
        self.generic_visit(node)

    def _is_good_test_name(self, name: str) -> bool:
        if len(name) < 10:
            return False
        parts = name.split("_")
        if len(parts) < 3:
            return False
        generic_words = {"test", "a", "b", "c", "temp", "foo", "bar"}
        return len([p for p in parts if p not in generic_words]) >= 2

    def _analyze_test_body(self, node: ast.FunctionDef):
        assertion_count = 0
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assert):
                assertion_count += 1
                self.assertions.append((stmt.lineno, ast.unparse(stmt.test)))
                if self._is_unclear_assertion(stmt):
                    self.smells.append(TestSmellInstance(
                        smell_type=TestSmell.UNCLEAR_ASSERTION,
                        line_number=stmt.lineno, severity="medium",
                        message="Assertion lacks clear comparison",
                        suggestion="Use explicit comparisons: assert x == expected",
                    ))
            if isinstance(stmt, ast.Call):
                if isinstance(stmt.func, ast.Attribute) and stmt.func.attr in ("sleep", "wait"):
                    self.smells.append(TestSmellInstance(
                        smell_type=TestSmell.SLEEPY_TEST,
                        line_number=getattr(stmt, "lineno", 0), severity="high",
                        message="Test uses sleep/wait - makes tests slow",
                        suggestion="Use mocks or event-driven waiting instead",
                    ))
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.CONDITIONAL_LOGIC,
                    line_number=getattr(stmt, "lineno", node.lineno), severity="high",
                    message="Test contains conditional logic",
                    suggestion="Split into separate tests or use parametrize",
                ))
            if isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    if not handler.type or (
                        isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
                    ):
                        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                            self.smells.append(TestSmellInstance(
                                smell_type=TestSmell.EXCEPTION_SWALLOWING,
                                line_number=getattr(stmt, "lineno", node.lineno), severity="high",
                                message="Test swallows exceptions silently",
                                suggestion="Use pytest.raises() for expected exceptions",
                            ))
            if isinstance(stmt, ast.Constant) and isinstance(stmt.value, (int, float)) \
                    and stmt.value not in (0, 1, -1, 2):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.MAGIC_NUMBER,
                    line_number=getattr(stmt, "lineno", node.lineno), severity="low",
                    message=f"Magic number {stmt.value} used",
                    suggestion="Extract to named constant for clarity",
                ))

        if assertion_count == 0:
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.NO_ASSERTION, line_number=node.lineno, severity="high",
                message=f"Test '{node.name}' has no assertions",
                suggestion="Add assertions to verify expected behavior",
            ))
        elif assertion_count > 5:
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.TOO_MANY_ASSERTIONS, line_number=node.lineno, severity="medium",
                message=f"Test '{node.name}' has {assertion_count} assertions",
                suggestion="Consider splitting into multiple focused tests",
            ))
        if len(node.body) <= 1 and (not node.body or isinstance(node.body[0], ast.Pass)):
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.EMPTY_TEST, line_number=node.lineno, severity="high",
                message=f"Test '{node.name}' is empty",
                suggestion="Implement test logic or remove placeholder",
            ))

    def _is_unclear_assertion(self, assert_node: ast.Assert) -> bool:
        test_expr = assert_node.test
        if isinstance(test_expr, ast.Compare):
            return False
        if isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not):
            return False
        if isinstance(test_expr, ast.Call) and isinstance(test_expr.func, ast.Name):
            if any(test_expr.func.id.startswith(p) for p in ["is_", "has_", "can_", "should_"]):
                return False
        return True


def analyze_test_quality(test_code: str, source_code: Optional[str] = None) -> QualityScore:
    """Analyze test code quality and return detailed score."""
    try:
        tree = ast.parse(test_code)
    except SyntaxError as e:
        return QualityScore(
            overall_score=0.0, assertion_quality=0.0, edge_case_coverage=0.0,
            naming_quality=0.0, documentation_quality=0.0, maintainability=0.0,
            smells_detected=[TestSmellInstance(
                smell_type=TestSmell.EMPTY_TEST, line_number=0, severity="high",
                message=f"Syntax error: {e}", suggestion="Fix syntax errors",
            )],
            improvements=["Fix syntax errors"],
        )

    analyzer = _TestQualityAnalyzer(test_code)
    analyzer.visit(tree)

    def _assertion_score() -> float:
        if not analyzer.test_functions:
            return 0.0
        score = 100.0
        no_assert = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.NO_ASSERTION)
        score -= (no_assert / len(analyzer.test_functions)) * 40
        unclear = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.UNCLEAR_ASSERTION)
        score -= (unclear / max(len(analyzer.assertions), 1)) * 30
        avg = len(analyzer.assertions) / len(analyzer.test_functions)
        if 1 <= avg <= 3:
            score += 10
        elif avg > 5:
            score -= 10
        return max(0, min(100, score))

    def _edge_case_score() -> float:
        score = 50.0
        keywords = ["empty", "none", "null", "zero", "negative", "boundary",
                    "max", "min", "invalid", "error", "exception", "edge"]
        ec_tests = sum(
            1 for f in analyzer.test_functions
            if any(k in f.name.lower() for k in keywords)
        )
        if analyzer.test_functions:
            ratio = ec_tests / len(analyzer.test_functions)
            if 0.3 <= ratio <= 0.5:
                score += 30
            elif 0.2 <= ratio < 0.3:
                score += 20
            elif ratio > 0.5:
                score += 10
            else:
                score -= 20
        if analyzer.has_parametrize:
            score += 20
        return max(0, min(100, score))

    def _naming_score() -> float:
        if not analyzer.test_functions:
            return 0.0
        poor = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.POOR_NAMING)
        score = 100.0 - (poor / len(analyzer.test_functions)) * 100
        if all("_" in f.name for f in analyzer.test_functions):
            score += 10
        return max(0, min(100, score))

    def _doc_score() -> float:
        if not analyzer.test_functions:
            return 0.0
        missing = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.MISSING_DOCSTRING)
        return max(0, min(100, 100.0 - (missing / len(analyzer.test_functions)) * 100))

    def _maintain_score() -> float:
        score = 100.0
        high_smells = {TestSmell.SLEEPY_TEST, TestSmell.CONDITIONAL_LOGIC,
                       TestSmell.EXCEPTION_SWALLOWING, TestSmell.EMPTY_TEST}
        for s in analyzer.smells:
            if s.smell_type in high_smells:
                score -= 15
            elif s.severity == "medium":
                score -= 5
            elif s.severity == "low":
                score -= 2
        if analyzer.has_fixtures:
            score += 10
        if analyzer.has_mocks:
            score += 5
        if analyzer.has_parametrize:
            score += 10
        return max(0, min(100, score))

    a_score  = _assertion_score()
    ec_score = _edge_case_score()
    n_score  = _naming_score()
    d_score  = _doc_score()
    m_score  = _maintain_score()

    overall = (a_score * 0.25 + ec_score * 0.25 + n_score * 0.15 +
               d_score * 0.15 + m_score * 0.20)
    high_count = sum(1 for s in analyzer.smells if s.severity == "high")
    overall = max(0, overall - high_count * 5)

    strengths, improvements = [], []
    if a_score >= 80:   strengths.append("Excellent assertion quality")
    elif a_score < 50:  improvements.append("Improve assertion clarity and coverage")
    if ec_score >= 80:  strengths.append("Comprehensive edge case coverage")
    elif ec_score < 50: improvements.append("Add more edge case tests (empty, null, boundary values)")
    if n_score >= 80:   strengths.append("Clear and descriptive test names")
    elif n_score < 50:  improvements.append("Use more descriptive test names")
    if d_score >= 80:   strengths.append("Well-documented tests")
    elif d_score < 50:  improvements.append("Add docstrings to test functions")
    if m_score >= 80:   strengths.append("Highly maintainable test code")
    elif m_score < 50:  improvements.append("Reduce test smells and improve maintainability")
    if analyzer.has_fixtures:   strengths.append("Uses pytest fixtures for setup")
    if analyzer.has_parametrize: strengths.append("Uses parametrized tests for multiple scenarios")
    if analyzer.has_mocks:       strengths.append("Properly uses mocks for isolation")
    smell_types = {s.smell_type for s in analyzer.smells}
    if TestSmell.SLEEPY_TEST in smell_types:
        improvements.append("Remove sleep() calls - use mocks or async waiting")
    if TestSmell.CONDITIONAL_LOGIC in smell_types:
        improvements.append("Remove conditional logic - split into separate tests")
    if TestSmell.TOO_MANY_ASSERTIONS in smell_types:
        improvements.append("Split tests with many assertions into focused tests")

    return QualityScore(
        overall_score=round(overall, 2),
        assertion_quality=round(a_score, 2),
        edge_case_coverage=round(ec_score, 2),
        naming_quality=round(n_score, 2),
        documentation_quality=round(d_score, 2),
        maintainability=round(m_score, 2),
        smells_detected=analyzer.smells,
        strengths=strengths,
        improvements=improvements,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Ensemble Test Generator (inlined from ensemble_test_generator.py)
# ══════════════════════════════════════════════════════════════════════════════

class ModelType(Enum):
    DEEPSEEK_CODER = "deepseek-coder:1.3b"
    STARCODER      = "starcoder"
    CODELLAMA      = "codellama:7b"
    LLAMA_CODE     = "llama3:code"


@dataclass
class ModelResult:
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
    final_test_code: str
    models_used: List[ModelType]
    best_model: ModelType
    quality_score: float
    generation_time: float
    voting_details: Dict[str, Any]
    merged_from: List[str] = field(default_factory=list)


class EnsembleTestGenerator:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.config = cfg or {
            "models": [ModelType.DEEPSEEK_CODER, ModelType.STARCODER, ModelType.CODELLAMA],
            "timeout_per_model": 60,
            "parallel_execution": True,
            "voting_strategy": "quality_weighted",
            "merge_strategy": "complementary",
            "min_quality_threshold": 50.0,
            "weights": {
                ModelType.DEEPSEEK_CODER: 1.0,
                ModelType.STARCODER: 0.9,
                ModelType.CODELLAMA: 0.8,
            },
        }
        self.timeout_per_model = self.config.get("timeout_per_model", 60)
        self.parallel_execution = self.config.get("parallel_execution", True)

    def generate(self, code: str) -> EnsembleResult:
        start_time = time.time()
        models = self.config["models"]

        if self.parallel_execution:
            model_results = self._generate_parallel(code, models)
        else:
            model_results = self._generate_sequential(code, models)

        successful = [r for r in model_results if r.success and r.test_code]

        if not successful:
            elapsed = time.time() - start_time
            return EnsembleResult(
                final_test_code="# All models failed\nimport pytest\n\ndef test_placeholder():\n    assert True",
                models_used=[], best_model=models[0], quality_score=0.0,
                generation_time=elapsed, voting_details={"error": "All models failed"},
            )

        scored = self._score_results(successful)
        voting = self._apply_voting(scored)
        final_code, merged_from = self._merge_results(scored, voting)
        best_result = max(scored, key=lambda r: r.quality_score)
        elapsed = time.time() - start_time

        return EnsembleResult(
            final_test_code=final_code,
            models_used=[r.model for r in successful],
            best_model=best_result.model,
            quality_score=best_result.quality_score,
            generation_time=elapsed,
            voting_details=voting,
            merged_from=merged_from,
        )

    def _generate_parallel(self, code: str, models: List[ModelType]) -> List[ModelResult]:
        results = []
        with ThreadPoolExecutor(max_workers=len(models)) as executor:
            future_to_model = {executor.submit(self._generate_from_model, code, m): m for m in models}
            for future in as_completed(future_to_model):
                model = future_to_model[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append(ModelResult(model=model, test_code=None,
                                               generation_time=0.0, success=False, error=str(e)))
        return results

    def _generate_sequential(self, code: str, models: List[ModelType]) -> List[ModelResult]:
        return [self._generate_from_model(code, m) for m in models]

    def _generate_from_model(self, code: str, model: ModelType) -> ModelResult:
        start_time = time.time()
        prompt = (self._starcoder_prompt(code) if "starcoder" in model.value
                  else self._chat_prompt(code))
        try:
            result = subprocess.run(
                ["ollama", "run", model.value, prompt],
                capture_output=True, text=True,
                timeout=self.timeout_per_model, encoding="utf-8", errors="ignore",
            )
            elapsed = time.time() - start_time
            if result.returncode != 0:
                return ModelResult(model=model, test_code=None, generation_time=elapsed,
                                   success=False, error=f"Exit code {result.returncode}")
            test_code = self._extract_test_code(result.stdout)
            if not test_code:
                return ModelResult(model=model, test_code=None, generation_time=elapsed,
                                   success=False, error="No valid test code extracted")
            num_tests = test_code.count("def test_")
            has_edge = any(k in test_code.lower() for k in ["empty", "none", "null", "invalid", "edge"])
            return ModelResult(model=model, test_code=test_code, generation_time=elapsed,
                               success=True, num_tests=num_tests, has_edge_cases=has_edge)
        except subprocess.TimeoutExpired:
            return ModelResult(model=model, test_code=None,
                               generation_time=time.time() - start_time,
                               success=False, error=f"Timeout after {self.timeout_per_model}s")
        except Exception as e:
            return ModelResult(model=model, test_code=None,
                               generation_time=time.time() - start_time,
                               success=False, error=str(e))

    def _starcoder_prompt(self, code: str) -> str:
        return (f"<filename>test_code.py\nimport pytest\nimport sys\n\n{code}\n\n"
                f"# Write comprehensive pytest test cases:\nimport pytest\n\ndef test_")

    def _chat_prompt(self, code: str) -> str:
        return (f"You are an expert QA engineer. Generate comprehensive pytest tests.\n\n"
                f"Requirements:\n1. Cover edge cases\n2. Test happy paths\n"
                f"3. Test error handling\n4. Return ONLY valid Python in a markdown block\n\n"
                f"Code:\n{code}\n\nGenerate complete test file:")

    def _extract_test_code(self, output: str) -> Optional[str]:
        ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        output = ansi.sub("", output)
        if "```python" in output:
            parts = output.split("```python")
            if len(parts) > 1:
                code = parts[1].split("```")[0].strip()
                if code:
                    return code
        elif "```" in output:
            parts = output.split("```")
            for i in range(1, len(parts), 2):
                c = parts[i].strip()
                if c and ("import" in c or "def test" in c.lower()):
                    return c
        match = re.search(r"(import|def test_|from)", output, re.IGNORECASE)
        if match:
            output = output[match.start():].strip()
        if "def test_" in output.lower() or "import pytest" in output:
            return output
        return None

    def _score_results(self, results: List[ModelResult]) -> List[ModelResult]:
        for result in results:
            if not result.test_code:
                continue
            try:
                quality = analyze_test_quality(result.test_code)
                base_score = quality.overall_score
            except Exception:
                base_score = 50.0
            model_weight = self.config["weights"].get(result.model, 1.0)
            edge_bonus = 10 if result.has_edge_cases else 0
            count_bonus = 10 if result.num_tests >= 5 else (5 if result.num_tests >= 3 else 0)
            time_penalty = 5 if result.generation_time > 30 else (10 if result.generation_time > 60 else 0)
            result.quality_score = min(100.0, max(0.0,
                (base_score * model_weight) + edge_bonus + count_bonus - time_penalty))
        return results

    def _apply_voting(self, results: List[ModelResult]) -> Dict[str, Any]:
        strategy = self.config.get("voting_strategy", "quality_weighted")
        threshold = self.config.get("min_quality_threshold", 50.0)

        if strategy == "best_of":
            best = max(results, key=lambda r: r.quality_score)
            return {"strategy": "best_of", "winner": best.model.value,
                    "score": best.quality_score, "selected_models": [best.model.value]}

        elif strategy == "quality_weighted":
            qualified = [r for r in results if r.quality_score >= threshold]
            if not qualified:
                best = max(results, key=lambda r: r.quality_score)
                return {"strategy": "quality_weighted_fallback", "winner": best.model.value,
                        "score": best.quality_score, "selected_models": [best.model.value]}
            total_weight = sum(r.quality_score for r in qualified)
            votes = {r.model.value: r.quality_score / total_weight for r in qualified}
            avg_weight = 1.0 / len(qualified)
            selected = [m for m, w in votes.items() if w >= avg_weight]
            return {"strategy": "quality_weighted", "votes": votes,
                    "selected_models": selected, "threshold": threshold}

        elif strategy == "majority":
            median_score = sorted(r.quality_score for r in results)[len(results) // 2]
            selected = [r.model.value for r in results if r.quality_score >= median_score]
            return {"strategy": "majority", "median_score": median_score, "selected_models": selected}

        best = max(results, key=lambda r: r.quality_score)
        return {"strategy": "default", "winner": best.model.value,
                "selected_models": [best.model.value]}

    def _merge_results(self, results: List[ModelResult],
                       voting: Dict[str, Any]) -> Tuple[str, List[str]]:
        merge_strategy = self.config.get("merge_strategy", "complementary")
        selected_models = voting.get("selected_models", [])
        selected = [r for r in results if r.model.value in selected_models]

        if not selected:
            best = max(results, key=lambda r: r.quality_score)
            return best.test_code, [best.model.value]

        if merge_strategy == "best_only":
            best = max(selected, key=lambda r: r.quality_score)
            return best.test_code, [best.model.value]

        elif merge_strategy == "complementary":
            all_funcs, seen_sigs, merged_from = [], set(), []
            for result in sorted(selected, key=lambda r: r.quality_score, reverse=True):
                if not result.test_code:
                    continue
                try:
                    tree = ast.parse(result.test_code)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                            name = node.name
                            num_asserts = sum(1 for n in ast.walk(node) if isinstance(n, ast.Assert))
                            parts = name.lower().split("_")
                            key_parts = [p for p in parts if len(p) > 3 and p not in
                                         {"test", "with", "when", "then"}]
                            sig = f"{'-'.join(key_parts)}:{num_asserts}"
                            if sig not in seen_sigs:
                                seen_sigs.add(sig)
                                all_funcs.append(ast.unparse(node))
                                if result.model.value not in merged_from:
                                    merged_from.append(result.model.value)
                except Exception:
                    continue
            if not all_funcs:
                best = sorted(selected, key=lambda r: r.quality_score, reverse=True)[0]
                return best.test_code, [best.model.value]
            imports = "import pytest\nimport sys\nfrom typing import Any\n\n"
            return imports + "\n\n".join(all_funcs), merged_from

        elif merge_strategy == "all":
            parts = [f"# Tests from {r.model.value}\n{r.test_code}\n" for r in selected if r.test_code]
            merged_from = [r.model.value for r in selected if r.test_code]
            return "\n\n".join(parts), merged_from

        best = max(selected, key=lambda r: r.quality_score)
        return best.test_code, [best.model.value]


def generate_ensemble_tests(code: str, cfg: Optional[Dict[str, Any]] = None) -> EnsembleResult:
    return EnsembleTestGenerator(cfg).generate(code)


# ══════════════════════════════════════════════════════════════════════════════
# Project Context Cache (inlined from flask app.py ProjectContext)
# ══════════════════════════════════════════════════════════════════════════════

class ProjectContext:
    def __init__(self, file_paths: List[str]):
        self.file_paths = file_paths
        self.summaries: Dict[str, str] = {}
        self._precompute_summaries()

    def _precompute_summaries(self):
        for file_path in self.file_paths:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.summaries[file_path] = self._generate_single_summary(file_path, content)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")
                self.summaries[file_path] = ""

    def _generate_single_summary(self, file_path: str, content: str) -> str:
        try:
            tree = ast.parse(content)
            rel_path = os.path.basename(file_path)
            lines = [f"# File: {rel_path}"]
            doc = ast.get_docstring(tree)
            if doc:
                lines.append(f'"""{doc}"""')
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name.startswith("_"):
                        continue
                    args = [a.arg for a in node.args.args]
                    fn_doc = ast.get_docstring(node)
                    sig = f"def {node.name}({', '.join(args)}):"
                    if fn_doc:
                        sig += f" # {fn_doc.splitlines()[0]}"
                    lines.append(sig)
                elif isinstance(node, ast.ClassDef):
                    if node.name.startswith("_"):
                        continue
                    lines.append(f"class {node.name}:")
                    cls_doc = ast.get_docstring(node)
                    if cls_doc:
                        lines.append(f'    """{cls_doc.splitlines()[0]}"""')
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            m_args = [a.arg for a in item.args.args]
                            m_doc = ast.get_docstring(item)
                            m_sig = f"    def {item.name}({', '.join(m_args)}):"
                            if m_doc:
                                m_sig += f" # {m_doc.splitlines()[0]}"
                            lines.append(m_sig)
            return "\n".join(lines)
        except Exception:
            return ""

    def get_context_for_file(self, target_file: str) -> str:
        return "\n\n".join(
            summary for path, summary in self.summaries.items()
            if path != target_file and summary
        )


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


def fallback_simple_tests(code: str, module_name: str) -> str:
    """Generate minimal fallback tests when all LLM methods fail."""
    try:
        tree = ast.parse(code)
        functions = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]
    except Exception:
        functions = []

    lines = [f"import pytest", f"# Fallback tests for {module_name}", ""]
    if functions:
        for fn in functions:
            lines.append(f"def test_{fn}_exists():")
            lines.append(f'    """Test that {fn} is importable."""')
            lines.append(f"    from {module_name} import {fn}")
            lines.append(f"    assert callable({fn})")
            lines.append("")
    else:
        lines.append("def test_module_importable():")
        lines.append(f'    """Test that {module_name} can be imported."""')
        lines.append(f"    import {module_name}")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Project context extraction (original get_file_context kept for compatibility)
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
# Core: process one file with strategy selection, ensemble, and quality analysis
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
    strategy: str = "auto",
    force_ensemble: bool = False,
) -> dict:
    """
    Generate tests + metrics for a single file.
    Applies strategy selection, ensemble generation, quality analysis, and metrics.
    force_ensemble=True bypasses strategy selection and runs ensemble unconditionally.
    Updates jobs[job_id]['current_file'] while running.
    """
    jobs[job_id]["current_file"] = f"{module_name}.py"
    work_dir = tempfile.mkdtemp(prefix="codexter_")
    entry: Dict[str, Any] = {"file": f"{module_name}.py", "status": "pending"}

    try:
        # Write source so pytest can import it
        src_path = os.path.join(work_dir, f"{module_name}.py")
        with open(src_path, "w") as f:
            f.write(code)
        with open(os.path.join(work_dir, "__init__.py"), "w") as f:
            f.write("")

        prompt_code = f"{code}\n\n# Context from other project files:\n{context}" if context else code

        # ── Strategy Selection ────────────────────────────────────────────
        file_strategy = strategy
        if strategy == "auto" and not force_ensemble:
            selected_strategy, strategy_details = select_test_strategy(code, file_path)
            file_strategy = selected_strategy.value
            entry["strategy_details"] = {
                "selected": file_strategy,
                "confidence": strategy_details.get("confidence", 0),
                "complexity_score": strategy_details.get("metrics", {}).get("overall_score", 0),
            }
            print(f"  [STRATEGY] {module_name}.py: {file_strategy}")

        # ── Test Generation ───────────────────────────────────────────────
        tests = None
        generation_method = "unknown"

        # Try Ensemble — triggered either by force_ensemble flag or by strategy selection
        run_ensemble = force_ensemble or (file_strategy == "ensemble" and config.get("enable_ensemble", False))
        if run_ensemble:
            try:
                print(f"  [ENSEMBLE] {module_name}.py...")
                ensemble_result = generate_ensemble_tests(prompt_code)
                tests = ensemble_result.final_test_code
                generation_method = "ensemble"
                entry["ensemble_details"] = {
                    "models_used": [m.value for m in ensemble_result.models_used],
                    "best_model": ensemble_result.best_model.value,
                    "quality_score": ensemble_result.quality_score,
                }
            except Exception as e:
                print(f"  [WARNING] Ensemble failed for {module_name}.py: {e}")
                # Fall through to single-model below

        # Try Standard (Ollama)
        if not tests:
            generation_method = "single_model"
            tests = generate_tests_ollama(
                code=code,
                module_name=module_name,
                context=context,
                ollama_url=ollama_url,
                model=model,
                timeout=timeout,
            )

        # Fallback
        if not tests or not tests.strip():
            print(f"  [FALLBACK] Generating simple tests for {module_name}.py")
            tests = fallback_simple_tests(code, module_name)
            generation_method = "fallback"
            entry["is_fallback"] = True

        ast.parse(tests)  # validate syntax

        # Save to TESTS_FOLDER so it can be bundled into a download ZIP
        out_name = f"test_{module_name}.py"
        out_path = os.path.join(TESTS_FOLDER, out_name)
        with open(out_path, "w") as tf:
            tf.write(tests)

        test_path = os.path.join(work_dir, out_name)
        with open(test_path, "w") as tf:
            tf.write(tests)

        entry["status"]            = "success"
        entry["test_file"]         = out_name
        entry["full_path"]         = out_path
        entry["content"]           = tests
        entry["generation_method"] = generation_method

        # ── Metrics ───────────────────────────────────────────────────────
        try:
            cov, _ = calculate_coverage(src_path, test_path, work_dir)
            mut, _ = calculate_mutation_score(module_name, test_path, work_dir)
            entry["coverage"]      = cov
            entry["mutation_score"] = mut
            entry["metrics"] = {
                "coverage_percent": round(cov * 100, 2),
                "mutation_score":   round(mut, 4),
                "has_errors":       False,
            }
        except Exception as e:
            entry["coverage"]      = 0.0
            entry["mutation_score"] = 0.0
            entry["metrics"] = {"coverage_percent": 0.0, "mutation_score": 0.0, "has_errors": True}

        # ── Quality Analysis ──────────────────────────────────────────────
        if config.get("enable_quality_analysis", True):
            try:
                quality = analyze_test_quality(tests, code)
                entry["quality_analysis"] = {
                    "overall_score": quality.overall_score,
                    "smells_count": len(quality.smells_detected),
                    "scores": {
                        "assertion_quality":    quality.assertion_quality,
                        "edge_case_coverage":   quality.edge_case_coverage,
                        "naming_quality":       quality.naming_quality,
                        "documentation_quality": quality.documentation_quality,
                        "maintainability":      quality.maintainability,
                    },
                    "strengths":    quality.strengths,
                    "improvements": quality.improvements,
                }
            except Exception as e:
                print(f"  [WARNING] Quality analysis failed for {module_name}.py: {e}")

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
    jobs[job_id]["status"]      = "processing"
    jobs[job_id]["progress"]    = 0
    jobs[job_id]["total_files"] = 1

    try:
        entry = _process_one_file(
            job_id=job_id, code=code, module_name=module_name,
            file_path=file_path, ollama_url=ollama_url, model=model,
            timeout=timeout, strategy=config.get("default_strategy", "auto"),
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
    files: list,
    ollama_url: str,
    model: str,
    timeout: int,
):
    """Background worker for a multiple-file job."""
    jobs[job_id]["status"]      = "processing"
    jobs[job_id]["progress"]    = 0
    jobs[job_id]["results"]     = []
    jobs[job_id]["total_files"] = len(files)

    all_real_paths = [f["file_path"] for f in files if os.path.isfile(f.get("file_path", ""))]

    # Build ProjectContext cache if we have real paths
    project_context = ProjectContext(all_real_paths) if all_real_paths else None

    try:
        for i, file_info in enumerate(files):
            code        = file_info["code"]
            module_name = file_info["module_name"]
            file_path   = file_info.get("file_path", "")

            context = (project_context.get_context_for_file(file_path)
                       if project_context else "")

            entry = _process_one_file(
                job_id=job_id, code=code, module_name=module_name,
                file_path=file_path, ollama_url=ollama_url, model=model,
                timeout=timeout, context=context,
                strategy=config.get("default_strategy", "auto"),
            )

            jobs[job_id]["results"].append(entry)
            jobs[job_id]["progress"] = int(((i + 1) / len(files)) * 100)

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
    analysis_mode: str = "single",   # "single" | "ensemble"
):
    """Background worker for ZIP job with parallel processing and ProjectContext cache."""
    jobs[job_id]["status"]   = "processing"
    jobs[job_id]["progress"] = 0
    jobs[job_id]["results"]  = []

    # "single"   → standard single-model generation, ensemble never triggered
    # "ensemble" → force ensemble generation for every file
    use_ensemble = (analysis_mode == "ensemble")
    job_strategy = "ensemble" if use_ensemble else "standard"

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

        # Build ProjectContext cache once for all files
        print(f"[{job_id}] Building project context... (mode={analysis_mode})")
        project_context = ProjectContext(python_files)

        max_workers = config.get("max_concurrency", 3)
        completed_count = 0

        def _process_zip_file(py_file: str) -> dict:
            file_name   = os.path.basename(py_file)
            module_name = os.path.splitext(file_name)[0]
            with open(py_file, "r", encoding="utf-8") as f:
                code = f.read()
            context = project_context.get_context_for_file(py_file)
            return _process_one_file(
                job_id=job_id, code=code, module_name=module_name,
                file_path=py_file, ollama_url=ollama_url, model=model,
                timeout=timeout, context=context, strategy=job_strategy,
                force_ensemble=use_ensemble,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(_process_zip_file, p): p for p in python_files}
            for future in as_completed(future_to_file):
                result = future.result()
                jobs[job_id]["results"].append(result)
                completed_count += 1
                jobs[job_id]["progress"] = int((completed_count / total) * 100)

        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for r in jobs[job_id]["results"]:
                if r["status"] == "success" and "full_path" in r:
                    zout.write(r["full_path"], r["test_file"])

        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["status"]       = "completed"
        jobs[job_id]["message"]      = f"Analysis complete ({analysis_mode} mode)"

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
    Single-file test generation — job-based.
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
            job_id, req.code, req.module_name, req.file_path,
            req.ollama_url, req.ollama_model, req.ollama_timeout,
        ),
        daemon=True,
    )
    thread.start()

    return {"message": "Job submitted", "job_id": job_id, "scope": "single"}


@app.post("/generate-tests-multiple")
async def generate_tests_multiple_endpoint(req: MultipleFileRequest):
    """
    Multiple-file test generation — job-based.
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
        args=(job_id, req.files, req.ollama_url, req.ollama_model, req.ollama_timeout),
        daemon=True,
    )
    thread.start()

    return {"message": "Job submitted", "job_id": job_id, "scope": "multiple"}


@app.post("/refactor", response_model=RefactorResponse)
async def refactor_endpoint(req: RefactorRequest):
    """Refactor a Python file using Ollama (synchronous)."""
    try:
        refactored, summary = refactor_code_ollama(
            code=req.code, module_name=req.module_name,
            ollama_url=req.ollama_url, model=req.ollama_model, timeout=req.ollama_timeout,
        )
        return RefactorResponse(refactored_code=refactored, summary=summary,
                                message="Refactoring complete")
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=500,
                            detail={"error": f"Cannot connect to Ollama at {req.ollama_url}"})
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.post("/analyze_zip")
async def analyze_zip(
    file:            UploadFile = File(...),
    ollama_model:    str = "deepseek-coder:1.3b",
    ollama_url:      str = "http://localhost:11434",
    ollama_timeout:  int = 120,
    analysis_mode:   str = "single",   # "single" | "ensemble"
):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted")

    if analysis_mode not in ("single", "ensemble"):
        raise HTTPException(status_code=400, detail="analysis_mode must be 'single' or 'ensemble'")

    job_id  = str(uuid.uuid4())
    job_dir = os.path.join(EXTRACT_FOLDER, job_id)
    os.makedirs(job_dir)

    zip_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{file.filename}")
    contents = await file.read()
    with open(zip_path, "wb") as f:
        f.write(contents)

    jobs[job_id] = {
        "status":        "queued",
        "submitted_at":  time.time(),
        "filename":      file.filename,
        "scope":         "zip",
        "analysis_mode": analysis_mode,
        "config": {
            "model":                    ollama_model,
            "timeout":                  ollama_timeout,
            "strategy":                 config.get("default_strategy", "auto"),
            "quality_analysis_enabled": config.get("enable_quality_analysis", True),
            "analysis_mode":            analysis_mode,
        },
    }

    thread = threading.Thread(
        target=process_zip_job,
        args=(job_id, zip_path, job_dir, ollama_model, ollama_url, ollama_timeout, analysis_mode),
        daemon=True,
    )
    thread.start()

    return {"message": "Job submitted", "job_id": job_id, "analysis_mode": analysis_mode}


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


@app.post("/analyze_strategy")
async def analyze_strategy(body: dict):
    """Analyze code and suggest optimal test strategy."""
    code = body.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    try:
        strategy, details = select_test_strategy(code)
        return {
            "strategy":   strategy.value,
            "confidence": details.get("confidence", 0),
            "metrics":    details.get("metrics", {}),
            "reasoning":  details.get("reasoning", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.post("/analyze_quality")
async def analyze_quality(body: dict):
    """Analyze test code quality."""
    test_code = body.get("test_code")
    if not test_code:
        raise HTTPException(status_code=400, detail="No test_code provided")
    source_code = body.get("source_code")
    try:
        quality = analyze_test_quality(test_code, source_code)
        return {
            "overall_score": quality.overall_score,
            "scores": {
                "assertion_quality":    quality.assertion_quality,
                "edge_case_coverage":   quality.edge_case_coverage,
                "naming_quality":       quality.naming_quality,
                "documentation_quality": quality.documentation_quality,
                "maintainability":      quality.maintainability,
            },
            "strengths":    quality.strengths,
            "improvements": quality.improvements,
            "smells": [
                {
                    "type":       s.smell_type.value,
                    "severity":   s.severity,
                    "line":       s.line_number,
                    "message":    s.message,
                    "suggestion": s.suggestion,
                }
                for s in quality.smells_detected
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/config")
async def get_config():
    """Get current configuration."""
    return config


@app.post("/config")
async def update_config(new_config: dict):
    """Update configuration."""
    global config
    try:
        config.update(new_config)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        return {"message": "Configuration updated", "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


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