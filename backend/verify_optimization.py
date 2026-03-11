
import sys
import os

# Add backend directory to path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(backend_dir)

print(f"Testing backend import from: {backend_dir}")

try:
    from app import process_zip_job, ProjectContext
    print("[OK] Successfully imported process_zip_job and ProjectContext")
except ImportError as e:
    print(f"[FAIL] ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Exception during import: {e}")
    sys.exit(1)

# Check if max_concurrency is in config (by loading it via app)
try:
    from app import config
    print(f"[OK] Config loaded. Max concurrency: {config.get('max_concurrency', 'Not Found')}")
except Exception as e:
    print(f"[FAIL] Could not access config: {e}")

print("Verification script completed successfully.")
