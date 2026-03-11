"""
Test Quality Analyzer

Analyzes generated test code and provides quality scores.
Detects test smells, validates coverage, and suggests improvements.
High cyclomatic complexity through multiple analysis heuristics.
"""

import ast
import re
from typing import Dict, Any, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class TestSmell(Enum):
    """Common test smells to detect"""
    MAGIC_NUMBER = "magic_number"
    UNCLEAR_ASSERTION = "unclear_assertion"
    NO_ASSERTION = "no_assertion"
    TOO_MANY_ASSERTIONS = "too_many_assertions"
    DUPLICATE_TEST = "duplicate_test"
    EMPTY_TEST = "empty_test"
    SLEEPY_TEST = "sleepy_test"
    CONDITIONAL_LOGIC = "conditional_logic"
    HARDCODED_PATH = "hardcoded_path"
    MISSING_DOCSTRING = "missing_docstring"
    POOR_NAMING = "poor_naming"
    EXCEPTION_SWALLOWING = "exception_swallowing"
    RESOURCE_LEAK = "resource_leak"
    GLOBAL_STATE = "global_state"
    MYSTERY_GUEST = "mystery_guest"


@dataclass
class TestSmellInstance:
    """Instance of a test smell"""
    smell_type: TestSmell
    line_number: int
    severity: str  # 'low', 'medium', 'high'
    message: str
    suggestion: str


@dataclass
class QualityScore:
    """Quality score breakdown"""
    overall_score: float  # 0-100
    assertion_quality: float
    edge_case_coverage: float
    naming_quality: float
    documentation_quality: float
    maintainability: float
    smells_detected: List[TestSmellInstance] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)


class TestQualityAnalyzer(ast.NodeVisitor):
    """AST visitor to analyze test quality"""
    
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.source_lines = source_code.splitlines()
        self.test_functions: List[ast.FunctionDef] = []
        self.assertions: List[Tuple[int, str]] = []
        self.imports: Set[str] = set()
        self.smells: List[TestSmellInstance] = []
        self.has_fixtures = False
        self.has_parametrize = False
        self.has_mocks = False
        self.current_function = None
        self.current_line = 0
        
    def visit_Import(self, node):
        """Track imports"""
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        """Track from imports"""
        if node.module:
            self.imports.add(node.module)
            # Check for pytest fixtures/parametrize
            if node.module == 'pytest':
                for alias in node.names:
                    if alias.name == 'fixture':
                        self.has_fixtures = True
                    elif alias.name == 'mark':
                        self.has_parametrize = True
            # Check for mocking
            if 'mock' in node.module.lower() or 'unittest.mock' in node.module:
                self.has_mocks = True
        self.generic_visit(node)
        
    def visit_FunctionDef(self, node):
        """Analyze test functions"""
        if node.name.startswith('test_'):
            self.test_functions.append(node)
            self.current_function = node
            self.current_line = node.lineno
            
            # Check for docstring
            docstring = ast.get_docstring(node)
            if not docstring:
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.MISSING_DOCSTRING,
                    line_number=node.lineno,
                    severity='low',
                    message=f"Test function '{node.name}' lacks docstring",
                    suggestion="Add docstring explaining what is being tested"
                ))
            
            # Check naming quality
            if not self._is_good_test_name(node.name):
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.POOR_NAMING,
                    line_number=node.lineno,
                    severity='medium',
                    message=f"Test name '{node.name}' is not descriptive",
                    suggestion="Use pattern: test_<method>_<scenario>_<expected_result>"
                ))
            
            # Analyze function body
            self._analyze_test_body(node)
            
            self.current_function = None
            
        self.generic_visit(node)
        
    def _is_good_test_name(self, name: str) -> bool:
        """Check if test name follows best practices"""
        # Good patterns: test_function_with_valid_input_returns_expected
        # Bad patterns: test1, test_a, test_function
        
        if len(name) < 10:  # Too short
            return False
        
        parts = name.split('_')
        if len(parts) < 3:  # Should have at least test_what_scenario
            return False
        
        # Check for generic names
        generic_words = {'test', 'a', 'b', 'c', 'temp', 'foo', 'bar'}
        meaningful_parts = [p for p in parts if p not in generic_words]
        
        return len(meaningful_parts) >= 2
    
    def _analyze_test_body(self, node: ast.FunctionDef):
        """Analyze test function body for smells"""
        assertion_count = 0
        has_sleep = False
        has_conditional = False
        has_exception_swallow = False
        
        for stmt in ast.walk(node):
            # Count assertions
            if isinstance(stmt, ast.Assert):
                assertion_count += 1
                self.assertions.append((stmt.lineno, ast.unparse(stmt.test)))
                
                # Check for unclear assertions
                if self._is_unclear_assertion(stmt):
                    self.smells.append(TestSmellInstance(
                        smell_type=TestSmell.UNCLEAR_ASSERTION,
                        line_number=stmt.lineno,
                        severity='medium',
                        message="Assertion lacks clear comparison",
                        suggestion="Use explicit comparisons: assert x == expected"
                    ))
            
            # Check for function calls
            if isinstance(stmt, ast.Call):
                if isinstance(stmt.func, ast.Attribute):
                    func_name = stmt.func.attr
                    # Check for sleep
                    if func_name in ('sleep', 'wait'):
                        has_sleep = True
                        self.smells.append(TestSmellInstance(
                            smell_type=TestSmell.SLEEPY_TEST,
                            line_number=getattr(stmt, 'lineno', 0),
                            severity='high',
                            message="Test uses sleep/wait - makes tests slow",
                            suggestion="Use mocks or event-driven waiting instead"
                        ))
                elif isinstance(stmt.func, ast.Name):
                    # Check for assert calls
                    if stmt.func.id.startswith('assert'):
                        assertion_count += 1
            
            # Check for conditionals in tests
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                has_conditional = True
                self.smells.append(TestSmellInstance(
                    smell_type=TestSmell.CONDITIONAL_LOGIC,
                    line_number=getattr(stmt, 'lineno', node.lineno),
                    severity='high',
                    message="Test contains conditional logic",
                    suggestion="Split into separate tests or use parametrize"
                ))
            
            # Check for exception swallowing
            if isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    if not handler.type or (isinstance(handler.type, ast.Name) and 
                                          handler.type.id == 'Exception'):
                        # Bare except or catching Exception
                        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                            has_exception_swallow = True
                            self.smells.append(TestSmellInstance(
                                smell_type=TestSmell.EXCEPTION_SWALLOWING,
                                line_number=getattr(stmt, 'lineno', node.lineno),
                                severity='high',
                                message="Test swallows exceptions silently",
                                suggestion="Use pytest.raises() for expected exceptions"
                            ))
            
            # Check for magic numbers
            if isinstance(stmt, ast.Constant):
                if isinstance(stmt.value, (int, float)) and stmt.value not in (0, 1, -1, 2):
                    # Check if it's in an assertion context
                    self.smells.append(TestSmellInstance(
                        smell_type=TestSmell.MAGIC_NUMBER,
                        line_number=getattr(stmt, 'lineno', node.lineno),
                        severity='low',
                        message=f"Magic number {stmt.value} used",
                        suggestion="Extract to named constant for clarity"
                    ))
        
        # Check assertion count
        if assertion_count == 0:
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.NO_ASSERTION,
                line_number=node.lineno,
                severity='high',
                message=f"Test '{node.name}' has no assertions",
                suggestion="Add assertions to verify expected behavior"
            ))
        elif assertion_count > 5:
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.TOO_MANY_ASSERTIONS,
                line_number=node.lineno,
                severity='medium',
                message=f"Test '{node.name}' has {assertion_count} assertions",
                suggestion="Consider splitting into multiple focused tests"
            ))
        
        # Check if test body is empty
        if len(node.body) <= 1 and (not node.body or isinstance(node.body[0], ast.Pass)):
            self.smells.append(TestSmellInstance(
                smell_type=TestSmell.EMPTY_TEST,
                line_number=node.lineno,
                severity='high',
                message=f"Test '{node.name}' is empty",
                suggestion="Implement test logic or remove placeholder"
            ))
    
    def _is_unclear_assertion(self, assert_node: ast.Assert) -> bool:
        """Check if assertion is unclear"""
        test_expr = assert_node.test
        
        # Good: assert x == y, assert x > y, assert x in y
        # Bad: assert x, assert func()
        
        if isinstance(test_expr, ast.Compare):
            return False  # Comparisons are clear
        
        if isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not):
            return False  # "assert not x" is acceptable
        
        # Check for boolean function calls (is_*, has_*, etc.)
        if isinstance(test_expr, ast.Call):
            if isinstance(test_expr.func, ast.Name):
                func_name = test_expr.func.id
                if any(func_name.startswith(prefix) for prefix in ['is_', 'has_', 'can_', 'should_']):
                    return False  # Boolean function names are clear
        
        return True  # Otherwise unclear


def analyze_test_quality(test_code: str, source_code: Optional[str] = None) -> QualityScore:
    """
    Analyze test code quality and return detailed score.
    High cyclomatic complexity through multiple scoring dimensions.
    """
    try:
        tree = ast.parse(test_code)
    except SyntaxError as e:
        return QualityScore(
            overall_score=0.0,
            assertion_quality=0.0,
            edge_case_coverage=0.0,
            naming_quality=0.0,
            documentation_quality=0.0,
            maintainability=0.0,
            smells_detected=[TestSmellInstance(
                smell_type=TestSmell.EMPTY_TEST,
                line_number=0,
                severity='high',
                message=f"Syntax error in test code: {e}",
                suggestion="Fix syntax errors before analyzing quality"
            )],
            improvements=["Fix syntax errors"]
        )
    
    analyzer = TestQualityAnalyzer(test_code)
    analyzer.visit(tree)
    
    # Calculate individual scores
    assertion_score = _calculate_assertion_quality(analyzer)
    edge_case_score = _calculate_edge_case_coverage(analyzer, source_code)
    naming_score = _calculate_naming_quality(analyzer)
    documentation_score = _calculate_documentation_quality(analyzer)
    maintainability_score = _calculate_maintainability(analyzer)
    
    # Calculate overall score with weights
    weights = {
        'assertion': 0.25,
        'edge_case': 0.25,
        'naming': 0.15,
        'documentation': 0.15,
        'maintainability': 0.20
    }
    
    overall = (
        assertion_score * weights['assertion'] +
        edge_case_score * weights['edge_case'] +
        naming_score * weights['naming'] +
        documentation_score * weights['documentation'] +
        maintainability_score * weights['maintainability']
    )
    
    # Apply penalties for high-severity smells
    high_severity_count = sum(1 for s in analyzer.smells if s.severity == 'high')
    overall = max(0, overall - (high_severity_count * 5))
    
    # Identify strengths and improvements
    strengths, improvements = _identify_strengths_and_improvements(
        analyzer, assertion_score, edge_case_score, naming_score,
        documentation_score, maintainability_score
    )
    
    return QualityScore(
        overall_score=round(overall, 2),
        assertion_quality=round(assertion_score, 2),
        edge_case_coverage=round(edge_case_score, 2),
        naming_quality=round(naming_score, 2),
        documentation_quality=round(documentation_score, 2),
        maintainability=round(maintainability_score, 2),
        smells_detected=analyzer.smells,
        strengths=strengths,
        improvements=improvements
    )


def _calculate_assertion_quality(analyzer: TestQualityAnalyzer) -> float:
    """Calculate assertion quality score (0-100)"""
    if not analyzer.test_functions:
        return 0.0
    
    score = 100.0
    
    # Check for tests without assertions
    no_assertion_count = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.NO_ASSERTION)
    score -= (no_assertion_count / len(analyzer.test_functions)) * 40
    
    # Check for unclear assertions
    unclear_count = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.UNCLEAR_ASSERTION)
    score -= (unclear_count / max(len(analyzer.assertions), 1)) * 30
    
    # Bonus for good assertion count per test
    avg_assertions = len(analyzer.assertions) / len(analyzer.test_functions)
    if 1 <= avg_assertions <= 3:
        score += 10
    elif avg_assertions > 5:
        score -= 10
    
    return max(0, min(100, score))


def _calculate_edge_case_coverage(analyzer: TestQualityAnalyzer, source_code: Optional[str]) -> float:
    """Calculate edge case coverage score (0-100)"""
    score = 50.0  # Base score
    
    # Check for common edge case patterns in test names
    edge_case_keywords = [
        'empty', 'none', 'null', 'zero', 'negative', 'boundary',
        'max', 'min', 'invalid', 'error', 'exception', 'edge'
    ]
    
    edge_case_tests = 0
    for func in analyzer.test_functions:
        func_name_lower = func.name.lower()
        if any(keyword in func_name_lower for keyword in edge_case_keywords):
            edge_case_tests += 1
    
    if analyzer.test_functions:
        edge_case_ratio = edge_case_tests / len(analyzer.test_functions)
        
        # Good coverage: 30-50% edge cases
        if 0.3 <= edge_case_ratio <= 0.5:
            score += 30
        elif 0.2 <= edge_case_ratio < 0.3:
            score += 20
        elif edge_case_ratio > 0.5:
            score += 10  # Too many edge cases, might be missing happy paths
        else:
            score -= 20  # Too few edge cases
    
    # Bonus for parametrized tests (better edge case coverage)
    if analyzer.has_parametrize:
        score += 20
    
    return max(0, min(100, score))


def _calculate_naming_quality(analyzer: TestQualityAnalyzer) -> float:
    """Calculate naming quality score (0-100)"""
    if not analyzer.test_functions:
        return 0.0
    
    poor_naming_count = sum(1 for s in analyzer.smells if s.smell_type == TestSmell.POOR_NAMING)
    
    score = 100.0 - (poor_naming_count / len(analyzer.test_functions)) * 100
    
    # Bonus for consistent naming patterns
    if all('_' in func.name for func in analyzer.test_functions):
        score += 10
    
    return max(0, min(100, score))


def _calculate_documentation_quality(analyzer: TestQualityAnalyzer) -> float:
    """Calculate documentation quality score (0-100)"""
    if not analyzer.test_functions:
        return 0.0
    
    missing_docstring_count = sum(1 for s in analyzer.smells 
                                  if s.smell_type == TestSmell.MISSING_DOCSTRING)
    
    score = 100.0 - (missing_docstring_count / len(analyzer.test_functions)) * 100
    
    return max(0, min(100, score))


def _calculate_maintainability(analyzer: TestQualityAnalyzer) -> float:
    """Calculate maintainability score (0-100)"""
    score = 100.0
    
    # Penalties for maintainability issues
    high_severity_smells = [
        TestSmell.SLEEPY_TEST,
        TestSmell.CONDITIONAL_LOGIC,
        TestSmell.EXCEPTION_SWALLOWING,
        TestSmell.EMPTY_TEST
    ]
    
    for smell in analyzer.smells:
        if smell.smell_type in high_severity_smells:
            score -= 15
        elif smell.severity == 'medium':
            score -= 5
        elif smell.severity == 'low':
            score -= 2
    
    # Bonuses for good practices
    if analyzer.has_fixtures:
        score += 10
    if analyzer.has_mocks:
        score += 5
    if analyzer.has_parametrize:
        score += 10
    
    return max(0, min(100, score))


def _identify_strengths_and_improvements(
    analyzer: TestQualityAnalyzer,
    assertion_score: float,
    edge_case_score: float,
    naming_score: float,
    documentation_score: float,
    maintainability_score: float
) -> Tuple[List[str], List[str]]:
    """Identify strengths and areas for improvement"""
    strengths = []
    improvements = []
    
    # Check each dimension
    if assertion_score >= 80:
        strengths.append("Excellent assertion quality")
    elif assertion_score < 50:
        improvements.append("Improve assertion clarity and coverage")
    
    if edge_case_score >= 80:
        strengths.append("Comprehensive edge case coverage")
    elif edge_case_score < 50:
        improvements.append("Add more edge case tests (empty, null, boundary values)")
    
    if naming_score >= 80:
        strengths.append("Clear and descriptive test names")
    elif naming_score < 50:
        improvements.append("Use more descriptive test names following pattern: test_<what>_<scenario>_<expected>")
    
    if documentation_score >= 80:
        strengths.append("Well-documented tests")
    elif documentation_score < 50:
        improvements.append("Add docstrings to test functions")
    
    if maintainability_score >= 80:
        strengths.append("Highly maintainable test code")
    elif maintainability_score < 50:
        improvements.append("Reduce test smells and improve maintainability")
    
    # Check for specific good practices
    if analyzer.has_fixtures:
        strengths.append("Uses pytest fixtures for setup")
    if analyzer.has_parametrize:
        strengths.append("Uses parametrized tests for multiple scenarios")
    if analyzer.has_mocks:
        strengths.append("Properly uses mocks for isolation")
    
    # Add specific improvements from smells
    smell_types = {s.smell_type for s in analyzer.smells}
    if TestSmell.SLEEPY_TEST in smell_types:
        improvements.append("Remove sleep() calls - use mocks or async waiting")
    if TestSmell.CONDITIONAL_LOGIC in smell_types:
        improvements.append("Remove conditional logic - split into separate tests")
    if TestSmell.TOO_MANY_ASSERTIONS in smell_types:
        improvements.append("Split tests with many assertions into focused tests")
    
    return strengths, improvements


if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    if len(sys.argv) < 2:
        print("Usage: python test_quality_analyzer.py <test_file>")
        sys.exit(1)
    
    test_file = Path(sys.argv[1])
    if not test_file.exists():
        print(f"Error: File not found: {test_file}")
        sys.exit(1)
    
    test_code = test_file.read_text(encoding='utf-8')
    quality = analyze_test_quality(test_code)
    
    print(f"\n{'='*60}")
    print("TEST QUALITY ANALYSIS")
    print(f"{'='*60}")
    print(f"File: {test_file}")
    print(f"\nOverall Score: {quality.overall_score:.1f}/100")
    print(f"\nScore Breakdown:")
    print(f"  Assertion Quality:    {quality.assertion_quality:.1f}/100")
    print(f"  Edge Case Coverage:   {quality.edge_case_coverage:.1f}/100")
    print(f"  Naming Quality:       {quality.naming_quality:.1f}/100")
    print(f"  Documentation:        {quality.documentation_quality:.1f}/100")
    print(f"  Maintainability:      {quality.maintainability:.1f}/100")
    
    if quality.strengths:
        print(f"\n✓ Strengths:")
        for strength in quality.strengths:
            print(f"  - {strength}")
    
    if quality.improvements:
        print(f"\n⚠ Suggested Improvements:")
        for improvement in quality.improvements:
            print(f"  - {improvement}")
    
    if quality.smells_detected:
        print(f"\n🔍 Test Smells Detected ({len(quality.smells_detected)}):")
        for smell in quality.smells_detected[:10]:  # Show first 10
            severity_icon = "🔴" if smell.severity == "high" else "🟡" if smell.severity == "medium" else "🟢"
            print(f"  {severity_icon} Line {smell.line_number}: {smell.message}")
            print(f"     → {smell.suggestion}")
    
    print(f"{'='*60}\n")
