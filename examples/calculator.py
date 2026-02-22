"""
Example calculator module for testing the Pynguin Test Generator
This module demonstrates various function types that Pynguin can test
"""

class Calculator:
    """A simple calculator class with various operations"""
    
    def __init__(self):
        self.history = []
    
    def add(self, a: float, b: float) -> float:
        """Add two numbers and store in history"""
        result = a + b
        self.history.append(f"{a} + {b} = {result}")
        return result
    
    def subtract(self, a: float, b: float) -> float:
        """Subtract b from a"""
        result = a - b
        self.history.append(f"{a} - {b} = {result}")
        return result
    
    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers"""
        result = a * b
        self.history.append(f"{a} * {b} = {result}")
        return result
    
    def divide(self, a: float, b: float) -> float:
        """Divide a by b, raises ZeroDivisionError if b is 0"""
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        result = a / b
        self.history.append(f"{a} / {b} = {result}")
        return result
    
    def power(self, base: float, exponent: float) -> float:
        """Calculate base raised to exponent"""
        if base == 0 and exponent < 0:
            raise ValueError("Cannot raise 0 to negative power")
        result = base ** exponent
        self.history.append(f"{base} ^ {exponent} = {result}")
        return result
    
    def get_history(self) -> list:
        """Return calculation history"""
        return self.history.copy()
    
    def clear_history(self):
        """Clear the calculation history"""
        self.history = []


def calculate_discount(price: float, discount_percent: float) -> float:
    """
    Calculate discounted price
    
    Args:
        price: Original price
        discount_percent: Discount percentage (0-100)
    
    Returns:
        Discounted price
    
    Raises:
        ValueError: If discount_percent is not between 0 and 100
        ValueError: If price is negative
    """
    if price < 0:
        raise ValueError("Price cannot be negative")
    
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Discount must be between 0 and 100")
    
    return price * (1 - discount_percent / 100)


def calculate_bmi(weight_kg: float, height_m: float) -> dict:
    """
    Calculate Body Mass Index
    
    Args:
        weight_kg: Weight in kilograms
        height_m: Height in meters
    
    Returns:
        Dictionary with BMI value and category
    
    Raises:
        ValueError: If weight or height is not positive
    """
    if weight_kg <= 0:
        raise ValueError("Weight must be positive")
    
    if height_m <= 0:
        raise ValueError("Height must be positive")
    
    bmi = weight_kg / (height_m ** 2)
    
    # Determine category
    if bmi < 18.5:
        category = "Underweight"
    elif bmi < 25:
        category = "Normal weight"
    elif bmi < 30:
        category = "Overweight"
    else:
        category = "Obese"
    
    return {
        "bmi": round(bmi, 2),
        "category": category
    }


def is_palindrome(text: str) -> bool:
    """
    Check if a string is a palindrome (ignoring case and spaces)
    
    Args:
        text: String to check
    
    Returns:
        True if palindrome, False otherwise
    """
    if not text:
        return True
    
    # Remove spaces and convert to lowercase
    cleaned = ''.join(text.split()).lower()
    
    return cleaned == cleaned[::-1]


def fibonacci(n: int) -> list:
    """
    Generate Fibonacci sequence up to n terms
    
    Args:
        n: Number of terms to generate
    
    Returns:
        List of Fibonacci numbers
    
    Raises:
        ValueError: If n is negative
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    
    if n == 0:
        return []
    
    if n == 1:
        return [0]
    
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])
    
    return fib


def find_max_min(numbers: list) -> dict:
    """
    Find maximum and minimum values in a list
    
    Args:
        numbers: List of numbers
    
    Returns:
        Dictionary with max and min values
    
    Raises:
        ValueError: If list is empty
    """
    if not numbers:
        raise ValueError("List cannot be empty")
    
    return {
        "max": max(numbers),
        "min": min(numbers),
        "range": max(numbers) - min(numbers)
    }


if __name__ == "__main__":
    # Example usage
    calc = Calculator()
    print(calc.add(10, 5))
    print(calc.multiply(3, 7))
    print(calc.get_history())
    
    print(calculate_discount(100, 20))
    print(calculate_bmi(70, 1.75))
    print(is_palindrome("A man a plan a canal Panama"))
    print(fibonacci(10))
    print(find_max_min([3, 1, 4, 1, 5, 9, 2, 6]))