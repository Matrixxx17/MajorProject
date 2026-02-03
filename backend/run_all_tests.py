#!/usr/bin/env python3
"""
Unified Test Generation and Execution System
Combines Pynguin and Ollama test generation with comprehensive reporting.
"""

import sys
import time
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from tabulate import tabulate

# Import our test generation modules
from generate_test import generate_tests_ollama
from generate_and_run_tests import (
    generate_tests_pynguin,
    create_property_tests,
    run_tests_summary
)


class TestReport:
    """Container for test metrics and results."""
    
    def __init__(self, method: str):
        self.method = method
        self.generation_time = 0.0
        self.execution_time = 0.0
        self.total_tests = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = 0
        self.coverage = None
        self.test_files = []
        self.success = False
        self.error_message = None


def generate_ollama_tests(code: str, output_dir: Path, module_name: str) -> TestReport:
    """Generate tests using Ollama and return report."""
    report = TestReport("Ollama")
    
    print(f"\n{'='*70}")
    print(f"METHOD 1: OLLAMA TEST GENERATION")
    print(f"{'='*70}")
    
    start_time = time.time()
    try:
        tests = generate_tests_ollama(code, model="starcoder", timeout=60)
        
        if tests:
            out_file = output_dir / f"test_{module_name}_ollama.py"
            out_file.write_text(tests, encoding="utf-8")
            report.test_files.append(str(out_file))
            report.generation_time = time.time() - start_time
            report.success = True
            
            # Run only the Ollama-generated tests
            print(f"\n{'-'*70}")
            print("Running Ollama-generated tests...")
            # Create a temporary test directory with only Ollama tests
            temp_test_dir = Path(tempfile.mkdtemp())
            shutil.copy(out_file, temp_test_dir / out_file.name)
            metrics = run_tests_summary(temp_test_dir, module_name)
            shutil.rmtree(temp_test_dir)
            
            report.execution_time = metrics['runtime']
            report.total_tests = metrics['total']
            report.passed = metrics['passed']
            report.failed = metrics['failed']
            report.skipped = metrics['skipped']
            report.errors = metrics['errors']
            report.coverage = metrics['coverage']
            
        else:
            report.success = False
            report.error_message = "Failed to generate valid test code"
            report.generation_time = time.time() - start_time
            
    except Exception as e:
        report.success = False
        report.error_message = str(e)
        report.generation_time = time.time() - start_time
    
    return report


def generate_pynguin_tests(module_path: Path, output_dir: Path, module_name: str) -> TestReport:
    """Generate tests using Pynguin and return report."""
    report = TestReport("Pynguin")
    
    print(f"\n{'='*70}")
    print(f"METHOD 2: PYNGUIN TEST GENERATION")
    print(f"{'='*70}")
    
    start_time = time.time()
    try:
        test_dir, gen_time = generate_tests_pynguin(
            str(module_path), 
            str(output_dir), 
            timeout=60  # Increased timeout for better test generation
        )
        report.generation_time = gen_time
        
        # Find testable module if it was created
        testable_module = module_path.parent / f"{module_name}.testable.py"
        testable_path = testable_module if testable_module.exists() else None
        
        # Create property-based tests
        prop_file = create_property_tests(module_name, test_dir, testable_path)
        if prop_file:
            report.test_files.append(str(prop_file))
        
        # Find all generated test files
        for test_file in test_dir.glob("test_*.py"):
            if test_file.name not in [f.name for f in [prop_file] if prop_file]:
                report.test_files.append(str(test_file))
        
        # Analyze what test cases were generated
        from generate_and_run_tests import analyze_generated_tests
        test_analysis = analyze_generated_tests(test_dir)
        
        # Run the generated tests
        print(f"\n{'-'*70}")
        print("Running Pynguin-generated tests...")
        metrics = run_tests_summary(test_dir, module_name)
        
        report.execution_time = metrics['runtime']
        report.total_tests = metrics['total']
        report.passed = metrics['passed']
        report.failed = metrics['failed']
        report.skipped = metrics['skipped']
        report.errors = metrics['errors']
        report.coverage = metrics['coverage']
        report.test_analysis = test_analysis  # Store test analysis
        report.success = True
        
    except Exception as e:
        report.success = False
        report.error_message = str(e)
        report.generation_time = time.time() - start_time
    
    return report


def generate_comprehensive_report(reports: List[TestReport], output_dir: Path, module_name: str):
    """Generate a comprehensive test report with all metrics."""
    
    print(f"\n\n{'='*70}")
    print("COMPREHENSIVE TEST REPORT")
    print(f"{'='*70}")
    
    # Summary table
    table_data = []
    for report in reports:
        pass_rate = (report.passed / report.total_tests * 100) if report.total_tests > 0 else 0
        table_data.append([
            report.method,
            "OK" if report.success else "FAIL",
            f"{report.generation_time:.2f}s",
            f"{report.execution_time:.2f}s",
            report.total_tests,
            report.passed,
            report.failed,
            f"{pass_rate:.1f}%",
            report.coverage or "N/A"
        ])
    
    headers = ["Method", "Status", "Gen Time", "Exec Time", "Total", "Passed", "Failed", "Pass Rate", "Coverage"]
    print("\n" + tabulate(table_data, headers=headers, tablefmt="grid"))
    
    # Detailed metrics
    print(f"\n{'-'*70}")
    print("DETAILED METRICS")
    print(f"{'-'*70}")
    
    total_gen_time = sum(r.generation_time for r in reports)
    total_exec_time = sum(r.execution_time for r in reports)
    total_tests = sum(r.total_tests for r in reports)
    total_passed = sum(r.passed for r in reports)
    total_failed = sum(r.failed for r in reports)
    
    print(f"Total Generation Time: {total_gen_time:.2f}s")
    print(f"Total Execution Time: {total_exec_time:.2f}s")
    print(f"Total Tests Generated: {total_tests}")
    print(f"Total Tests Passed: {total_passed}")
    print(f"Total Tests Failed: {total_failed}")
    if total_tests > 0:
        print(f"Overall Pass Rate: {(total_passed/total_tests)*100:.1f}%")
    
    # Test files location and test cases
    print(f"\n{'-'*70}")
    print("TEST FILES LOCATION & TEST CASES")
    print(f"{'-'*70}")
    print(f"All test files are located in: {output_dir.absolute()}")
    print("\nGenerated test files and test cases:")
    for report in reports:
        if report.test_files:
            print(f"\n  {report.method}:")
            for test_file in report.test_files:
                test_path = Path(test_file)
                print(f"    - {test_path.name}")
                
                # Show test cases if analysis available
                if hasattr(report, 'test_analysis') and report.test_analysis:
                    file_analysis = report.test_analysis.get('test_files', {}).get(test_path.name, {})
                    if file_analysis.get('test_count', 0) > 0:
                        for test in file_analysis.get('tests', []):
                            print(f"      * {test['name']} (line {test['line']})")
    
    # Save JSON report
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "module": module_name,
        "methods": []
    }
    
    for report in reports:
        report_data["methods"].append({
            "method": report.method,
            "success": report.success,
            "generation_time": report.generation_time,
            "execution_time": report.execution_time,
            "total_tests": report.total_tests,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "errors": report.errors,
            "coverage": report.coverage,
            "test_files": report.test_files,
            "error_message": report.error_message
        })
    
    json_report = output_dir / "test_report.json"
    with open(json_report, 'w') as f:
        json.dump(report_data, f, indent=2)
    
    print(f"\n{'-'*70}")
    print(f"JSON report saved to: {json_report}")
    print(f"{'='*70}\n")


def main():
    """Main entry point for unified test generation."""
    
    if len(sys.argv) < 2:
        print("Usage: python run_all_tests.py <python_file> [output_dir]")
        print("\nExample:")
        print("  python run_all_tests.py my_code.py")
        print("  python run_all_tests.py my_code.py ./generated_tests")
        sys.exit(1)
    
    # Parse arguments
    module_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("generated_tests")
    
    if not module_path.exists():
        print(f"[ERROR] File not found: {module_path}")
        sys.exit(1)
    
    module_name = module_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read source code
    code = module_path.read_text(encoding="utf-8")
    
    print(f"\n{'#'*70}")
    print(f"# AI-DRIVEN SOFTWARE TESTING SYSTEM")
    print(f"# Testing: {module_path.name}")
    print(f"# Output Directory: {output_dir}")
    print(f"{'#'*70}")
    
    # Generate tests using both methods
    reports = []
    
    # Method 1: Ollama
    try:
        ollama_report = generate_ollama_tests(code, output_dir, module_name)
        reports.append(ollama_report)
    except Exception as e:
        print(f"\n[ERROR] Ollama generation failed: {e}")
        import traceback
        traceback.print_exc()
        ollama_report = TestReport("Ollama")
        ollama_report.success = False
        ollama_report.error_message = str(e)
        reports.append(ollama_report)
    
    # Method 2: Pynguin
    try:
        pynguin_report = generate_pynguin_tests(module_path, output_dir, module_name)
        reports.append(pynguin_report)
    except Exception as e:
        print(f"\n[ERROR] Pynguin generation failed: {e}")
        import traceback
        traceback.print_exc()
        pynguin_report = TestReport("Pynguin")
        pynguin_report.success = False
        pynguin_report.error_message = str(e)
        reports.append(pynguin_report)
    
    # Generate comprehensive report
    generate_comprehensive_report(reports, output_dir, module_name)
    
    # Exit code based on overall success
    all_failed = all(not r.success for r in reports)
    if all_failed:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

