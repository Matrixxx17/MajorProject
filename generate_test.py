import sys
from pathlib import Path
import subprocess

def generate_tests_ollama(code: str, model: str = "starcoder") -> str:
    prompt = f"""
You are a Python expert. Write pytest tests for the following function, including edge cases:
{code}
"""

    process = subprocess.Popen(
        ["ollama", "run", model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    process.stdin.write(prompt.encode("utf-8"))
    process.stdin.close()

    output_lines = []
    for line in iter(process.stdout.readline, b""):
        decoded_line = line.decode("utf-8", errors="ignore").strip()
        if decoded_line and not decoded_line.startswith("#"):
            output_lines.append(decoded_line)

    return "\n".join(output_lines)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_test.py <python_file>")
        sys.exit(1)

    src_file = Path(sys.argv[1])
    if not src_file.exists():
        print(f"File not found: {src_file}")
        sys.exit(1)

    code = src_file.read_text(encoding="utf-8")

    print("  Sending code to Ollama StarCoder... (this may take a few seconds)")
    tests = generate_tests_ollama(code, model="starcoder")

    if tests:
        out_file = f"test_{src_file.stem}.py"
        Path(out_file).write_text(tests, encoding="utf-8")
        print(f"\n Test file created: {out_file}")
        print("\n---- Preview ----")
        print(tests[:1000])
    else:
        print("\n  No output received from Ollama.")
