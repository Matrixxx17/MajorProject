# simple_programs/operations.py

def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b

def power(base: float, exponent: float) -> float:
    """Raise base to the power of exponent."""
    if exponent < 0:
        raise ValueError("Negative exponent not allowed")
    return base ** exponent

def is_even(n: int) -> bool:
    """Check if a number is even."""
    return n % 2 == 0

def reverse_string(s: str) -> str:
    """Reverse a string."""
    if not s:
        raise ValueError("Empty string")
    return s[::-1]

def average(numbers: list[float]) -> float:
    """Compute the average of a list of numbers."""
    if not numbers:
        raise ValueError("List cannot be empty")
    return sum(numbers) / len(numbers)
