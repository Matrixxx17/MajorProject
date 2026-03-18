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
import difflib
import io
from pathlib import Path
import requests
import traceback
import sys
import re
from typing import Dict, Any, List, Tuple, Optional, Set

os.environ["PYNGUIN_DANGER_AWARE"] = "1"

try:
    import pycodestyle
    _PYCODESTYLE_OK = True
except ImportError:
    _PYCODESTYLE_OK = False

try:
    from radon.complexity import cc_visit
    from radon.metrics import h_visit
    _RADON_OK = True
except ImportError:
    _RADON_OK = False
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

# ── Pynguin algorithms used for single-file generation ────────────────────────
PYNGUIN_ALGORITHMS   = ["RANDOM", "WHOLE_SUITE", "DYNAMOSA"]

# ── LLM models available for test generation ──────────────────────────────────
LLM_TEST_MODELS      = ["deepseek-coder:1.3b", "codellama:7b"]

# ── Refactoring constants ──────────────────────────────────────────────────────
REFACTOR_MODELS      = ["deepseek-coder:1.3b", "starcoder2:3b", "codellama:7b"]
PPO_MAX_ITERATIONS   = 5
PPO_REWARD_THRESHOLD = 0.6
REWARD_WEIGHTS       = {"cyclomatic": 0.35, "pep8": 0.30, "halstead": 0.20, "loc": 0.15}

# ── FIX 1: Per-model token budgets ─────────────────────────────────────────────
# Smaller models are faster; larger models need a raised token ceiling but also
# a tighter cap so they don't run forever on trivial code.
MODEL_NUM_PREDICT: Dict[str, int] = {
    "deepseek-coder:1.3b": 1024,   # fast, generous budget
    "starcoder2:3b":       1024,
    "codellama:7b":        768,    # slower — keep output shorter
    "llama3:code":         768,
}
DEFAULT_NUM_PREDICT = 1024   # fallback for unknown models

# ── FIX 2: Per-model base timeouts (seconds) ──────────────────────────────────
# These are MINIMUM timeouts regardless of what the caller requests.
# Actual timeout = max(caller_timeout, MODEL_BASE_TIMEOUT[model])
MODEL_BASE_TIMEOUT: Dict[str, int] = {
    "deepseek-coder:1.3b": 60,
    "starcoder2:3b":       90,
    "codellama:7b":        180,   # 7B model is slow on CPU — give it 3 min
    "llama3:code":         180,
}
DEFAULT_BASE_TIMEOUT = 120


# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> Dict[str, Any]:
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
    ollama_model:    str = "deepseek-coder:1.3b"
    ollama_url:      str = "http://localhost:11434"
    ollama_timeout:  int = 120
    approach:        str = "hybrid"
    selected_algos:  List[str] = ["RANDOM", "WHOLE_SUITE", "DYNAMOSA"]
    selected_models: List[str] = ["deepseek-coder:1.3b"]
    hybrid_algo:     str = "RANDOM"
    hybrid_llm:      str = "deepseek-coder:1.3b"

class MultipleFileRequest(BaseModel):
    files: list
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
    ollama_timeout: int = 300

class RefactorResponse(BaseModel):
    refactored_code: str
    summary: str
    message: str


# ══════════════════════════════════════════════════════════════════════════════
# Test Strategy Selector
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategy(Enum):
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
        if self.cyclomatic_complexity <= 5:       score += 5
        elif self.cyclomatic_complexity <= 10:    score += 15
        elif self.cyclomatic_complexity <= 20:    score += 25
        else:                                     score += 40
        if self.cognitive_complexity <= 5:        score += 3
        elif self.cognitive_complexity <= 15:     score += 12
        elif self.cognitive_complexity <= 30:     score += 22
        else:                                     score += 30
        if self.max_nesting_depth <= 2:           score += 2
        elif self.max_nesting_depth <= 4:         score += 8
        elif self.max_nesting_depth <= 6:         score += 12
        else:                                     score += 15
        special_score = 0
        if self.has_recursion:  special_score += 5
        if self.has_exceptions: special_score += 3
        if self.has_async:      special_score += 7
        score += min(special_score, 15)
        return min(score, 100.0)


class _ComplexityAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.cyclomatic = 1; self.cognitive = 0; self.nesting_depth = 0
        self.max_nesting = 0; self.num_functions = 0; self.num_classes = 0
        self.num_branches = 0; self.num_loops = 0
        self.has_recursion = False; self.has_exceptions = False; self.has_async = False
        self.function_calls: Set[str] = set()
        self.current_function: Optional[str] = None

    def visit_FunctionDef(self, node):
        self.num_functions += 1
        old = self.current_function; self.current_function = node.name
        self.nesting_depth += 1; self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node); self.nesting_depth -= 1; self.current_function = old

    def visit_AsyncFunctionDef(self, node):
        self.has_async = True; self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        self.num_classes += 1; self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node); self.nesting_depth -= 1

    def visit_If(self, node):
        self.cyclomatic += 1; self.num_branches += 1
        self.cognitive += (1 + self.nesting_depth); self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node); self.nesting_depth -= 1

    def visit_For(self, node):
        self.cyclomatic += 1; self.num_loops += 1
        self.cognitive += (1 + self.nesting_depth); self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node); self.nesting_depth -= 1

    def visit_While(self, node):
        self.cyclomatic += 1; self.num_loops += 1
        self.cognitive += (1 + self.nesting_depth); self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node); self.nesting_depth -= 1

    def visit_Try(self, node):
        self.has_exceptions = True; self.cyclomatic += len(node.handlers)
        self.cognitive += (1 + self.nesting_depth); self.nesting_depth += 1
        self.max_nesting = max(self.max_nesting, self.nesting_depth)
        self.generic_visit(node); self.nesting_depth -= 1

    def visit_ExceptHandler(self, node):
        self.num_branches += 1; self.generic_visit(node)

    def visit_With(self, node):
        self.cyclomatic += 1; self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            call_name = node.func.id; self.function_calls.add(call_name)
            if call_name == self.current_function: self.has_recursion = True
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.cyclomatic += len(node.values) - 1
        self.cognitive += len(node.values) - 1; self.generic_visit(node)


def _analyze_code_complexity(code: str) -> ComplexityMetrics:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ComplexityMetrics(1, 0, 0.0, len(code.splitlines()), 0, 0, 0, 0, 0, False, False, False)

    analyzer = _ComplexityAnalyzer(); analyzer.visit(tree)
    operators, operands = 0, 0
    unique_operators: Set[str] = set(); unique_operands: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
                              ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd,
                              ast.FloorDiv, ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq,
                              ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
                              ast.In, ast.NotIn)):
            operators += 1; unique_operators.add(type(node).__name__)
        if isinstance(node, ast.Name):
            operands += 1; unique_operands.add(node.id)
        elif isinstance(node, ast.Constant):
            operands += 1

    halstead_difficulty = 0.0
    if unique_operands:
        halstead_difficulty = (len(unique_operators) / 2.0) * (operands / len(unique_operands))

    return ComplexityMetrics(
        cyclomatic_complexity=analyzer.cyclomatic, cognitive_complexity=analyzer.cognitive,
        halstead_difficulty=halstead_difficulty, lines_of_code=len(code.splitlines()),
        num_functions=analyzer.num_functions, num_classes=analyzer.num_classes,
        max_nesting_depth=analyzer.max_nesting, num_branches=analyzer.num_branches,
        num_loops=analyzer.num_loops, has_recursion=analyzer.has_recursion,
        has_exceptions=analyzer.has_exceptions, has_async=analyzer.has_async,
    )


def select_test_strategy(code: str, file_path: Optional[str] = None) -> Tuple[TestStrategy, Dict[str, Any]]:
    metrics = _analyze_code_complexity(code)
    overall_score = metrics.get_overall_score()
    thresholds = {
        "simple":   {"max_complexity_score": 20, "max_cyclomatic": 5, "max_functions": 3},
        "standard": {"max_complexity_score": 50, "max_cyclomatic": 15, "max_nesting": 3},
        "advanced": {"max_complexity_score": 75, "max_cyclomatic": 30},
        "ensemble": {"min_complexity_score": 75, "min_cyclomatic": 20},
    }
    selected_strategy = None; confidence = 0.0; reasoning = []

    if (overall_score <= thresholds["simple"]["max_complexity_score"] and
            metrics.cyclomatic_complexity <= thresholds["simple"]["max_cyclomatic"] and
            metrics.num_functions <= thresholds["simple"]["max_functions"] and
            not metrics.has_recursion and not metrics.has_async):
        selected_strategy = TestStrategy.SIMPLE; confidence = 0.9
        reasoning.append("Code is very simple with low complexity")
    elif (overall_score >= thresholds["ensemble"]["min_complexity_score"] or
          metrics.cyclomatic_complexity >= thresholds["ensemble"]["min_cyclomatic"] or
          metrics.has_recursion or metrics.has_async or metrics.has_exceptions):
        if metrics.num_functions >= 5 or metrics.num_classes >= 2:
            selected_strategy = TestStrategy.ENSEMBLE; confidence = 0.85
            reasoning.append("High complexity warrants multi-model approach")
        elif metrics.has_recursion and metrics.cyclomatic_complexity > 10:
            selected_strategy = TestStrategy.ENSEMBLE; confidence = 0.8
            reasoning.append("Recursive functions benefit from ensemble")
        elif metrics.has_async and metrics.num_functions >= 3:
            selected_strategy = TestStrategy.ENSEMBLE; confidence = 0.75
            reasoning.append("Async code with multiple functions needs ensemble")
        else:
            selected_strategy = TestStrategy.ADVANCED; confidence = 0.7
            reasoning.append("Complex but not enough for ensemble")
    elif (overall_score >= thresholds["advanced"]["max_complexity_score"] or
          metrics.cyclomatic_complexity >= thresholds["standard"]["max_cyclomatic"] or
          metrics.max_nesting_depth > thresholds["standard"]["max_nesting"]):
        if metrics.has_exceptions and metrics.num_branches >= 5:
            selected_strategy = TestStrategy.ADVANCED; confidence = 0.8
            reasoning.append("Exception handling with multiple branches")
        elif metrics.num_loops >= 3 and metrics.max_nesting_depth >= 3:
            selected_strategy = TestStrategy.ADVANCED; confidence = 0.75
            reasoning.append("Multiple nested loops require advanced testing")
        elif metrics.num_classes >= 1 and metrics.num_functions >= 5:
            selected_strategy = TestStrategy.ADVANCED; confidence = 0.7
            reasoning.append("OOP code benefits from advanced strategy")
        else:
            selected_strategy = TestStrategy.STANDARD; confidence = 0.65
            reasoning.append("Moderate complexity, standard approach sufficient")
    elif overall_score >= thresholds["simple"]["max_complexity_score"]:
        selected_strategy = TestStrategy.STANDARD; confidence = 0.8
        reasoning.append("Standard complexity, single model sufficient")
    else:
        selected_strategy = TestStrategy.SIMPLE; confidence = 0.7
        reasoning.append("Low complexity, simple tests adequate")

    return selected_strategy, {
        "strategy": selected_strategy, "confidence": confidence,
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
        "reasoning": reasoning, "file_path": file_path,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Test Quality Analyzer
# ══════════════════════════════════════════════════════════════════════════════

class TestSmell(Enum):
    MAGIC_NUMBER = "magic_number"; UNCLEAR_ASSERTION = "unclear_assertion"
    NO_ASSERTION = "no_assertion"; TOO_MANY_ASSERTIONS = "too_many_assertions"
    DUPLICATE_TEST = "duplicate_test"; EMPTY_TEST = "empty_test"
    SLEEPY_TEST = "sleepy_test"; CONDITIONAL_LOGIC = "conditional_logic"
    HARDCODED_PATH = "hardcoded_path"; MISSING_DOCSTRING = "missing_docstring"
    POOR_NAMING = "poor_naming"; EXCEPTION_SWALLOWING = "exception_swallowing"
    RESOURCE_LEAK = "resource_leak"; GLOBAL_STATE = "global_state"
    MYSTERY_GUEST = "mystery_guest"


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
        self.has_fixtures = False; self.has_parametrize = False; self.has_mocks = False
        self.current_function = None

    def visit_Import(self, node):
        for alias in node.names: self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.add(node.module)
            if node.module == "pytest":
                for alias in node.names:
                    if alias.name == "fixture": self.has_fixtures = True
                    elif alias.name == "mark":  self.has_parametrize = True
            if "mock" in node.module.lower(): self.has_mocks = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            self.test_functions.append(node); self.current_function = node
            if not ast.get_docstring(node):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.MISSING_DOCSTRING, line_number=node.lineno,
                    severity="low", message=f"Test function '{node.name}' lacks docstring",
                    suggestion="Add docstring explaining what is being tested"))
            if not self._is_good_test_name(node.name):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.POOR_NAMING, line_number=node.lineno,
                    severity="medium", message=f"Test name '{node.name}' is not descriptive",
                    suggestion="Use pattern: test_<method>_<scenario>_<expected_result>"))
            self._analyze_test_body(node); self.current_function = None
        self.generic_visit(node)

    def _is_good_test_name(self, name: str) -> bool:
        if len(name) < 10: return False
        parts = name.split("_")
        if len(parts) < 3: return False
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
                        smell_type=TestSmell.UNCLEAR_ASSERTION, line_number=stmt.lineno,
                        severity="medium", message="Assertion lacks clear comparison",
                        suggestion="Use explicit comparisons: assert x == expected"))
            if isinstance(stmt, ast.Call):
                if isinstance(stmt.func, ast.Attribute) and stmt.func.attr in ("sleep", "wait"):
                    self.smells.append(TestSmellInstance(
                        smell_type=TestSmell.SLEEPY_TEST,
                        line_number=getattr(stmt, "lineno", 0), severity="high",
                        message="Test uses sleep/wait - makes tests slow",
                        suggestion="Use mocks or event-driven waiting instead"))
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.CONDITIONAL_LOGIC,
                    line_number=getattr(stmt, "lineno", node.lineno), severity="high",
                    message="Test contains conditional logic",
                    suggestion="Split into separate tests or use parametrize"))
            if isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    if not handler.type or (isinstance(handler.type, ast.Name) and handler.type.id == "Exception"):
                        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                            self.smells.append(TestSmellInstance(
                                smell_type=TestSmell.EXCEPTION_SWALLOWING,
                                line_number=getattr(stmt, "lineno", node.lineno), severity="high",
                                message="Test swallows exceptions silently",
                                suggestion="Use pytest.raises() for expected exceptions"))
        if assertion_count == 0:
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.NO_ASSERTION, line_number=node.lineno, severity="high",
                message=f"Test '{node.name}' has no assertions",
                suggestion="Add assertions to verify expected behavior"))
        elif assertion_count > 5:
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.TOO_MANY_ASSERTIONS, line_number=node.lineno, severity="medium",
                message=f"Test '{node.name}' has {assertion_count} assertions",
                suggestion="Consider splitting into multiple focused tests"))
        if len(node.body) <= 1 and (not node.body or isinstance(node.body[0], ast.Pass)):
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.EMPTY_TEST, line_number=node.lineno, severity="high",
                message=f"Test '{node.name}' is empty",
                suggestion="Implement test logic or remove placeholder"))

    def _is_unclear_assertion(self, assert_node: ast.Assert) -> bool:
        test_expr = assert_node.test
        if isinstance(test_expr, ast.Compare): return False
        if isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not): return False
        if isinstance(test_expr, ast.Call) and isinstance(test_expr.func, ast.Name):
            if any(test_expr.func.id.startswith(p) for p in ["is_", "has_", "can_", "should_"]): return False
        return True


def analyze_test_quality(test_code: str, source_code: Optional[str] = None) -> QualityScore:
    try:
        tree = ast.parse(test_code)
    except SyntaxError as e:
        return QualityScore(
            overall_score=0.0, assertion_quality=0.0, edge_case_coverage=0.0,
            naming_quality=0.0, documentation_quality=0.0, maintainability=0.0,
            smells_detected=[TestSmellInstance(
                smell_type=TestSmell.EMPTY_TEST, line_number=0, severity="high",
                message=f"Syntax error: {e}", suggestion="Fix syntax errors")],
            improvements=["Fix syntax errors"])

    analyzer = _TestQualityAnalyzer(test_code); analyzer.visit(tree)

    def _assertion_score() -> float:
        if not analyzer.test_functions: return 0.0
        score = 100.0
        no_assert = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.NO_ASSERTION)
        score -= (no_assert / len(analyzer.test_functions)) * 40
        unclear = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.UNCLEAR_ASSERTION)
        score -= (unclear / max(len(analyzer.assertions), 1)) * 30
        avg = len(analyzer.assertions) / len(analyzer.test_functions)
        if 1 <= avg <= 3: score += 10
        elif avg > 5:     score -= 10
        return max(0, min(100, score))

    def _edge_case_score() -> float:
        score = 50.0
        keywords = ["empty", "none", "null", "zero", "negative", "boundary",
                    "max", "min", "invalid", "error", "exception", "edge"]
        ec_tests = sum(1 for f in analyzer.test_functions
                       if any(k in f.name.lower() for k in keywords))
        if analyzer.test_functions:
            ratio = ec_tests / len(analyzer.test_functions)
            if 0.3 <= ratio <= 0.5:    score += 30
            elif 0.2 <= ratio < 0.3:   score += 20
            elif ratio > 0.5:          score += 10
            else:                      score -= 20
        if analyzer.has_parametrize: score += 20
        return max(0, min(100, score))

    def _naming_score() -> float:
        if not analyzer.test_functions: return 0.0
        poor = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.POOR_NAMING)
        score = 100.0 - (poor / len(analyzer.test_functions)) * 100
        if all("_" in f.name for f in analyzer.test_functions): score += 10
        return max(0, min(100, score))

    def _doc_score() -> float:
        if not analyzer.test_functions: return 0.0
        missing = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.MISSING_DOCSTRING)
        return max(0, min(100, 100.0 - (missing / len(analyzer.test_functions)) * 100))

    def _maintain_score() -> float:
        score = 100.0
        high_smells = {TestSmell.SLEEPY_TEST, TestSmell.CONDITIONAL_LOGIC,
                       TestSmell.EXCEPTION_SWALLOWING, TestSmell.EMPTY_TEST}
        for s in analyzer.smells:
            if s.smell_type in high_smells: score -= 15
            elif s.severity == "medium":    score -= 5
            elif s.severity == "low":       score -= 2
        if analyzer.has_fixtures:    score += 10
        if analyzer.has_mocks:       score += 5
        if analyzer.has_parametrize: score += 10
        return max(0, min(100, score))

    a_score = _assertion_score(); ec_score = _edge_case_score()
    n_score = _naming_score();    d_score  = _doc_score(); m_score = _maintain_score()
    overall = (a_score * 0.25 + ec_score * 0.25 + n_score * 0.15 + d_score * 0.15 + m_score * 0.20)
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
    if analyzer.has_fixtures:    strengths.append("Uses pytest fixtures for setup")
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
        overall_score=round(overall, 2), assertion_quality=round(a_score, 2),
        edge_case_coverage=round(ec_score, 2), naming_quality=round(n_score, 2),
        documentation_quality=round(d_score, 2), maintainability=round(m_score, 2),
        smells_detected=analyzer.smells, strengths=strengths, improvements=improvements)


# ══════════════════════════════════════════════════════════════════════════════
# Ensemble Test Generator
# ══════════════════════════════════════════════════════════════════════════════

class ModelType(Enum):
    DEEPSEEK_CODER = "deepseek-coder:1.3b"
    STARCODER      = "starcoder2:3b"
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
            "timeout_per_model": 60, "parallel_execution": True,
            "voting_strategy": "quality_weighted", "merge_strategy": "complementary",
            "min_quality_threshold": 50.0,
            "weights": {ModelType.DEEPSEEK_CODER: 1.0, ModelType.STARCODER: 0.9, ModelType.CODELLAMA: 0.8},
        }
        self.timeout_per_model = self.config.get("timeout_per_model", 60)
        self.parallel_execution = self.config.get("parallel_execution", True)
        # FIX: store ollama_url so _generate_from_model can use the REST API
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")

    def generate(self, code: str) -> EnsembleResult:
        start_time = time.time()
        models = self.config["models"]
        model_results = (self._generate_parallel(code, models) if self.parallel_execution
                         else self._generate_sequential(code, models))
        successful = [r for r in model_results if r.success and r.test_code]
        if not successful:
            elapsed = time.time() - start_time
            return EnsembleResult(
                final_test_code="# All models failed\nimport pytest\n\ndef test_placeholder():\n    assert True",
                models_used=[], best_model=models[0], quality_score=0.0,
                generation_time=elapsed, voting_details={"error": "All models failed"})
        scored = self._score_results(successful)
        voting = self._apply_voting(scored)
        final_code, merged_from = self._merge_results(scored, voting)
        best_result = max(scored, key=lambda r: r.quality_score)
        return EnsembleResult(
            final_test_code=final_code, models_used=[r.model for r in successful],
            best_model=best_result.model, quality_score=best_result.quality_score,
            generation_time=time.time() - start_time, voting_details=voting, merged_from=merged_from)

    def _generate_parallel(self, code, models):
        results = []
        with ThreadPoolExecutor(max_workers=len(models)) as ex:
            fmap = {ex.submit(self._generate_from_model, code, m): m for m in models}
            for future in as_completed(fmap):
                model = fmap[future]
                try:    results.append(future.result())
                except Exception as e:
                    results.append(ModelResult(model=model, test_code=None,
                                               generation_time=0.0, success=False, error=str(e)))
        return results

    def _generate_sequential(self, code, models):
        return [self._generate_from_model(code, m) for m in models]

    # ── FIX 3: Use REST API instead of CLI subprocess ──────────────────────────
    def _generate_from_model(self, code: str, model: ModelType) -> ModelResult:
        """
        Previously used `subprocess.run(['ollama', 'run', ...])` which:
          - Spawns a new process (slow startup ~5-10s each call)
          - Has no keep-alive connection to the Ollama daemon
          - Doesn't support per-model num_predict limits
        Now uses the REST API directly (same as call_ollama) with:
          - Per-model timeout from MODEL_BASE_TIMEOUT
          - Per-model token budget from MODEL_NUM_PREDICT
          - Proper JSON body with temperature controls
        """
        start_time = time.time()
        model_name = model.value

        # Resolve effective timeout: caller config OR model-specific minimum
        effective_timeout = max(
            self.timeout_per_model,
            MODEL_BASE_TIMEOUT.get(model_name, DEFAULT_BASE_TIMEOUT),
        )
        num_predict = MODEL_NUM_PREDICT.get(model_name, DEFAULT_NUM_PREDICT)

        prompt = self._build_prompt(code, model_name)

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "num_predict": num_predict,
                        # FIX: stop tokens prevent the model from rambling
                        "stop": ["# End of tests", "if __name__"],
                    },
                },
                timeout=effective_timeout,
            )
            response.raise_for_status()
            output = response.json().get("response", "")
            elapsed = time.time() - start_time

            test_code = self._extract_test_code(output)
            if not test_code:
                return ModelResult(
                    model=model, test_code=None, generation_time=elapsed,
                    success=False, error="No valid test code extracted from REST response",
                )

            return ModelResult(
                model=model, test_code=test_code, generation_time=elapsed,
                success=True,
                num_tests=test_code.count("def test_"),
                has_edge_cases=any(
                    k in test_code.lower()
                    for k in ["empty", "none", "null", "invalid", "edge"]
                ),
            )

        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            return ModelResult(
                model=model, test_code=None, generation_time=elapsed,
                success=False,
                error=f"REST API timeout after {effective_timeout}s for {model_name}",
            )
        except requests.exceptions.ConnectionError as e:
            return ModelResult(
                model=model, test_code=None, generation_time=time.time() - start_time,
                success=False, error=f"Cannot connect to Ollama: {e}",
            )
        except Exception as e:
            return ModelResult(
                model=model, test_code=None,
                generation_time=time.time() - start_time, success=False, error=str(e),
            )

    # ── FIX 4: Unified prompt builder (no more starcoder special-case via CLI) ─
    def _build_prompt(self, code: str, model_name: str) -> str:
        """
        starcoder2 works better with a fill-in-the-middle style prompt.
        All other models get a standard instruction prompt.
        The key change: prompts are shorter and more directive to reduce
        token output volume (which directly cuts latency for large models).
        """
        if "starcoder2" in model_name:
            # starcoder2 understands <fim_prefix>/<fim_suffix>/<fim_middle> tokens
            return (
                f"<fim_prefix>import pytest\n\n"
                f"# Source module under test:\n{code}\n\n"
                f"# Pytest tests — cover happy paths and edge cases:\n"
                f"<fim_suffix>\n<fim_middle>"
            )
        # Generic instruction prompt — kept deliberately short so the model
        # doesn't waste tokens on preamble/explanation.
        return (
            f"Write pytest tests for this Python code. "
            f"Output ONLY a valid Python file starting with `import pytest`. "
            f"Cover happy paths and edge cases. No explanations.\n\n"
            f"```python\n{code}\n```\n\n"
            f"import pytest\n"
        )

    def _extract_test_code(self, output):
        ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        output = ansi.sub("", output)
        if "```python" in output:
            parts = output.split("```python")
            if len(parts) > 1:
                code = parts[1].split("```")[0].strip()
                if code: return code
        elif "```" in output:
            parts = output.split("```")
            for i in range(1, len(parts), 2):
                c = parts[i].strip()
                if c and ("import" in c or "def test" in c.lower()): return c
        match = re.search(r"(import|def test_|from)", output, re.IGNORECASE)
        if match: output = output[match.start():].strip()
        if "def test_" in output.lower() or "import pytest" in output: return output
        return None

    def _score_results(self, results):
        for result in results:
            if not result.test_code: continue
            try:
                quality = analyze_test_quality(result.test_code)
                base_score = quality.overall_score
            except Exception: base_score = 50.0
            model_weight = self.config["weights"].get(result.model, 1.0)
            edge_bonus   = 10 if result.has_edge_cases else 0
            count_bonus  = 10 if result.num_tests >= 5 else (5 if result.num_tests >= 3 else 0)
            time_penalty = 5 if result.generation_time > 30 else (10 if result.generation_time > 60 else 0)
            result.quality_score = min(100.0, max(0.0,
                (base_score * model_weight) + edge_bonus + count_bonus - time_penalty))
        return results

    def _apply_voting(self, results):
        strategy  = self.config.get("voting_strategy", "quality_weighted")
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

    def _merge_results(self, results, voting):
        merge_strategy  = self.config.get("merge_strategy", "complementary")
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
                if not result.test_code: continue
                try:
                    tree = ast.parse(result.test_code)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                            num_asserts = sum(1 for n in ast.walk(node) if isinstance(n, ast.Assert))
                            parts = node.name.lower().split("_")
                            key_parts = [p for p in parts if len(p) > 3 and p not in
                                         {"test", "with", "when", "then"}]
                            sig = f"{'-'.join(key_parts)}:{num_asserts}"
                            if sig not in seen_sigs:
                                seen_sigs.add(sig); all_funcs.append(ast.unparse(node))
                                if result.model.value not in merged_from:
                                    merged_from.append(result.model.value)
                except Exception: continue
            if not all_funcs:
                best = sorted(selected, key=lambda r: r.quality_score, reverse=True)[0]
                return best.test_code, [best.model.value]
            return "import pytest\nimport sys\nfrom typing import Any\n\n" + "\n\n".join(all_funcs), merged_from
        elif merge_strategy == "all":
            parts = [f"# Tests from {r.model.value}\n{r.test_code}\n" for r in selected if r.test_code]
            return "\n\n".join(parts), [r.model.value for r in selected if r.test_code]
        best = max(selected, key=lambda r: r.quality_score)
        return best.test_code, [best.model.value]


def generate_ensemble_tests(code: str, cfg: Optional[Dict[str, Any]] = None) -> EnsembleResult:
    return EnsembleTestGenerator(cfg).generate(code)


# ══════════════════════════════════════════════════════════════════════════════
# Project Context Cache
# ══════════════════════════════════════════════════════════════════════════════

class ProjectContext:
    def __init__(self, file_paths: List[str]):
        self.file_paths = file_paths; self.summaries: Dict[str, str] = {}
        self._precompute_summaries()

    def _precompute_summaries(self):
        for file_path in self.file_paths:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.summaries[file_path] = self._generate_single_summary(file_path, content)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}"); self.summaries[file_path] = ""

    def _generate_single_summary(self, file_path, content):
        try:
            tree = ast.parse(content)
            lines = [f"# File: {os.path.basename(file_path)}"]
            doc = ast.get_docstring(tree)
            if doc: lines.append(f'"""{doc}"""')
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name.startswith("_"): continue
                    args = [a.arg for a in node.args.args]
                    sig = f"def {node.name}({', '.join(args)}):"
                    fn_doc = ast.get_docstring(node)
                    if fn_doc: sig += f" # {fn_doc.splitlines()[0]}"
                    lines.append(sig)
                elif isinstance(node, ast.ClassDef):
                    if node.name.startswith("_"): continue
                    lines.append(f"class {node.name}:")
                    cls_doc = ast.get_docstring(node)
                    if cls_doc: lines.append(f'    """{cls_doc.splitlines()[0]}"""')
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            m_args = [a.arg for a in item.args.args]
                            m_sig = f"    def {item.name}({', '.join(m_args)}):"
                            m_doc = ast.get_docstring(item)
                            if m_doc: m_sig += f" # {m_doc.splitlines()[0]}"
                            lines.append(m_sig)
            return "\n".join(lines)
        except Exception: return ""

    def get_context_for_file(self, target_file):
        return "\n\n".join(s for p, s in self.summaries.items() if p != target_file and s)


# ══════════════════════════════════════════════════════════════════════════════
# Ollama / LLM helpers
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_timeout(model: str, requested_timeout: int) -> int:
    """
    FIX 5: Return the effective timeout — whichever is larger:
    the caller's requested value or the model's known minimum.
    This prevents short caller timeouts from cutting off slow models.
    """
    return max(requested_timeout, MODEL_BASE_TIMEOUT.get(model, DEFAULT_BASE_TIMEOUT))


def call_ollama(prompt: str, ollama_url: str, model: str, timeout: int) -> str:
    # FIX 6: Use per-model num_predict and resolve effective timeout
    effective_timeout = _resolve_timeout(model, timeout)
    num_predict = MODEL_NUM_PREDICT.get(model, DEFAULT_NUM_PREDICT)

    response = requests.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": num_predict,       # was hardcoded 2048 — too high for codellama
                "stop": ["# End", "if __name__"], # prevent runaway generation
            },
        },
        timeout=effective_timeout,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def _clean_code(raw: str) -> str:
    ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    raw = ansi.sub("", raw).strip()
    match = re.search(r"```python\s*\n(.*?)```", raw, re.DOTALL)
    if match: return match.group(1).strip()
    match = re.search(r"```[a-z]*\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        if "def " in candidate or "import " in candidate: return candidate
    match = re.search(r"^(import |from |def |class )", raw, re.MULTILINE)
    if match: return raw[match.start():].strip()
    return raw.strip()


def generate_tests_ollama(code, module_name, context="",
                          ollama_url="http://localhost:11434",
                          model="deepseek-coder:1.3b", timeout=120) -> str:
    context_block = f"\n\n# Context from other project files:\n{context}" if context else ""

    # FIX 7: Shorter, more focused prompt reduces tokens-in AND tokens-out.
    # The old prompt had 9 numbered requirements which pushed large models to
    # write verbose preamble before any actual code.
    prompt = (
        f"Write pytest tests for the Python module `{module_name}` below. "
        f"Output ONLY valid Python — no markdown, no explanation. "
        f"Start with `import pytest`. "
        f"Cover all public functions, edge cases, and exceptions.\n\n"
        f"```python\n{code}{context_block}\n```\n\n"
        f"import pytest\n"
    )
    raw = call_ollama(prompt, ollama_url, model, timeout)
    return _clean_code(raw)


def refactor_code_ollama(code, module_name, ollama_url="http://localhost:11434",
                         model="deepseek-coder:1.3b", timeout=120) -> tuple[str, str]:
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


def _parse_refactor_response(raw, original):
    code_part = original; summary_part = "No summary provided."
    if "REFACTORED_CODE:" in raw and "SUMMARY:" in raw:
        parts = raw.split("SUMMARY:", 1); summary_part = parts[1].strip()
        code_section = parts[0].split("REFACTORED_CODE:", 1)[1].strip()
        code_part = _clean_code(code_section)
    else:
        cleaned = _clean_code(raw)
        if cleaned: code_part = cleaned
    return code_part, summary_part


def fallback_simple_tests(code: str, module_name: str) -> str:
    try:
        tree = ast.parse(code)
        functions = [node.name for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]
    except Exception:
        functions = []
    lines = ["import pytest", f"# Fallback tests for {module_name}", ""]
    if functions:
        for fn in functions:
            lines += [
                f"def test_{fn}_exists():",
                f'    """Test that {fn} is importable and callable."""',
                f"    try:",
                f"        from {module_name} import {fn}",
                f"        assert callable({fn})",
                f"    except ImportError:",
                f"        pytest.skip('Could not import {fn}')",
                ""]
    else:
        lines += [
            "def test_module_importable():",
            f'    """Test that {module_name} can be imported."""',
            f"    try:",
            f"        import {module_name}",
            f"        assert {module_name} is not None",
            f"    except ImportError:",
            f"        pytest.skip('Could not import {module_name}')",
            ""]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Metrics helpers
# ══════════════════════════════════════════════════════════════════════════════

def calculate_coverage(module_path: str, test_path: str, work_dir: str) -> tuple[float, list]:
    logs = []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path,
             f"--cov={module_path}", "--cov-report=json",
             "-v", "--tb=short", "-p", "no:cacheprovider"],
            cwd=work_dir, capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": work_dir})
        logs.append(f"pytest exit code: {result.returncode}")
        cov_json = os.path.join(work_dir, "coverage.json")
        if os.path.exists(cov_json):
            with open(cov_json) as f: data = json.load(f)
            pct = data.get("totals", {}).get("percent_covered", 0.0)
            logs.append(f"Coverage: {pct:.1f}%")
            return pct / 100.0, logs
        for line in result.stdout.split("\n"):
            if "TOTAL" in line:
                for part in line.split():
                    if part.endswith("%"):
                        try: return float(part.rstrip("%")) / 100.0, logs
                        except ValueError: pass
        logs.append("Could not parse coverage — defaulting to 0.0")
        return 0.0, logs
    except subprocess.TimeoutExpired:
        logs.append("Coverage timed out"); return 0.0, logs
    except Exception as e:
        logs.append(f"Coverage error: {e}"); return 0.0, logs


def calculate_mutation_score(module_name: str, test_path: str, work_dir: str) -> tuple[float, list]:
    logs = []
    try:
        pre = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "--tb=short", "-p", "no:cacheprovider"],
            cwd=work_dir, capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": work_dir})
        if pre.returncode != 0:
            logs.append("Tests failed pre-mutation — using default score 0.3")
            return 0.3, logs
        subprocess.run(
            [sys.executable, "-m", "mutmut", "run",
             "--paths-to-mutate", f"{module_name}.py", "--no-progress"],
            cwd=work_dir, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": work_dir})
        res = subprocess.run(
            [sys.executable, "-m", "mutmut", "results"],
            cwd=work_dir, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": work_dir})
        logs.append(f"mutmut output: {res.stdout[:300]}")
        score = _parse_mutation_score(res.stdout)
        logs.append(f"Mutation score: {score:.2%}")
        return score, logs
    except subprocess.TimeoutExpired:
        logs.append("Mutation testing timed out — using default 0.3"); return 0.3, logs
    except Exception as e:
        logs.append(f"Mutation error: {e}"); return 0.3, logs


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
    if total > 0: return killed / total
    for line in output.split("\n"):
        for part in line.split():
            if part.endswith("%"):
                try: return float(part.rstrip("%")) / 100
                except ValueError: pass
    return 0.5


# ══════════════════════════════════════════════════════════════════════════════
# ★  Coverage reading from Pynguin statistics.csv  (FIXED)
# ══════════════════════════════════════════════════════════════════════════════

def _read_pynguin_coverage(out_dir: str, work_dir: str, module_name: str) -> float:
    import csv as _csv

    COVERAGE_COLS = [
        "Coverage", "BranchCoverage", "LineCoverage",
        "coverage_percent", "coverage", "branch_coverage", "line_coverage",
    ]

    candidate_paths: List[str] = [
        os.path.join(out_dir, "statistics.csv"),
        os.path.join(out_dir, "pynguin-report", "statistics.csv"),
        os.path.join(work_dir, "statistics.csv"),
        os.path.join(work_dir, "pynguin-report", "statistics.csv"),
    ]

    for root, dirs, files in os.walk(work_dir):
        for fname in files:
            if fname == "statistics.csv":
                fp = os.path.join(root, fname)
                if fp not in candidate_paths:
                    candidate_paths.append(fp)

    for csv_path in candidate_paths:
        if not os.path.exists(csv_path):
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                raw = fh.read()

            ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            raw = ansi.sub("", raw)

            reader = _csv.DictReader(io.StringIO(raw))
            if not reader.fieldnames:
                continue

            field_map = {f.strip().strip('"').lower(): f for f in reader.fieldnames}

            cov_col = None
            for candidate in COVERAGE_COLS:
                if candidate.lower() in field_map:
                    cov_col = field_map[candidate.lower()]
                    break

            if cov_col is None:
                for f in reader.fieldnames:
                    if "coverage" in f.lower():
                        cov_col = f
                        break

            if cov_col is None:
                continue

            rows = list(reader)
            if not rows:
                continue

            target_col = None
            for f in reader.fieldnames:
                if f.strip().strip('"').lower() in ("targetmodule", "module", "module_name", "target_module"):
                    target_col = f
                    break

            matching_rows = rows
            if target_col:
                matched = [
                    r for r in rows
                    if r.get(target_col, "").strip().strip('"') == module_name
                ]
                if matched:
                    matching_rows = matched

            row = matching_rows[-1]
            raw_val = row.get(cov_col, "").strip().strip('"')
            if not raw_val:
                continue

            val = float(raw_val)
            if val <= 1.0:
                return val
            else:
                return val / 100.0

        except Exception as exc:
            print(f"[coverage] Failed to parse {csv_path}: {exc}")
            continue

    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# ★  Single-file Pynguin pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _pynguin_search_time(code: str) -> int:
    try:
        metrics = _analyze_code_complexity(code)
        branches = metrics.num_branches
        loc      = metrics.lines_of_code
        if branches <= 5  and loc <= 20:  return 10
        if branches <= 15 and loc <= 60:  return 20
        if branches <= 30 and loc <= 150: return 35
        return 60
    except Exception:
        return 30


def _deduplicate_tests(raw_code: str) -> str:
    try:
        tree = ast.parse(raw_code)
    except SyntaxError:
        return raw_code

    seen_bodies: list = []
    kept_nodes  = []

    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            kept_nodes.append(node)
            continue

        body_stmts = node.body
        if body_stmts and isinstance(body_stmts[0], ast.Expr) and isinstance(body_stmts[0].value, ast.Constant):
            body_stmts = body_stmts[1:]

        fingerprint = tuple(ast.unparse(s) for s in body_stmts)
        if fingerprint not in seen_bodies:
            seen_bodies.append(fingerprint)
            kept_nodes.append(node)

    tree.body = kept_nodes
    try:
        return ast.unparse(tree)
    except Exception:
        return raw_code


def _run_pynguin_algorithm(
    algorithm: str,
    module_name: str,
    src_path: str,
    work_dir: str,
    timeout: int = 120,
    source_code: str = "",
) -> dict:
    out_dir = os.path.join(work_dir, f"pynguin_{algorithm.lower()}")
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "algorithm": algorithm,
        "status": "pending",
        "test_code": None,
        "coverage": 0.0,
        "mutation_score": 0.0,
        "num_tests": 0,
        "error": None,
    }

    try:
        _src = source_code or ""
        if not _src:
            try:
                with open(src_path) as _f: _src = _f.read()
            except Exception: pass
        search_time = _pynguin_search_time(_src)

        proc = subprocess.run(
            [
                sys.executable, "-m", "pynguin",
                "--project-path", os.path.dirname(src_path),
                "--module-name", module_name,
                "--output-path", out_dir,
                "--algorithm", algorithm,
                "--maximum-search-time", str(search_time),
                "--assertion-generation", "MUTATION_ANALYSIS",
                "-v",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": os.path.dirname(src_path)},
        )

        test_file = os.path.join(out_dir, f"test_{module_name}.py")
        if not os.path.exists(test_file):
            py_files = [f for f in os.listdir(out_dir) if f.endswith(".py")]
            if py_files:
                test_file = os.path.join(out_dir, py_files[0])

        if not os.path.exists(test_file):
            result["status"] = "error"
            stderr_snippet = (proc.stderr or "")[:400]
            result["error"] = f"Pynguin produced no test file. stderr: {stderr_snippet}"
            return result

        with open(test_file, "r", encoding="utf-8") as f:
            raw_tests = f.read()

        if not raw_tests.strip():
            result["status"] = "error"
            result["error"] = "Pynguin produced an empty test file"
            return result

        raw_tests = _deduplicate_tests(raw_tests)

        result["test_code"] = raw_tests
        result["num_tests"] = raw_tests.count("def test_")
        result["status"] = "success"

        cov = _read_pynguin_coverage(out_dir, work_dir, module_name)

        if cov == 0.0:
            mdir = tempfile.mkdtemp(prefix=f"codexter_cov_{algorithm}_")
            try:
                shutil.copy(src_path, os.path.join(mdir, f"{module_name}.py"))
                open(os.path.join(mdir, "__init__.py"), "w").close()
                test_dest = os.path.join(mdir, f"test_{module_name}_{algorithm.lower()}.py")
                with open(test_dest, "w") as f:
                    f.write(raw_tests)
                cov, cov_logs = calculate_coverage(
                    os.path.join(mdir, f"{module_name}.py"), test_dest, mdir
                )
                print(f"[coverage fallback] {algorithm}: {cov:.2%} — logs: {cov_logs}")
            except Exception as cov_err:
                print(f"[coverage fallback] {algorithm}: error — {cov_err}")
            finally:
                shutil.rmtree(mdir, ignore_errors=True)

        mdir = tempfile.mkdtemp(prefix=f"codexter_{algorithm}_")
        try:
            shutil.copy(src_path, os.path.join(mdir, f"{module_name}.py"))
            open(os.path.join(mdir, "__init__.py"), "w").close()
            test_dest = os.path.join(mdir, f"test_{module_name}_{algorithm.lower()}.py")
            with open(test_dest, "w") as f:
                f.write(raw_tests)
            mut, _ = calculate_mutation_score(module_name, test_dest, mdir)
        finally:
            shutil.rmtree(mdir, ignore_errors=True)

        result["coverage"]       = cov
        result["mutation_score"] = mut

    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["error"]  = f"Pynguin timed out after {timeout}s"
    except FileNotFoundError:
        result["status"] = "error"
        result["error"]  = "pynguin not found — install with: pip install pynguin"
    except Exception as e:
        result["status"] = "error"
        result["error"]  = str(e)

    return result


def _refine_tests_with_llm(
    algo_results: List[dict],
    source_code: str,
    module_name: str,
    ollama_url: str,
    model: str,
    timeout: int,
) -> dict:
    successful = [r for r in algo_results if r["status"] == "success" and r["test_code"]]
    if not successful:
        return {"status": "error", "refined_code": None,
                "error": "No successful algo outputs to refine"}

    combined_tests = "\n\n".join(
        f"# ── Tests from {r['algorithm']} "
        f"(cov: {r['coverage']:.1%}, mut: {r['mutation_score']:.1%}) ──\n"
        + r["test_code"]
        for r in successful
    )

    prompt = f"""You are an expert Python QA engineer. You have been given auto-generated pytest tests
produced by Pynguin using {len(successful)} different search algorithms for the same module.
Your task is to produce a single, refined, high-quality pytest test file by:

1. Removing duplicate tests (keep the best version of each)
2. Fixing any broken imports or invalid assertions
3. Adding clear docstrings to every test function
4. Renaming tests to follow: test_<function>_<scenario>_<expected>
5. Adding any obvious missing edge-case tests
6. Using pytest.mark.parametrize where repetition exists
7. Ensuring all assertions are explicit (assert x == expected, not just assert x)

Source module ({module_name}):
```python
{source_code}
```

Auto-generated tests from Pynguin algorithms:
```python
{combined_tests}
```

Return ONLY the complete refined Python test file. No markdown fences. No explanations.
Start directly with `import pytest`."""

    try:
        raw = call_ollama(prompt, ollama_url, model, timeout)
        refined = _clean_code(raw)

        try:
            ast.parse(refined)
        except SyntaxError:
            refined = _clean_code(refined)
            try:
                ast.parse(refined)
            except SyntaxError:
                refined = fallback_simple_tests(source_code, module_name)

        return {"status": "success", "refined_code": refined, "error": None}

    except Exception as e:
        return {"status": "error", "refined_code": None, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# ★  Single-file: Pynguin-only worker
# ══════════════════════════════════════════════════════════════════════════════

def process_single_file_pynguin(
    job_id: str,
    code: str,
    module_name: str,
    file_path: str,
    ollama_url: str,
    model: str,
    timeout: int,
    selected_algos: Optional[List[str]] = None,
):
    algos = [a for a in PYNGUIN_ALGORITHMS if a in (selected_algos or PYNGUIN_ALGORITHMS)]
    if not algos:
        algos = PYNGUIN_ALGORITHMS

    jobs[job_id]["status"]   = "processing"
    jobs[job_id]["progress"] = 0
    jobs[job_id]["phase"]    = "pynguin"

    work_dir = tempfile.mkdtemp(prefix="codexter_single_")
    try:
        src_path = os.path.join(work_dir, f"{module_name}.py")
        with open(src_path, "w") as f:
            f.write(code)
        open(os.path.join(work_dir, "__init__.py"), "w").close()

        jobs[job_id]["phase"]       = "pynguin"
        jobs[job_id]["phase_label"] = f"Running {len(algos)} Pynguin algorithm(s)…"
        jobs[job_id]["progress"]    = 10

        algo_results: List[dict] = []

        def _run_algo(algo: str) -> dict:
            return _run_pynguin_algorithm(
                algorithm=algo, module_name=module_name,
                src_path=src_path, work_dir=work_dir, timeout=timeout,
                source_code=code,
            )

        with ThreadPoolExecutor(max_workers=len(algos)) as executor:
            futures = {executor.submit(_run_algo, algo): algo for algo in algos}
            done_count = 0
            for future in as_completed(futures):
                algo_results.append(future.result())
                done_count += 1
                jobs[job_id]["progress"] = 10 + int((done_count / len(algos)) * 85)

        order = {a: i for i, a in enumerate(PYNGUIN_ALGORITHMS)}
        algo_results.sort(key=lambda r: order.get(r["algorithm"], 99))

        jobs[job_id]["algo_results"] = algo_results
        jobs[job_id]["progress"]     = 95

        saved_files = []
        for r in algo_results:
            if r["status"] == "success" and r["test_code"]:
                fname    = f"test_{module_name}_{r['algorithm'].lower()}.py"
                out_path = os.path.join(TESTS_FOLDER, fname)
                with open(out_path, "w") as f:
                    f.write(r["test_code"])
                r["saved_path"] = out_path
                saved_files.append((out_path, fname))

        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for abs_path, arc_name in saved_files:
                if os.path.exists(abs_path):
                    zout.write(abs_path, arc_name)

        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["progress"]     = 100
        jobs[job_id]["status"]       = "completed"
        jobs[job_id]["phase"]        = "done"
        jobs[job_id]["phase_label"]  = "Complete"

        successful_algos = [r for r in algo_results if r["status"] == "success"]
        jobs[job_id]["message"] = (
            f"{len(successful_algos)}/{len(algos)} algorithm(s) succeeded."
        )

        jobs[job_id]["results"] = [
            {
                "file":           f"test_{module_name}_{r['algorithm'].lower()}.py",
                "algorithm":      r["algorithm"],
                "model":          None,
                "status":         r["status"],
                "content":        r["test_code"],
                "num_tests":      r["num_tests"],
                "coverage":       r["coverage"],
                "mutation_score": r["mutation_score"],
                "error":          r["error"],
                "metrics": {
                    "coverage_percent": round(r["coverage"] * 100, 2),
                    "mutation_score":   round(r["mutation_score"], 4),
                },
            }
            for r in algo_results
        ]

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# ★  Single-file: LLM-only worker
# ══════════════════════════════════════════════════════════════════════════════

def _run_llm_model_for_tests(
    model: str,
    code: str,
    module_name: str,
    src_path: str,
    ollama_url: str,
    timeout: int,
) -> dict:
    result: Dict[str, Any] = {
        "model":          model,
        "algorithm":      None,
        "status":         "pending",
        "test_code":      None,
        "coverage":       0.0,
        "mutation_score": 0.0,
        "num_tests":      0,
        "error":          None,
    }

    # FIX 8: Always use the effective (model-aware) timeout here too
    effective_timeout = _resolve_timeout(model, timeout)

    try:
        raw_tests = generate_tests_ollama(
            code=code, module_name=module_name,
            ollama_url=ollama_url, model=model, timeout=effective_timeout,
        )

        if not raw_tests or not raw_tests.strip():
            raw_tests = fallback_simple_tests(code, module_name)
            result["error"] = "LLM returned empty output — using fallback"

        try:
            ast.parse(raw_tests)
        except SyntaxError:
            raw_tests = _clean_code(raw_tests)
            try:
                ast.parse(raw_tests)
            except SyntaxError:
                raw_tests = fallback_simple_tests(code, module_name)
                result["error"] = "LLM output had syntax errors — using fallback"

        result["test_code"] = raw_tests
        result["num_tests"] = raw_tests.count("def test_")
        result["status"]    = "success"

        mdir = tempfile.mkdtemp(prefix=f"codexter_llm_")
        try:
            shutil.copy(src_path, os.path.join(mdir, f"{module_name}.py"))
            open(os.path.join(mdir, "__init__.py"), "w").close()
            safe_model = re.sub(r"[^a-z0-9]", "_", model.lower())
            test_fname = f"test_{module_name}_{safe_model}.py"
            test_dest  = os.path.join(mdir, test_fname)
            with open(test_dest, "w") as f:
                f.write(raw_tests)

            cov, _ = calculate_coverage(
                os.path.join(mdir, f"{module_name}.py"), test_dest, mdir)
            mut, _ = calculate_mutation_score(module_name, test_dest, mdir)
            result["coverage"]       = cov
            result["mutation_score"] = mut
        finally:
            shutil.rmtree(mdir, ignore_errors=True)

    except Exception as e:
        result["status"] = "error"
        result["error"]  = str(e)

    return result


def process_single_file_llm(
    job_id: str,
    code: str,
    module_name: str,
    file_path: str,
    ollama_url: str,
    timeout: int,
    selected_models: Optional[List[str]] = None,
):
    models = [m for m in LLM_TEST_MODELS if m in (selected_models or LLM_TEST_MODELS)]
    if not models:
        models = ["deepseek-coder:1.3b"]

    jobs[job_id]["status"]   = "processing"
    jobs[job_id]["progress"] = 0
    jobs[job_id]["phase"]    = "llm"

    work_dir = tempfile.mkdtemp(prefix="codexter_llm_single_")
    try:
        src_path = os.path.join(work_dir, f"{module_name}.py")
        with open(src_path, "w") as f:
            f.write(code)
        open(os.path.join(work_dir, "__init__.py"), "w").close()

        model_results: List[dict] = []

        for idx, model in enumerate(models):
            # FIX 9: Show the effective timeout in the progress label so users
            # know the system is respecting CodeLlama's longer generation time.
            eff_t = _resolve_timeout(model, timeout)
            jobs[job_id]["phase_label"] = (
                f"Running {model} ({idx+1}/{len(models)})… "
                f"[timeout: {eff_t}s]"
            )
            jobs[job_id]["progress"] = 5 + int(idx / len(models) * 85)

            r = _run_llm_model_for_tests(
                model=model, code=code, module_name=module_name,
                src_path=src_path, ollama_url=ollama_url, timeout=timeout,
            )
            model_results.append(r)
            jobs[job_id]["progress"] = 5 + int((idx + 1) / len(models) * 85)

        saved_files = []
        for r in model_results:
            if r["status"] == "success" and r["test_code"]:
                safe_model = re.sub(r"[^a-z0-9]", "_", r["model"].lower())
                fname    = f"test_{module_name}_{safe_model}.py"
                out_path = os.path.join(TESTS_FOLDER, fname)
                with open(out_path, "w") as f:
                    f.write(r["test_code"])
                r["saved_path"] = out_path
                saved_files.append((out_path, fname))

        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for abs_path, arc_name in saved_files:
                if os.path.exists(abs_path):
                    zout.write(abs_path, arc_name)

        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["progress"]     = 100
        jobs[job_id]["status"]       = "completed"
        jobs[job_id]["phase"]        = "done"
        jobs[job_id]["phase_label"]  = "Complete"

        ok = [r for r in model_results if r["status"] == "success"]
        jobs[job_id]["message"] = f"{len(ok)}/{len(models)} model(s) succeeded."

        jobs[job_id]["results"] = [
            {
                "file":           f"test_{module_name}_{re.sub(r'[^a-z0-9]','_',r['model'].lower())}.py",
                "algorithm":      None,
                "model":          r["model"],
                "status":         r["status"],
                "content":        r["test_code"],
                "num_tests":      r["num_tests"],
                "coverage":       r["coverage"],
                "mutation_score": r["mutation_score"],
                "error":          r["error"],
                "metrics": {
                    "coverage_percent": round(r["coverage"] * 100, 2),
                    "mutation_score":   round(r["mutation_score"], 4),
                },
            }
            for r in model_results
        ]

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# ★  Single-file: Hybrid worker
# ══════════════════════════════════════════════════════════════════════════════

def process_single_file_hybrid(
    job_id: str,
    code: str,
    module_name: str,
    file_path: str,
    ollama_url: str,
    model: str,
    timeout: int,
    hybrid_algo: str = "RANDOM",
    hybrid_llm: str = "deepseek-coder:1.3b",
):
    if hybrid_algo not in PYNGUIN_ALGORITHMS:
        hybrid_algo = "RANDOM"

    jobs[job_id]["status"]   = "processing"
    jobs[job_id]["progress"] = 0
    jobs[job_id]["phase"]    = "pynguin"

    work_dir = tempfile.mkdtemp(prefix="codexter_hybrid_")
    try:
        src_path = os.path.join(work_dir, f"{module_name}.py")
        with open(src_path, "w") as f:
            f.write(code)
        open(os.path.join(work_dir, "__init__.py"), "w").close()

        jobs[job_id]["phase_label"] = f"Running Pynguin/{hybrid_algo}…"
        jobs[job_id]["progress"]    = 10

        algo_result = _run_pynguin_algorithm(
            algorithm=hybrid_algo, module_name=module_name,
            src_path=src_path, work_dir=work_dir, timeout=timeout,
            source_code=code,
        )

        jobs[job_id]["algo_results"] = [algo_result]
        jobs[job_id]["progress"]     = 60

        jobs[job_id]["phase"]       = "refining"
        # FIX 10: Use effective timeout for the hybrid LLM refinement step too
        effective_llm_timeout = _resolve_timeout(hybrid_llm, timeout)
        jobs[job_id]["phase_label"] = (
            f"Refining with {hybrid_llm}… [timeout: {effective_llm_timeout}s]"
        )

        refinement = _refine_tests_with_llm(
            algo_results=[algo_result],
            source_code=code,
            module_name=module_name,
            ollama_url=ollama_url,
            model=hybrid_llm,
            timeout=effective_llm_timeout,
        )
        jobs[job_id]["progress"]   = 90
        jobs[job_id]["refinement"] = refinement

        saved_files = []

        if algo_result["status"] == "success" and algo_result["test_code"]:
            fname    = f"test_{module_name}_{hybrid_algo.lower()}_raw.py"
            out_path = os.path.join(TESTS_FOLDER, fname)
            with open(out_path, "w") as f:
                f.write(algo_result["test_code"])
            algo_result["saved_path"] = out_path
            saved_files.append((out_path, fname))

        if refinement["status"] == "success" and refinement["refined_code"]:
            refined_fname    = f"test_{module_name}_{hybrid_algo.lower()}_refined.py"
            refined_out_path = os.path.join(TESTS_FOLDER, refined_fname)
            with open(refined_out_path, "w") as f:
                f.write(refinement["refined_code"])
            refinement["saved_path"] = refined_out_path
            saved_files.append((refined_out_path, refined_fname))

        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for abs_path, arc_name in saved_files:
                if os.path.exists(abs_path):
                    zout.write(abs_path, arc_name)

        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["progress"]     = 100
        jobs[job_id]["status"]       = "completed"
        jobs[job_id]["phase"]        = "done"
        jobs[job_id]["phase_label"]  = "Complete"
        jobs[job_id]["message"] = (
            f"Hybrid: {hybrid_algo} algo + {hybrid_llm} refinement. "
            + ("Refined." if refinement["status"] == "success" else "Refinement failed.")
        )

        jobs[job_id]["results"] = [
            {
                "file":           f"test_{module_name}_{hybrid_algo.lower()}_raw.py",
                "algorithm":      algo_result["algorithm"],
                "model":          None,
                "status":         algo_result["status"],
                "content":        algo_result["test_code"],
                "num_tests":      algo_result["num_tests"],
                "coverage":       algo_result["coverage"],
                "mutation_score": algo_result["mutation_score"],
                "error":          algo_result["error"],
                "metrics": {
                    "coverage_percent": round(algo_result["coverage"] * 100, 2),
                    "mutation_score":   round(algo_result["mutation_score"], 4),
                },
            }
        ]

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# Codebase (ZIP) pipeline helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_file_context(target_file: str, all_files: list) -> str:
    context = []
    for fp in all_files:
        if fp == target_file: continue
        try:
            with open(fp, "r", encoding="utf-8") as f: content = f.read()
            tree = ast.parse(content); rel = os.path.basename(fp)
            summary = [f"# File: {rel}"]
            doc = ast.get_docstring(tree)
            if doc: summary.append(f'"""{doc}"""')
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                    args = [a.arg for a in node.args.args]
                    line = f"def {node.name}({', '.join(args)}):"
                    fn_doc = ast.get_docstring(node)
                    if fn_doc: line += f"  # {fn_doc.splitlines()[0]}"
                    summary.append(line)
                elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    summary.append(f"class {node.name}:")
                    cls_doc = ast.get_docstring(node)
                    if cls_doc: summary.append(f'    """{cls_doc.splitlines()[0]}"""')
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            m_args = [a.arg for a in item.args.args]
                            m_line = f"    def {item.name}({', '.join(m_args)}):"
                            m_doc  = ast.get_docstring(item)
                            if m_doc: m_line += f"  # {m_doc.splitlines()[0]}"
                            summary.append(m_line)
            if len(summary) > 1: context.append("\n".join(summary))
        except Exception: pass
    return "\n\n".join(context)


def _process_one_file(
    job_id, code, module_name, file_path, ollama_url, model, timeout,
    context="", strategy="auto", force_ensemble=False,
) -> dict:
    jobs[job_id]["current_file"] = f"{module_name}.py"
    work_dir = tempfile.mkdtemp(prefix="codexter_")
    entry: Dict[str, Any] = {"file": f"{module_name}.py", "status": "pending"}
    try:
        src_path = os.path.join(work_dir, f"{module_name}.py")
        with open(src_path, "w") as f: f.write(code)
        open(os.path.join(work_dir, "__init__.py"), "w").close()

        prompt_code = f"{code}\n\n# Context from other project files:\n{context}" if context else code

        file_strategy = strategy
        if strategy == "auto" and not force_ensemble:
            selected_strategy, strategy_details = select_test_strategy(code, file_path)
            file_strategy = selected_strategy.value
            entry["strategy_details"] = {
                "selected": file_strategy,
                "confidence": strategy_details.get("confidence", 0),
                "complexity_score": strategy_details.get("metrics", {}).get("overall_score", 0),
            }

        tests = None; generation_method = "unknown"
        run_ensemble = force_ensemble or (file_strategy == "ensemble" and config.get("enable_ensemble", False))
        if run_ensemble:
            try:
                ensemble_result = generate_ensemble_tests(prompt_code)
                tests = ensemble_result.final_test_code; generation_method = "ensemble"
                entry["ensemble_details"] = {
                    "models_used": [m.value for m in ensemble_result.models_used],
                    "best_model": ensemble_result.best_model.value,
                    "quality_score": ensemble_result.quality_score,
                }
            except Exception as e:
                print(f"  [WARNING] Ensemble failed for {module_name}.py: {e}")

        if not tests:
            generation_method = "single_model"
            # FIX 11: Pass effective timeout so codellama gets its minimum
            effective_timeout = _resolve_timeout(model, timeout)
            tests = generate_tests_ollama(
                code=code, module_name=module_name, context=context,
                ollama_url=ollama_url, model=model, timeout=effective_timeout)

        if not tests or not tests.strip():
            tests = fallback_simple_tests(code, module_name)
            generation_method = "fallback"; entry["is_fallback"] = True

        try:
            ast.parse(tests)
        except SyntaxError:
            tests = _clean_code(tests)
            try:
                ast.parse(tests)
            except SyntaxError:
                tests = fallback_simple_tests(code, module_name)
                generation_method = "fallback"; entry["is_fallback"] = True

        out_name = f"test_{module_name}.py"
        out_path = os.path.join(TESTS_FOLDER, out_name)
        with open(out_path, "w") as tf: tf.write(tests)
        test_path = os.path.join(work_dir, out_name)
        with open(test_path, "w") as tf: tf.write(tests)

        entry["status"]            = "success"
        entry["test_file"]         = out_name
        entry["full_path"]         = out_path
        entry["content"]           = tests
        entry["generation_method"] = generation_method

        try:
            cov, _ = calculate_coverage(src_path, test_path, work_dir)
            mut, _ = calculate_mutation_score(module_name, test_path, work_dir)
            entry["coverage"] = cov; entry["mutation_score"] = mut
            entry["metrics"] = {"coverage_percent": round(cov * 100, 2),
                                "mutation_score": round(mut, 4), "has_errors": False}
        except Exception:
            entry["coverage"] = 0.0; entry["mutation_score"] = 0.0
            entry["metrics"] = {"coverage_percent": 0.0, "mutation_score": 0.0, "has_errors": True}

        if config.get("enable_quality_analysis", True):
            try:
                quality = analyze_test_quality(tests, code)
                entry["quality_analysis"] = {
                    "overall_score": quality.overall_score,
                    "smells_count": len(quality.smells_detected),
                    "scores": {
                        "assertion_quality": quality.assertion_quality,
                        "edge_case_coverage": quality.edge_case_coverage,
                        "naming_quality": quality.naming_quality,
                        "documentation_quality": quality.documentation_quality,
                        "maintainability": quality.maintainability,
                    },
                    "strengths": quality.strengths,
                    "improvements": quality.improvements,
                }
            except Exception as e:
                print(f"  [WARNING] Quality analysis failed: {e}")

    except SyntaxError as e:
        entry["status"] = "failed"; entry["error"] = f"LLM returned invalid Python: {e}"
    except Exception as e:
        entry["status"] = "failed"; entry["error"] = str(e)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return entry


def process_multiple_job(job_id, files, ollama_url, model, timeout):
    jobs[job_id]["status"] = "processing"; jobs[job_id]["progress"] = 0
    jobs[job_id]["results"] = []; jobs[job_id]["total_files"] = len(files)
    all_real_paths = [f["file_path"] for f in files if os.path.isfile(f.get("file_path", ""))]
    project_context = ProjectContext(all_real_paths) if all_real_paths else None
    try:
        for i, file_info in enumerate(files):
            code = file_info["code"]; module_name = file_info["module_name"]
            file_path = file_info.get("file_path", "")
            context = (project_context.get_context_for_file(file_path) if project_context else "")
            entry = _process_one_file(
                job_id=job_id, code=code, module_name=module_name, file_path=file_path,
                ollama_url=ollama_url, model=model, timeout=timeout, context=context,
                strategy=config.get("default_strategy", "auto"))
            jobs[job_id]["results"].append(entry)
            jobs[job_id]["progress"] = int(((i + 1) / len(files)) * 100)
        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for r in jobs[job_id]["results"]:
                if r["status"] == "success" and "full_path" in r:
                    zout.write(r["full_path"], r["test_file"])
        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["status"] = "completed"; jobs[job_id]["message"] = "All files processed"
    except Exception as e:
        jobs[job_id]["status"] = "error"; jobs[job_id]["error"] = str(e)
        print(traceback.format_exc())


def process_zip_job(job_id, zip_path, extract_path, model, ollama_url, timeout, analysis_mode="single"):
    jobs[job_id]["status"] = "processing"; jobs[job_id]["progress"] = 0; jobs[job_id]["results"] = []
    use_ensemble = (analysis_mode == "ensemble")
    job_strategy = "ensemble" if use_ensemble else "standard"
    try:
        with zipfile.ZipFile(zip_path, "r") as z: z.extractall(extract_path)
        python_files = [
            os.path.join(root, f)
            for root, _, files in os.walk(extract_path)
            for f in files
            if f.endswith(".py") and not f.startswith("test_")]
        total = len(python_files); jobs[job_id]["total_files"] = total
        if total == 0:
            jobs[job_id]["status"] = "completed"; jobs[job_id]["message"] = "No Python files found."; return
        project_context = ProjectContext(python_files)
        max_workers = config.get("max_concurrency", 3); completed_count = 0

        def _process_zip_file(py_file):
            module_name = os.path.splitext(os.path.basename(py_file))[0]
            with open(py_file, "r", encoding="utf-8") as f: code = f.read()
            context = project_context.get_context_for_file(py_file)
            return _process_one_file(
                job_id=job_id, code=code, module_name=module_name, file_path=py_file,
                ollama_url=ollama_url, model=model, timeout=timeout, context=context,
                strategy=job_strategy, force_ensemble=use_ensemble)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            fmap = {executor.submit(_process_zip_file, p): p for p in python_files}
            for future in as_completed(fmap):
                jobs[job_id]["results"].append(future.result())
                completed_count += 1
                jobs[job_id]["progress"] = int((completed_count / total) * 100)

        results_zip = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
        with zipfile.ZipFile(results_zip, "w") as zout:
            for r in jobs[job_id]["results"]:
                if r["status"] == "success" and "full_path" in r:
                    zout.write(r["full_path"], r["test_file"])
        jobs[job_id]["download_url"] = f"/download_tests/{job_id}"
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["message"] = f"Analysis complete ({analysis_mode} mode)"
    except Exception as e:
        jobs[job_id]["status"] = "error"; jobs[job_id]["error"] = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# Code Quality Metrics
# ══════════════════════════════════════════════════════════════════════════════

def _pep8_count(code: str) -> int:
    if not _PYCODESTYLE_OK:
        return 0
    try:
        import tempfile as _tmp
        with _tmp.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code); fname = f.name
        result = subprocess.run(
            [sys.executable, "-m", "pycodestyle", "--statistics", "-q", fname],
            capture_output=True, text=True, timeout=10)
        os.unlink(fname)
        total = 0
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts and parts[0].isdigit():
                total += int(parts[0])
        return total
    except Exception:
        return 0


def _cyclomatic_complexity_score(code: str) -> float:
    if _RADON_OK:
        try:
            results = cc_visit(code)
            if results:
                return round(sum(r.complexity for r in results) / len(results), 2)
            return 1.0
        except Exception:
            pass
    kw = ["if ", "elif ", "for ", "while ", "except ", "and ", "or "]
    count = sum(code.count(k) for k in kw)
    lines = [l for l in code.splitlines() if l.strip()]
    return round(1 + count / max(len(lines), 1) * 10, 2)


def _halstead_difficulty_score(code: str) -> float:
    if _RADON_OK:
        try:
            result = h_visit(code)
            if result:
                return round(result[0].difficulty, 2)
        except Exception:
            pass
    try:
        tree = ast.parse(code)
        operators, operands = 0, 0
        uo: Set[str] = set(); ud: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                                  ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq,
                                  ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                                  ast.Is, ast.IsNot, ast.In, ast.NotIn)):
                operators += 1; uo.add(type(node).__name__)
            if isinstance(node, ast.Name):
                operands += 1; ud.add(node.id)
            elif isinstance(node, ast.Constant):
                operands += 1
        if ud:
            return round((len(uo) / 2.0) * (operands / len(ud)), 2)
    except Exception:
        pass
    return 0.0


def _loc_score(code: str) -> int:
    return sum(1 for l in code.splitlines()
               if l.strip() and not l.strip().startswith("#"))


def compute_code_metrics(code: str) -> dict:
    return {
        "loc":        _loc_score(code),
        "cyclomatic": _cyclomatic_complexity_score(code),
        "halstead":   _halstead_difficulty_score(code),
        "pep8":       _pep8_count(code),
    }


def metrics_delta(before: dict, after: dict) -> dict:
    return {
        "loc_delta":        before["loc"]        - after["loc"],
        "cyclomatic_delta": before["cyclomatic"] - after["cyclomatic"],
        "halstead_delta":   before["halstead"]   - after["halstead"],
        "pep8_delta":       before["pep8"]       - after["pep8"],
    }


def unified_diff_str(original: str, refactored: str, filename: str = "code.py") -> str:
    orig = original.splitlines(keepends=True)
    new  = refactored.splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        orig, new,
        fromfile=f"original/{filename}",
        tofile=f"refactored/{filename}",
        lineterm="",
    ))


def compute_reward(before: dict, after: dict) -> float:
    total = 0.0
    for key, weight in REWARD_WEIGHTS.items():
        bv = before[key]; av = after[key]
        if bv == 0:
            comp = 0.0 if av == 0 else -1.0
        else:
            ratio = bv / max(av, 0.01)
            comp  = max(-1.0, min(1.0, ratio - 1.0))
        total += weight * comp
    return round(total, 4)


# ══════════════════════════════════════════════════════════════════════════════
# Multi-model refactor pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _refactor_one_model(
    code: str, module_name: str, model: str,
    ollama_url: str, timeout: int, before: dict,
) -> dict:
    result = {
        "model": model, "status": "pending",
        "refactored_code": None, "summary": None,
        "before": before, "after": None, "delta": None,
        "reward": None, "diff": None, "error": None, "elapsed": 0.0,
    }
    t0 = time.time()

    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            available = [m["name"] for m in r.json().get("models", [])]
            if not any(model == m or m.startswith(model.split(":")[0]) for m in available):
                result["status"] = "error"
                result["error"] = f"Model '{model}' not found in Ollama. Run: ollama pull {model}"
                result["elapsed"] = round(time.time() - t0, 2)
                return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Availability check failed: {type(e).__name__}: {e}"
        result["elapsed"] = round(time.time() - t0, 2)
        return result

    try:
        refactored, summary = refactor_code_ollama(
            code=code, module_name=module_name,
            ollama_url=ollama_url, model=model, timeout=timeout,
        )
        elapsed = round(time.time() - t0, 2)
        after   = compute_code_metrics(refactored)
        result.update({
            "status":          "success",
            "refactored_code": refactored,
            "summary":         summary,
            "after":           after,
            "delta":           metrics_delta(before, after),
            "reward":          compute_reward(before, after),
            "diff":            unified_diff_str(code, refactored, f"{module_name}.py"),
            "elapsed":         elapsed,
        })
    except Exception as e:
        result["status"]  = "error"
        result["error"]   = f"{type(e).__name__}: {e}"
        result["elapsed"] = round(time.time() - t0, 2)

    return result


def process_multimodel_refactor(
    job_id: str, code: str, module_name: str,
    ollama_url: str, timeout: int,
):
    jobs[job_id].update({
        "status": "processing", "progress": 0,
        "phase": "running", "phase_label": "Running models one at a time…",
    })
    before = compute_code_metrics(code)
    jobs[job_id]["before_metrics"] = before
    model_results: List[dict] = []

    try:
        for i, model in enumerate(REFACTOR_MODELS):
            jobs[job_id]["phase_label"] = f"Running {model} ({i+1}/{len(REFACTOR_MODELS)})…"
            jobs[job_id]["progress"] = int(i / len(REFACTOR_MODELS) * 100)
            result = _refactor_one_model(code, module_name, model, ollama_url, timeout, before)
            model_results.append(result)
            jobs[job_id]["progress"] = int((i + 1) / len(REFACTOR_MODELS) * 100)
            jobs[job_id]["partial_results"] = model_results[:]

        model_results.sort(key=lambda r: r.get("reward") or -99, reverse=True)
        best = model_results[0]["model"] if model_results else None
        jobs[job_id].update({
            "status":     "completed", "progress": 100,
            "phase":      "done",      "phase_label": "Complete",
            "results":    model_results,
            "best_model": best,
            "message":    f"3 models complete. Best: {best}",
        })
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# Simulated-PPO refactor pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _ppo_feedback_prompt(
    original: str, current: str, module_name: str,
    iteration: int, reward: float, delta: dict,
    ollama_url: str, model: str, timeout: int,
) -> Tuple[str, str]:
    fb = []
    if delta["cyclomatic_delta"] <= 0:
        fb.append("- Cyclomatic complexity DID NOT improve. Simplify branches and nested conditionals.")
    else:
        fb.append(f"- Cyclomatic complexity improved by {delta['cyclomatic_delta']:.2f}. Preserve this.")
    if delta["pep8_delta"] <= 0:
        fb.append("- PEP8 violations DID NOT improve. Fix spacing, naming, and line length.")
    else:
        fb.append(f"- PEP8 violations reduced by {delta['pep8_delta']}. Preserve this.")
    if delta["halstead_delta"] <= 0:
        fb.append("- Halstead difficulty DID NOT improve. Reduce operator and operand variety.")
    else:
        fb.append(f"- Halstead difficulty improved by {delta['halstead_delta']:.2f}. Preserve this.")
    if delta["loc_delta"] < 0:
        fb.append("- Lines of code INCREASED. Remove verbosity and dead code.")
    elif delta["loc_delta"] > 0:
        fb.append(f"- Lines of code reduced by {delta['loc_delta']}. Good.")

    reward_pct = int((reward + 1) / 2 * 100)
    prompt = f"""You are an AI code quality optimizer — iteration {iteration} of a feedback-driven loop.
Current reward score: {reward_pct}/100 (higher = better).

Feedback on previous refactoring:
{chr(10).join(fb)}

Refactor the module again, specifically addressing areas that did NOT improve.
Do not regress on areas that did improve.

Original module ({module_name}):
```python
{original}
```

Previous version (iteration {iteration - 1}):
```python
{current}
```

Respond with exactly:

REFACTORED_CODE:
```python
<complete improved module>
```

SUMMARY:
<brief bullet list of changes in this iteration>"""

    try:
        raw = call_ollama(prompt, ollama_url, model, timeout)
        return _parse_refactor_response(raw, current)
    except Exception as e:
        return current, f"Iteration {iteration} failed: {e}"


def process_ppo_refactor(
    job_id: str, code: str, module_name: str,
    ollama_url: str, model: str, timeout: int,
    max_iterations: int = PPO_MAX_ITERATIONS,
):
    jobs[job_id].update({
        "status": "processing", "progress": 0,
        "phase": "ppo", "phase_label": "Starting iterative refactor loop…",
        "iterations": [],
    })
    before      = compute_code_metrics(code)
    current     = code
    best_code   = code
    best_reward = -99.0
    log: List[dict] = []
    jobs[job_id]["before_metrics"] = before

    reward = 0.0
    delta  = {k: 0 for k in ("cyclomatic_delta", "pep8_delta", "halstead_delta", "loc_delta")}

    try:
        for i in range(1, max_iterations + 1):
            jobs[job_id]["phase_label"] = f"PPO iteration {i}/{max_iterations}…"
            jobs[job_id]["progress"]    = int((i - 1) / max_iterations * 90)

            if i == 1:
                try:
                    refactored, summary = refactor_code_ollama(
                        code=current, module_name=module_name,
                        ollama_url=ollama_url, model=model, timeout=timeout,
                    )
                except Exception as e:
                    refactored, summary = current, f"Initial refactor failed: {e}"
            else:
                refactored, summary = _ppo_feedback_prompt(
                    code, current, module_name, i,
                    reward, delta, ollama_url, model, timeout,
                )

            after  = compute_code_metrics(refactored)
            delta  = metrics_delta(before, after)
            reward = compute_reward(before, after)
            diff   = unified_diff_str(current, refactored, f"{module_name}.py")

            entry = {
                "iteration": i,
                "reward":    reward,
                "after":     after,
                "delta":     delta,
                "summary":   summary,
                "diff":      diff,
                "code":      refactored,
            }
            log.append(entry)
            jobs[job_id]["iterations"] = log[:]
            jobs[job_id]["progress"]   = int(i / max_iterations * 90)

            if reward > best_reward:
                best_reward = reward
                best_code   = refactored
            current = refactored

            if reward >= PPO_REWARD_THRESHOLD:
                jobs[job_id]["phase_label"] = (
                    f"Early stop at iteration {i} "
                    f"(reward {reward:.2f} ≥ {PPO_REWARD_THRESHOLD})"
                )
                break

        fa    = compute_code_metrics(best_code)
        fd    = metrics_delta(before, fa)
        fr    = compute_reward(before, fa)
        fdiff = unified_diff_str(code, best_code, f"{module_name}.py")

        jobs[job_id].update({
            "status":           "completed",
            "progress":         100,
            "phase":            "done",
            "phase_label":      "PPO complete",
            "best_code":        best_code,
            "best_reward":      best_reward,
            "final_after":      fa,
            "final_delta":      fd,
            "final_reward":     fr,
            "final_diff":       fdiff,
            "total_iterations": len(log),
            "message": (
                f"PPO complete — {len(log)} iteration(s), "
                f"best reward {best_reward:.3f}"
            ),
        })
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# AST Rule-Engine Refactor
# ══════════════════════════════════════════════════════════════════════════════

MAX_FUNC_LINES = 30

class _UnusedImportRemover(ast.NodeTransformer):
    def __init__(self, tree: ast.Module):
        self._used: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self._used.add(node.id)
            elif isinstance(node, ast.Attribute):
                self._used.add(node.attr)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self._used.add(node.value)

    def visit_Import(self, node: ast.Import) -> Optional[ast.Import]:
        kept = [alias for alias in node.names
                if (alias.asname or alias.name).split(".")[0] in self._used
                or alias.name.split(".")[0] in self._used]
        if not kept:
            return None
        node.names = kept
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Optional[ast.ImportFrom]:
        kept = [alias for alias in node.names
                if (alias.asname or alias.name) in self._used or alias.name == "*"]
        if not kept:
            return None
        node.names = kept
        return node


class _BoolSimplifier(ast.NodeTransformer):
    def visit_Compare(self, node: ast.Compare) -> ast.expr:
        if (len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
                and len(node.comparators) == 1):
            comp = node.comparators[0]
            if isinstance(comp, ast.Constant):
                if comp.value is True:
                    return self.generic_visit(node.left)
                if comp.value is False:
                    return ast.UnaryOp(op=ast.Not(), operand=self.generic_visit(node.left))
        return self.generic_visit(node)


class _BareExceptFixer(ast.NodeTransformer):
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.ExceptHandler:
        if node.type is None:
            node.type = ast.Name(id="Exception", ctx=ast.Load())
        return self.generic_visit(node)


def _add_module_docstring(tree: ast.Module, module_name: str) -> ast.Module:
    has_doc = (tree.body
               and isinstance(tree.body[0], ast.Expr)
               and isinstance(tree.body[0].value, ast.Constant)
               and isinstance(tree.body[0].value.value, str))
    if not has_doc:
        doc_node = ast.Expr(value=ast.Constant(value=f"Module: {module_name}."))
        tree.body.insert(0, doc_node)
    return tree


def _add_missing_type_hints(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.returns is None:
            if node.name != "__init__":
                node.returns = ast.Constant(value=None)
    return tree


def _report_long_functions(tree: ast.Module) -> List[str]:
    long_fns = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines = (node.end_lineno or node.lineno) - node.lineno
            if body_lines > MAX_FUNC_LINES:
                long_fns.append(f"{node.name} (~{body_lines} lines)")
    return long_fns


def _deduplicate_consecutive_stmts(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            new_body = []
            prev_src = None
            for stmt in node.body:
                try:
                    src = ast.unparse(stmt)
                except Exception:
                    src = None
                if src is not None and src == prev_src:
                    continue
                new_body.append(stmt)
                prev_src = src
            node.body = new_body
    return tree


def apply_ast_rules(code: str, module_name: str) -> Tuple[str, List[str]]:
    changes: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return code, [f"SyntaxError — cannot parse: {exc}"]

    original_has_doc = (tree.body
                        and isinstance(tree.body[0], ast.Expr)
                        and isinstance(tree.body[0].value, ast.Constant))
    tree = _add_module_docstring(tree, module_name)
    if not original_has_doc:
        changes.append("R8: Added module-level docstring")

    before_imports = sum(1 for n in tree.body
                         if isinstance(n, (ast.Import, ast.ImportFrom)))
    tree = _UnusedImportRemover(tree).visit(tree)
    after_imports = sum(1 for n in tree.body
                        if isinstance(n, (ast.Import, ast.ImportFrom)))
    removed = before_imports - after_imports
    if removed:
        changes.append(f"R2: Removed {removed} unused import statement(s)")

    tree = _BoolSimplifier().visit(tree)
    changes.append("R7: Simplified boolean comparisons (x==True → x)")

    tree = _BareExceptFixer().visit(tree)
    changes.append("R4: Replaced bare except: with except Exception:")

    tree = _deduplicate_consecutive_stmts(tree)
    changes.append("R6: Removed consecutive duplicate statements")

    tree = _add_missing_type_hints(tree)
    changes.append("R5: Added missing -> None return annotations")

    long_fns = _report_long_functions(tree)
    if long_fns:
        changes.append(
            f"R1 (advisory): Functions exceeding {MAX_FUNC_LINES} lines "
            f"(consider extracting): {', '.join(long_fns)}"
        )

    ast.fix_missing_locations(tree)
    try:
        refactored = ast.unparse(tree)
        try:
            import black
            mode = black.Mode(line_length=88)
            refactored = black.format_str(refactored, mode=mode)
            changes.append("Formatted with black (line-length 88)")
        except Exception:
            pass
    except Exception as exc:
        return code, [f"Unparse failed: {exc}"]

    return refactored, changes


def process_ast_refactor(
    job_id: str, code: str, module_name: str,
    ollama_url: str, timeout: int,
) -> None:
    jobs[job_id].update({
        "status": "processing", "progress": 0,
        "phase": "ast", "phase_label": "Applying AST rule passes…",
    })
    before = compute_code_metrics(code)
    jobs[job_id]["before_metrics"] = before

    try:
        jobs[job_id]["progress"] = 20
        jobs[job_id]["phase_label"] = "Running R2/R4/R5/R6/R7/R8 passes…"

        refactored, changes = apply_ast_rules(code, module_name)

        jobs[job_id]["progress"] = 70
        jobs[job_id]["phase_label"] = "Computing metrics…"

        after  = compute_code_metrics(refactored)
        delta  = metrics_delta(before, after)
        reward = compute_reward(before, after)
        diff   = unified_diff_str(code, refactored, f"{module_name}.py")

        jobs[job_id].update({
            "status":          "completed",
            "progress":        100,
            "phase":           "done",
            "phase_label":     "AST refactor complete",
            "refactored_code": refactored,
            "summary":        "\n".join(f"• {c}" for c in changes) if changes else "No changes applied.",
            "before":         before,
            "after":          after,
            "delta":          delta,
            "reward":         reward,
            "diff":           diff,
            "changes":        changes,
            "message":        f"AST rules applied — {len(changes)} change(s), reward {reward:.3f}",
        })
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# Simulated Annealing Refactor
# ══════════════════════════════════════════════════════════════════════════════

import math as _math
import random as _random

SA_MAX_ITERATIONS    = 8
SA_INITIAL_TEMP      = 1.0
SA_COOLING_RATE      = 0.75
SA_MIN_TEMP          = 0.05
SA_REWARD_THRESHOLD  = 0.65


def _sa_action_pep8_fix(code: str) -> str:
    try:
        import autopep8  # type: ignore
        return autopep8.fix_code(code, options={"max_line_length": 99, "aggressive": 1})
    except ImportError:
        pass
    lines, blanks = [], 0
    for line in code.splitlines():
        stripped = line.rstrip()
        if stripped == "":
            blanks += 1
            if blanks <= 2:
                lines.append(stripped)
        else:
            blanks = 0
            lines.append(stripped)
    return "\n".join(lines)


def _sa_action_sort_imports(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    import_nodes: List[Tuple[int, ast.stmt]] = []
    other_nodes:  List[Tuple[int, ast.stmt]] = []

    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_nodes.append((i, node))
        else:
            other_nodes.append((i, node))

    if not import_nodes:
        return code

    def _import_key(node: ast.stmt) -> Tuple[int, str]:
        import sys as _sys
        stdlib = set(_sys.stdlib_module_names) if hasattr(_sys, "stdlib_module_names") else set()
        if isinstance(node, ast.Import):
            name = node.names[0].name.split(".")[0]
        else:
            name = (node.module or "").split(".")[0]
        tier = 0 if name in stdlib else 1
        return (tier, name)

    sorted_imports = sorted([n for _, n in import_nodes], key=_import_key)

    non_import_positions = [i for i, _ in other_nodes]
    min_non_import = min(non_import_positions) if non_import_positions else len(tree.body)
    if any(i < min_non_import for i, _ in import_nodes):
        new_body = sorted_imports + [n for _, n in other_nodes]
        tree.body = new_body
        try:
            return ast.unparse(tree)
        except Exception:
            return code
    return code


def _sa_action_remove_excess_blanks(code: str) -> str:
    lines, blanks = [], 0
    for line in code.splitlines():
        if line.strip() == "":
            blanks += 1
            if blanks <= 2:
                lines.append("")
        else:
            blanks = 0
            lines.append(line)
    return "\n".join(lines)


# AFTER — remove ast_rules from the static list entirely
SA_ACTIONS = [
    ("pep8_fix",      _sa_action_pep8_fix),
    ("sort_imports",  _sa_action_sort_imports),
    ("remove_blanks", _sa_action_remove_excess_blanks),
]


def process_sa_refactor(
    job_id: str, code: str, module_name: str,
    ollama_url: str, model: str, timeout: int,
    max_iterations: int = SA_MAX_ITERATIONS,
):
    jobs[job_id].update({
        "status": "processing", "progress": 0,
        "phase": "sa", "phase_label": "Starting SA loop…",
        "iterations": [],
    })

    before       = compute_code_metrics(code)
    jobs[job_id]["before_metrics"] = before

    current      = code
    current_reward = compute_reward(before, compute_code_metrics(current))
    best_code    = code
    best_reward  = current_reward
    temperature  = SA_INITIAL_TEMP
    log: List[dict] = []

    # ── FIX: build actions locally so ast_rules can close over module_name ──
    local_actions = SA_ACTIONS + [
        ("ast_rules", lambda c: apply_ast_rules(c, module_name)[0]),
    ]

    try:
        for i in range(1, max_iterations + 1):
            jobs[job_id]["phase_label"] = (
                f"SA iteration {i}/{max_iterations}  T={temperature:.3f}…"
            )
            jobs[job_id]["progress"] = int((i - 1) / max_iterations * 90)

            if temperature > 0.4 and i == 1:
                try:
                    llm_candidate, _ = refactor_code_ollama(
                        current, module_name, ollama_url, model, timeout
                    )
                    action_name = "llm_refactor"
                    candidate   = llm_candidate
                except Exception:
                    action_name, fn = _random.choice(local_actions)
                    candidate = fn(current)
            else:
                action_name, fn = _random.choice(local_actions)
                candidate = fn(current)

            try:
                ast.parse(candidate)
            except SyntaxError:
                log.append({
                    "iteration": i, "action": action_name,
                    "reward": current_reward, "delta": {},
                    "accepted": False, "reason": "syntax error in candidate",
                    "temperature": round(temperature, 4),
                })
                jobs[job_id]["iterations"] = log[:]
                temperature = max(SA_MIN_TEMP, temperature * SA_COOLING_RATE)
                continue

            after_m      = compute_code_metrics(candidate)
            new_reward   = compute_reward(before, after_m)
            delta        = metrics_delta(before, after_m)
            reward_delta = new_reward - current_reward

            if reward_delta > 0:
                accepted = True
                reason   = "improvement"
            else:
                prob     = _math.exp(reward_delta / max(temperature, 1e-9))
                accepted = _random.random() < prob
                reason   = f"accepted worse (p={prob:.3f})" if accepted else "rejected"

            if accepted:
                current        = candidate
                current_reward = new_reward

            if new_reward > best_reward:
                best_reward = new_reward
                best_code   = candidate

            entry = {
                "iteration":   i,
                "action":      action_name,
                "reward":      round(new_reward, 4),
                "delta":       delta,
                "accepted":    accepted,
                "reason":      reason,
                "temperature": round(temperature, 4),
                "code":        candidate if accepted else None,
            }
            log.append(entry)
            jobs[job_id]["iterations"] = log[:]

            temperature = max(SA_MIN_TEMP, temperature * SA_COOLING_RATE)

            if best_reward >= SA_REWARD_THRESHOLD:
                jobs[job_id]["phase_label"] = (
                    f"Early stop at iter {i} (reward {best_reward:.3f} ≥ {SA_REWARD_THRESHOLD})"
                )
                break

        fa    = compute_code_metrics(best_code)
        fd    = metrics_delta(before, fa)
        fr    = compute_reward(before, fa)
        fdiff = unified_diff_str(code, best_code, f"{module_name}.py")

        jobs[job_id].update({
            "status":           "completed",
            "progress":         100,
            "phase":            "done",
            "phase_label":      "SA refactor complete",
            "best_code":        best_code,
            "best_reward":      best_reward,
            "final_after":      fa,
            "final_delta":      fd,
            "final_reward":     fr,
            "final_diff":       fdiff,
            "total_iterations": len(log),
            "message": (
                f"SA complete — {len(log)} iteration(s), "
                f"best reward {best_reward:.3f}, "
                f"final T={temperature:.4f}"
            ),
        })

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# RAG-based Refactor
# ══════════════════════════════════════════════════════════════════════════════

RAG_TOP_K = 4

_RAG_CORPUS: List[Dict[str, str]] = [
    {
        "title": "Use enumerate instead of range(len(...))",
        "before": "for i in range(len(items)):\n    print(i, items[i])",
        "after":  "for i, item in enumerate(items):\n    print(i, item)",
        "tags":   "loop enumerate range",
    },
    {
        "title": "Use list comprehension instead of for-loop append",
        "before": "result = []\nfor x in data:\n    result.append(x * 2)",
        "after":  "result = [x * 2 for x in data]",
        "tags":   "list comprehension loop",
    },
    {
        "title": "Use dict.get() with default instead of key-in-dict check",
        "before": "if key in d:\n    val = d[key]\nelse:\n    val = default",
        "after":  "val = d.get(key, default)",
        "tags":   "dict get default key",
    },
    {
        "title": "Add type hints to function signature",
        "before": "def add(a, b):\n    return a + b",
        "after":  "def add(a: int | float, b: int | float) -> int | float:\n    return a + b",
        "tags":   "type hints annotation",
    },
    {
        "title": "Replace mutable default argument with None sentinel",
        "before": "def func(items=[]):\n    items.append(1)\n    return items",
        "after":  "def func(items=None):\n    if items is None:\n        items = []\n    items.append(1)\n    return items",
        "tags":   "mutable default argument function",
    },
    {
        "title": "Use f-string instead of % or .format()",
        "before": "msg = 'Hello, %s! You are %d years old.' % (name, age)",
        "after":  "msg = f'Hello, {name}! You are {age} years old.'",
        "tags":   "fstring format string",
    },
]


def _tfidf_vectorize(texts: List[str]) -> Tuple[List[dict], set]:
    import math as _m
    tokenize = lambda t: re.findall(r"[a-z_][a-z0-9_]*", t.lower())
    corpus_tokens = [tokenize(t) for t in texts]
    df: dict = {}
    for tokens in corpus_tokens:
        for term in set(tokens):
            df[term] = df.get(term, 0) + 1
    N = len(texts)
    idf = {term: _m.log((N + 1) / (cnt + 1)) + 1 for term, cnt in df.items()}
    vectors = []
    for tokens in corpus_tokens:
        tf: dict = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        total = max(len(tokens), 1)
        vec = {t: (c / total) * idf.get(t, 1) for t, c in tf.items()}
        vectors.append(vec)
    vocab = set(df.keys())
    return vectors, vocab


def _cosine_sim(a: dict, b: dict) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot  = sum(a[k] * b[k] for k in common)
    na   = _math.sqrt(sum(v * v for v in a.values()))
    nb   = _math.sqrt(sum(v * v for v in b.values()))
    denom = na * nb
    return dot / denom if denom > 0 else 0.0


def retrieve_similar_patterns(code: str, top_k: int = RAG_TOP_K) -> List[Dict[str, str]]:
    corpus_texts = [
        f"{e['title']} {e['tags']} {e['before']} {e['after']}"
        for e in _RAG_CORPUS
    ]
    all_texts   = corpus_texts + [code]
    vectors, _  = _tfidf_vectorize(all_texts)
    query_vec   = vectors[-1]
    corpus_vecs = vectors[:-1]

    scored = [
        (i, _cosine_sim(query_vec, cv))
        for i, cv in enumerate(corpus_vecs)
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [_RAG_CORPUS[i] for i, _ in scored[:top_k]]


def _build_rag_prompt(
    code: str, module_name: str, retrieved: List[Dict[str, str]]
) -> str:
    examples_block = ""
    for idx, ex in enumerate(retrieved, 1):
        examples_block += (
            f"\n--- Example {idx}: {ex['title']} ---\n"
            f"Before:\n```python\n{ex['before']}\n```\n"
            f"After:\n```python\n{ex['after']}\n```\n"
        )

    return f"""You are an expert Python software engineer. Refactor the following module using the
idiomatic patterns shown in the examples below where applicable.

RETRIEVED IDIOMATIC PATTERNS (apply these where relevant):
{examples_block}

MODULE TO REFACTOR ({module_name}):
```python
{code}
```

Instructions:
1. Apply the retrieved patterns where they genuinely improve the code
2. Also fix any other readability, PEP 8, or structural issues you find
3. Add type hints and docstrings where missing
4. Do NOT change the public API (function names, signatures, return types)

Respond in exactly two sections:

REFACTORED_CODE:
```python
<complete refactored module>
```

SUMMARY:
<bullet list — for each retrieved pattern applied, say which one and where>"""


def process_rag_refactor(
    job_id: str, code: str, module_name: str,
    ollama_url: str, model: str, timeout: int,
):
    jobs[job_id].update({
        "status": "processing", "progress": 0,
        "phase": "rag", "phase_label": "Building retrieval index…",
    })
    before = compute_code_metrics(code)
    jobs[job_id]["before_metrics"] = before

    try:
        jobs[job_id]["phase_label"] = "Retrieving similar patterns…"
        jobs[job_id]["progress"]    = 15
        retrieved = retrieve_similar_patterns(code, top_k=RAG_TOP_K)
        jobs[job_id]["retrieved_patterns"] = [p["title"] for p in retrieved]

        jobs[job_id]["phase_label"] = f"Generating with {len(retrieved)} retrieved patterns…"
        jobs[job_id]["progress"]    = 35
        prompt    = _build_rag_prompt(code, module_name, retrieved)
        raw       = call_ollama(prompt, ollama_url, model, timeout)
        refactored, summary = _parse_refactor_response(raw, code)

        jobs[job_id]["phase_label"] = "Computing metrics…"
        jobs[job_id]["progress"]    = 80
        after  = compute_code_metrics(refactored)
        delta  = metrics_delta(before, after)
        reward = compute_reward(before, after)
        diff   = unified_diff_str(code, refactored, f"{module_name}.py")

        jobs[job_id].update({
            "status":              "completed",
            "progress":            100,
            "phase":               "done",
            "phase_label":         "RAG refactor complete",
            "refactored_code":     refactored,
            "summary":             summary,
            "retrieved_patterns":  [p["title"] for p in retrieved],
            "before":              before,
            "after":               after,
            "delta":               delta,
            "reward":              reward,
            "diff":                diff,
            "message": (
                f"RAG complete — {len(retrieved)} patterns retrieved, "
                f"reward {reward:.3f}"
            ),
        })

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        print(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/generate-tests")
async def generate_tests_endpoint(req: SingleFileRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "filename": f"{req.module_name}.py", "scope": "single",
        "approach": req.approach,
    }

    if req.approach == "pynguin":
        threading.Thread(
            target=process_single_file_pynguin,
            args=(
                job_id, req.code, req.module_name, req.file_path,
                req.ollama_url, req.ollama_model, req.ollama_timeout,
                req.selected_algos,
            ),
            daemon=True,
        ).start()

    elif req.approach == "llm":
        threading.Thread(
            target=process_single_file_llm,
            args=(
                job_id, req.code, req.module_name, req.file_path,
                req.ollama_url, req.ollama_timeout,
                req.selected_models,
            ),
            daemon=True,
        ).start()

    else:
        threading.Thread(
            target=process_single_file_hybrid,
            args=(
                job_id, req.code, req.module_name, req.file_path,
                req.ollama_url, req.ollama_model, req.ollama_timeout,
                req.hybrid_algo, req.hybrid_llm,
            ),
            daemon=True,
        ).start()

    return {"message": "Job submitted", "job_id": job_id, "scope": "single"}


@app.post("/generate-tests-multiple")
async def generate_tests_multiple_endpoint(req: MultipleFileRequest):
    if not req.files:
        raise HTTPException(status_code=400, detail="No files provided")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "total_files": len(req.files), "scope": "multiple",
    }
    threading.Thread(
        target=process_multiple_job,
        args=(job_id, req.files, req.ollama_url, req.ollama_model, req.ollama_timeout),
        daemon=True,
    ).start()
    return {"message": "Job submitted", "job_id": job_id, "scope": "multiple"}


@app.post("/refactor-multimodel")
async def refactor_multimodel_endpoint(req: RefactorRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "filename": f"{req.module_name}.py", "scope": "multimodel_refactor",
    }
    threading.Thread(
        target=process_multimodel_refactor,
        args=(job_id, req.code, req.module_name, req.ollama_url, req.ollama_timeout),
        daemon=True,
    ).start()
    return {"job_id": job_id, "scope": "multimodel_refactor"}


@app.post("/refactor-ppo")
async def refactor_ppo_endpoint(req: RefactorRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "filename": f"{req.module_name}.py", "scope": "ppo_refactor",
    }
    threading.Thread(
        target=process_ppo_refactor,
        args=(
            job_id, req.code, req.module_name,
            req.ollama_url, req.ollama_model, req.ollama_timeout,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id, "scope": "ppo_refactor"}


@app.post("/refactor-ast")
async def refactor_ast_endpoint(req: RefactorRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "filename": f"{req.module_name}.py", "scope": "ast_refactor",
    }
    threading.Thread(
        target=process_ast_refactor,
        args=(job_id, req.code, req.module_name, req.ollama_url, req.ollama_timeout),
        daemon=True,
    ).start()
    return {"job_id": job_id, "scope": "ast_refactor"}


@app.post("/refactor-sa")
async def refactor_sa_endpoint(req: RefactorRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "filename": f"{req.module_name}.py", "scope": "sa_refactor",
    }
    threading.Thread(
        target=process_sa_refactor,
        args=(
            job_id, req.code, req.module_name,
            req.ollama_url, req.ollama_model, req.ollama_timeout,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id, "scope": "sa_refactor"}


@app.post("/refactor-rag")
async def refactor_rag_endpoint(req: RefactorRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(),
        "filename": f"{req.module_name}.py", "scope": "rag_refactor",
    }
    threading.Thread(
        target=process_rag_refactor,
        args=(
            job_id, req.code, req.module_name,
            req.ollama_url, req.ollama_model, req.ollama_timeout,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id, "scope": "rag_refactor"}


@app.post("/refactor", response_model=RefactorResponse)
async def refactor_endpoint(req: RefactorRequest):
    try:
        refactored, summary = refactor_code_ollama(
            code=req.code, module_name=req.module_name,
            ollama_url=req.ollama_url, model=req.ollama_model, timeout=req.ollama_timeout)
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
    file: UploadFile = File(...),
    ollama_model: str = "deepseek-coder:1.3b",
    ollama_url:   str = "http://localhost:11434",
    ollama_timeout: int = 120,
    analysis_mode:  str = "single",
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
    with open(zip_path, "wb") as f: f.write(contents)
    jobs[job_id] = {
        "status": "queued", "submitted_at": time.time(), "filename": file.filename,
        "scope": "zip", "analysis_mode": analysis_mode,
        "config": {"model": ollama_model, "timeout": ollama_timeout,
                   "strategy": config.get("default_strategy", "auto"),
                   "quality_analysis_enabled": config.get("enable_quality_analysis", True),
                   "analysis_mode": analysis_mode},
    }
    threading.Thread(
        target=process_zip_job,
        args=(job_id, zip_path, job_dir, ollama_model, ollama_url, ollama_timeout, analysis_mode),
        daemon=True,
    ).start()
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
    return FileResponse(zip_path, media_type="application/zip",
                        filename=f"generated_tests_{jobs[job_id].get('filename', job_id)}.zip")


@app.post("/analyze_strategy")
async def analyze_strategy(body: dict):
    code = body.get("code")
    if not code: raise HTTPException(status_code=400, detail="No code provided")
    try:
        strategy, details = select_test_strategy(code)
        return {"strategy": strategy.value, "confidence": details.get("confidence", 0),
                "metrics": details.get("metrics", {}), "reasoning": details.get("reasoning", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.post("/analyze_quality")
async def analyze_quality(body: dict):
    test_code = body.get("test_code")
    if not test_code: raise HTTPException(status_code=400, detail="No test_code provided")
    source_code = body.get("source_code")
    try:
        quality = analyze_test_quality(test_code, source_code)
        return {
            "overall_score": quality.overall_score,
            "scores": {"assertion_quality": quality.assertion_quality,
                       "edge_case_coverage": quality.edge_case_coverage,
                       "naming_quality": quality.naming_quality,
                       "documentation_quality": quality.documentation_quality,
                       "maintainability": quality.maintainability},
            "strengths": quality.strengths, "improvements": quality.improvements,
            "smells": [{"type": s.smell_type.value, "severity": s.severity,
                        "line": s.line_number, "message": s.message,
                        "suggestion": s.suggestion} for s in quality.smells_detected],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/config")
async def get_config():
    return config


@app.post("/config")
async def update_config(new_config: dict):
    global config
    try:
        config.update(new_config)
        with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=2)
        return {"message": "Configuration updated", "config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "Codexter", "version": "3.0.0"}


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


@app.get("/check-models")
async def check_models(ollama_url: str = "http://localhost:11434"):
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        available = [m["name"] for m in r.json().get("models", [])]
        status = {}
        for model in REFACTOR_MODELS:
            status[model] = any(
                model == m or m.startswith(model.split(":")[0])
                for m in available
            )
        return {"models": status, "available": available}
    except Exception as e:
        return {"error": str(e), "models": {m: False for m in REFACTOR_MODELS}}


if __name__ == "__main__":
    import uvicorn
    print("Starting Codexter API — http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)