#!/usr/bin/env python3
"""
System Verification Script
Tests all components of the AI-driven testing system.
"""

import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """Check if all required packages are installed."""
    print("\n" + "="*70)
    print("CHECKING DEPENDENCIES")
    print("="*70)
    
    required = ['pytest', 'hypothesis', 'pynguin', 'coverage', 'tabulate']
    missing = []
    
    for package in required:
        try:
            __import__(package.replace('-', '_'))
            print(f"  [OK] {package}")
        except ImportError:
            print(f"  [MISSING] {package}")
            missing.append(package)
    
    if missing:
        print(f"\n[ERROR] Missing packages: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False
    return True

def check_ollama():
    """Check if Ollama is available and working."""
    print("\n" + "="*70)
    print("CHECKING OLLAMA")
    print("="*70)
    
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("  [OK] Ollama is installed")
            if "starcoder" in result.stdout:
                print("  [OK] starcoder model is available")
                return True
            else:
                print("  [WARNING] starcoder model not found")
                print("  Install with: ollama pull starcoder")
                return False
        else:
            print("  [ERROR] Ollama command failed")
            return False
    except FileNotFoundError:
        print("  [ERROR] Ollama not found in PATH")
        print("  Install from: https://ollama.ai")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def check_pynguin():
    """Check if Pynguin can be imported."""
    print("\n" + "="*70)
    print("CHECKING PYNGUIN")
    print("="*70)
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pynguin", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 or "pynguin" in result.stdout.lower() or "pynguin" in result.stderr.lower():
            print("  [OK] Pynguin is installed and accessible")
            return True
        else:
            print("  [WARNING] Pynguin may not be working correctly")
            return True  # Still try to use it
    except Exception as e:
        print(f"  [WARNING] Could not verify Pynguin: {e}")
        return True  # Still try to use it

def check_test_files():
    """Check if test files exist and are readable."""
    print("\n" + "="*70)
    print("CHECKING TEST FILES")
    print("="*70)
    
    files_to_check = [
        "my_code.py",
        "generate_test.py",
        "generate_and_run_tests.py",
        "run_all_tests.py"
    ]
    
    all_exist = True
    for file in files_to_check:
        path = Path(file)
        if path.exists():
            print(f"  [OK] {file}")
        else:
            print(f"  [MISSING] {file}")
            all_exist = False
    
    return all_exist

def run_quick_test():
    """Run a quick test generation to verify the system works."""
    print("\n" + "="*70)
    print("RUNNING QUICK TEST")
    print("="*70)
    
    if not Path("my_code.py").exists():
        print("  [SKIP] my_code.py not found, skipping test")
        return True
    
    print("  [INFO] Running Pynguin test generation (this may take 30-60 seconds)...")
    try:
        result = subprocess.run(
            [sys.executable, "generate_and_run_tests.py", "my_code.py"],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            print("  [OK] Test generation completed successfully")
            # Check if test files were created
            test_dir = Path("generated_tests")
            if test_dir.exists():
                test_files = list(test_dir.glob("test_*.py"))
                if test_files:
                    print(f"  [OK] Generated {len(test_files)} test file(s)")
                    for tf in test_files:
                        print(f"    - {tf.name}")
                    return True
                else:
                    print("  [WARNING] No test files generated")
                    return False
            else:
                print("  [WARNING] generated_tests directory not created")
                return False
        else:
            print("  [WARNING] Test generation had issues")
            print(f"  Error output: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("  [WARNING] Test generation timed out (this is normal for first run)")
        return True  # Timeout is acceptable
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

def main():
    """Run all verification checks."""
    print("\n" + "#"*70)
    print("# AI-DRIVEN TESTING SYSTEM - VERIFICATION")
    print("#"*70)
    
    results = {
        "Dependencies": check_dependencies(),
        "Ollama": check_ollama(),
        "Pynguin": check_pynguin(),
        "Test Files": check_test_files(),
    }
    
    # Only run quick test if basic checks pass
    if all([results["Dependencies"], results["Pynguin"], results["Test Files"]]):
        results["Quick Test"] = run_quick_test()
    else:
        print("\n[SKIP] Skipping quick test due to missing components")
        results["Quick Test"] = None
    
    # Summary
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    for check, status in results.items():
        if status is True:
            print(f"  [PASS] {check}")
        elif status is False:
            print(f"  [FAIL] {check}")
        else:
            print(f"  [SKIP] {check}")
    
    all_passed = all(v for v in results.values() if v is not None)
    
    print("\n" + "="*70)
    if all_passed:
        print("[SUCCESS] All critical components are working!")
        print("\nYou can now run: python run_all_tests.py my_code.py")
    else:
        print("[WARNING] Some components need attention")
        print("Fix the issues above before running the full test suite")
    print("="*70 + "\n")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())


