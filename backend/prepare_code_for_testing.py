#!/usr/bin/env python3
"""
Prepare code for testing by removing interactive elements like input() calls.
Creates a testable version of the code.
"""

import re
from pathlib import Path
import sys

def prepare_code_for_testing(source_file: Path, output_file: Path = None):
    """
    Prepare code for testing by:
    1. Commenting out input() calls
    2. Commenting out print statements that are not part of functions
    3. Making the code importable without side effects
    """
    if not source_file.exists():
        raise FileNotFoundError(f"Source file not found: {source_file}")
    
    content = source_file.read_text(encoding="utf-8")
    original_content = content
    
    # Split into lines
    lines = content.split('\n')
    modified_lines = []
    in_function = False
    indent_level = 0
    function_stack = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if line.strip() else 0
        
        # Track if we're inside a function
        if stripped.startswith('def '):
            in_function = True
            indent_level = current_indent
            function_stack.append(indent_level)
        elif stripped and not stripped.startswith('#') and not stripped.startswith('"""'):
            # Check if we've exited all functions
            if function_stack and current_indent <= function_stack[-1]:
                while function_stack and current_indent <= function_stack[-1]:
                    function_stack.pop()
                if not function_stack:
                    in_function = False
                    indent_level = 0
        
        # Comment out input() calls that are not in functions (module level)
        if not in_function and 'input(' in line and not line.strip().startswith('#'):
            # Check if it's an assignment or standalone
            if '=' in line and 'input(' in line:
                # Replace with a default value or comment it out
                modified_lines.append(f"# {line}  # Commented out for testing")
                # Add a default assignment
                var_match = re.search(r'(\w+)\s*=\s*', line)
                if var_match:
                    var_name = var_match.group(1)
                    # Try to infer type from context
                    if 'int(' in line:
                        modified_lines.append(f"{' ' * (len(line) - len(line.lstrip()))}{var_name} = 5  # Default for testing")
                    elif 'float(' in line:
                        modified_lines.append(f"{' ' * (len(line) - len(line.lstrip()))}{var_name} = 5.0  # Default for testing")
                    else:
                        modified_lines.append(f"{' ' * (len(line) - len(line.lstrip()))}{var_name} = ''  # Default for testing")
            else:
                modified_lines.append(f"# {line}  # Commented out for testing")
        # Comment out print statements at module level (not in functions)
        elif not in_function and stripped.startswith('print(') and not line.strip().startswith('#'):
            modified_lines.append(f"# {line}  # Commented out for testing")
        else:
            modified_lines.append(line)
    
    modified_content = '\n'.join(modified_lines)
    
    # If no changes were made, return original
    if modified_content == original_content:
        return False, original_content
    
    # Write to output file or return
    if output_file:
        output_file.write_text(modified_content, encoding="utf-8")
        return True, modified_content
    
    return True, modified_content

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prepare_code_for_testing.py <source_file> [output_file]")
        sys.exit(1)
    
    source = Path(sys.argv[1])
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else source.with_suffix('.testable.py')
    
    try:
        changed, content = prepare_code_for_testing(source, output)
        if changed:
            print(f"[OK] Created testable version: {output}")
            print(f"[INFO] Commented out input() and module-level print() calls")
        else:
            print(f"[INFO] No changes needed, code is already testable")
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

