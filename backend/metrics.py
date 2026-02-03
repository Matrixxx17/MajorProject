import subprocess
import sys
import os
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
import time


def calculate_coverage(source_file: str, test_file: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Calculate code coverage for a test file against its source file.
    
    Args:
        source_file: Path to the source Python file
        test_file: Path to the test file
        timeout: Maximum time to wait for pytest (seconds)
    
    Returns:
        Dictionary with coverage metrics:
        - coverage_percent: Overall coverage percentage
        - lines_covered: Number of lines covered
        - total_lines: Total executable lines
        - missing_lines: List of uncovered line numbers
    """
    source_path = Path(source_file)
    test_path = Path(test_file)
    
    if not source_path.exists() or not test_path.exists():
        return {
            'coverage_percent': 0.0,
            'lines_covered': 0,
            'total_lines': 0,
            'missing_lines': [],
            'error': 'Source or test file not found'
        }
    
    # Create a temporary directory for coverage data
    with tempfile.TemporaryDirectory() as temp_dir:
        coverage_file = os.path.join(temp_dir, '.coverage')
        json_report = os.path.join(temp_dir, 'coverage.json')
        
        try:
            # Run pytest with coverage
            cmd = [
                sys.executable, '-m', 'pytest',
                str(test_path),
                f'--cov={source_path.parent}',
                f'--cov-report=json:{json_report}',
                '--cov-report=term-missing',
                '--tb=no',
                '--no-header',
                '-q',
                '--disable-warnings'
            ]
            
            env = os.environ.copy()
            env['COVERAGE_FILE'] = coverage_file
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=source_path.parent
            )
            
            # Parse JSON coverage report
            if os.path.exists(json_report):
                with open(json_report, 'r') as f:
                    cov_data = json.load(f)
                
                # Find the source file in coverage data
                source_key = None
                for key in cov_data.get('files', {}).keys():
                    if source_path.name in key or str(source_path) in key:
                        source_key = key
                        break
                
                if source_key:
                    file_cov = cov_data['files'][source_key]['summary']
                    return {
                        'coverage_percent': round(file_cov.get('percent_covered', 0.0), 2),
                        'lines_covered': file_cov.get('covered_lines', 0),
                        'total_lines': file_cov.get('num_statements', 0),
                        'missing_lines': cov_data['files'][source_key].get('missing_lines', []),
                        'error': None
                    }
            
            # Fallback: parse text output
            return {
                'coverage_percent': 0.0,
                'lines_covered': 0,
                'total_lines': 0,
                'missing_lines': [],
                'error': 'Could not parse coverage report'
            }
            
        except subprocess.TimeoutExpired:
            return {
                'coverage_percent': 0.0,
                'lines_covered': 0,
                'total_lines': 0,
                'missing_lines': [],
                'error': f'Coverage calculation timed out after {timeout}s'
            }
        except Exception as e:
            return {
                'coverage_percent': 0.0,
                'lines_covered': 0,
                'total_lines': 0,
                'missing_lines': [],
                'error': f'Coverage calculation failed: {str(e)}'
            }


def calculate_mutation_score(source_file: str, test_file: str, timeout: int = 60) -> Dict[str, Any]:
    """
    Calculate mutation testing score for a test file.
    
    Args:
        source_file: Path to the source Python file
        test_file: Path to the test file
        timeout: Maximum time to wait for mutation testing (seconds)
    
    Returns:
        Dictionary with mutation metrics:
        - mutation_score: Percentage of mutants killed
        - mutants_killed: Number of mutants killed
        - total_mutants: Total number of mutants
        - status: 'completed', 'timeout', or 'error'
    """
    source_path = Path(source_file)
    test_path = Path(test_file)
    
    if not source_path.exists() or not test_path.exists():
        return {
            'mutation_score': 0.0,
            'mutants_killed': 0,
            'total_mutants': 0,
            'status': 'error',
            'error': 'Source or test file not found'
        }
    
    # Create a temporary directory for mutmut cache
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = os.path.join(temp_dir, '.mutmut-cache')
        
        try:
            # Run mutmut
            cmd = [
                sys.executable, '-m', 'mutmut',
                'run',
                '--paths-to-mutate', str(source_path),
                '--tests-dir', str(test_path.parent),
                '--no-progress',
                '--CI'
            ]
            
            env = os.environ.copy()
            env['MUTMUT_CACHE_DIR'] = cache_dir
            
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=source_path.parent
            )
            elapsed = time.time() - start_time
            
            # Parse mutmut output
            output = result.stdout + result.stderr
            
            # Look for summary line like "5/10 killed"
            import re
            killed_match = re.search(r'(\d+)/(\d+)\s+killed', output, re.IGNORECASE)
            if killed_match:
                killed = int(killed_match.group(1))
                total = int(killed_match.group(2))
                score = (killed / total * 100) if total > 0 else 0.0
                
                return {
                    'mutation_score': round(score, 2),
                    'mutants_killed': killed,
                    'total_mutants': total,
                    'status': 'completed',
                    'elapsed_time': round(elapsed, 2),
                    'error': None
                }
            
            # If no mutants found or all survived
            return {
                'mutation_score': 0.0,
                'mutants_killed': 0,
                'total_mutants': 0,
                'status': 'completed',
                'elapsed_time': round(elapsed, 2),
                'error': 'No mutation results found'
            }
            
        except subprocess.TimeoutExpired:
            return {
                'mutation_score': 0.0,
                'mutants_killed': 0,
                'total_mutants': 0,
                'status': 'timeout',
                'error': f'Mutation testing timed out after {timeout}s'
            }
        except Exception as e:
            return {
                'mutation_score': 0.0,
                'mutants_killed': 0,
                'total_mutants': 0,
                'status': 'error',
                'error': f'Mutation testing failed: {str(e)}'
            }


def calculate_all_metrics(source_file: str, test_file: str) -> Dict[str, Any]:
    """
    Calculate all performance metrics for a test file.
    
    Args:
        source_file: Path to the source Python file
        test_file: Path to the test file
    
    Returns:
        Dictionary with all metrics combined
    """
    print(f"  [METRICS] Calculating coverage for {Path(source_file).name}...")
    coverage = calculate_coverage(source_file, test_file, timeout=30)
    
    print(f"  [METRICS] Calculating mutation score for {Path(source_file).name}...")
    mutation = calculate_mutation_score(source_file, test_file, timeout=60)
    
    return {
        'coverage': coverage,
        'mutation': mutation,
        'summary': {
            'coverage_percent': coverage.get('coverage_percent', 0.0),
            'mutation_score': mutation.get('mutation_score', 0.0),
            'has_errors': bool(coverage.get('error') or mutation.get('error'))
        }
    }
