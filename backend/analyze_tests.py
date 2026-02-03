#!/usr/bin/env python3
"""
Analyze and report what test cases were generated in test files.
"""

import ast
import re
from pathlib import Path
from typing import List, Dict

def extract_test_cases(file_path: Path) -> Dict:
    """Extract test case information from a test file."""
    if not file_path.exists():
        return {"file": str(file_path), "exists": False, "tests": []}
    
    content = file_path.read_text(encoding="utf-8")
    
    tests = []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                test_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "docstring": ast.get_docstring(node) or "",
                    "decorators": [ast.unparse(d) if hasattr(ast, 'unparse') else str(d) for d in node.decorator_list],
                    "code_preview": ast.get_source_segment(content, node) or ""
                }
                tests.append(test_info)
    except SyntaxError:
        # Fallback: use regex if AST parsing fails
        test_pattern = r'def\s+(test_\w+)\s*\([^)]*\):'
        for match in re.finditer(test_pattern, content):
            test_name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            tests.append({
                "name": test_name,
                "line": line_num,
                "docstring": "",
                "decorators": [],
                "code_preview": ""
            })
    
    return {
        "file": str(file_path),
        "exists": True,
        "test_count": len(tests),
        "tests": tests
    }

def analyze_test_directory(test_dir: Path) -> Dict:
    """Analyze all test files in a directory."""
    results = {}
    
    test_files = list(test_dir.glob("test_*.py"))
    
    for test_file in test_files:
        results[test_file.name] = extract_test_cases(test_file)
    
    return results

def print_test_analysis(results: Dict):
    """Print a formatted analysis of test cases."""
    print("\n" + "="*70)
    print("GENERATED TEST CASES ANALYSIS")
    print("="*70)
    
    total_tests = 0
    
    for filename, info in results.items():
        if not info["exists"]:
            print(f"\n[FILE] {filename}")
            print("  [MISSING] File does not exist")
            continue
        
        print(f"\n[FILE] {filename}")
        print(f"  [STATUS] Found {info['test_count']} test case(s)")
        
        if info['test_count'] == 0:
            print("  [WARNING] No test functions found in this file")
        else:
            for i, test in enumerate(info['tests'], 1):
                print(f"\n  Test {i}: {test['name']}")
                print(f"    Line: {test['line']}")
                
                if test['docstring']:
                    print(f"    Description: {test['docstring']}")
                
                if test['decorators']:
                    print(f"    Decorators: {', '.join(test['decorators'])}")
                
                # Show code preview (first 3 lines of function body)
                if test['code_preview']:
                    lines = test['code_preview'].split('\n')[:5]
                    preview = '\n'.join(lines)
                    if len(test['code_preview'].split('\n')) > 5:
                        preview += "\n    ..."
                    print(f"    Code preview:")
                    for line in preview.split('\n'):
                        if line.strip():
                            print(f"      {line}")
        
        total_tests += info['test_count']
    
    print("\n" + "-"*70)
    print(f"TOTAL TEST CASES GENERATED: {total_tests}")
    print("="*70 + "\n")
    
    return total_tests

if __name__ == "__main__":
    import sys
    
    test_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("generated_tests")
    
    if not test_dir.exists():
        print(f"[ERROR] Directory not found: {test_dir}")
        sys.exit(1)
    
    results = analyze_test_directory(test_dir)
    total = print_test_analysis(results)
    
    sys.exit(0 if total > 0 else 1)


