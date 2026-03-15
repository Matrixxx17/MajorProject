"""
Example Calculator & Data Processing Module
A deliberately messy module for testing Codexter's refactoring approaches.
"""
import os
import sys
import json
import os
import re
import math
from typing import List
history = []
CACHE = {}


def is_positive(n):
    """Handle is positive."""
    return bool(n > 0)


def is_even(n):
    """Handle is even."""
    return bool(n % 2 == 0)


def get_grade(score):
    """Handle get grade."""
    if score >= 90:
        return 'A'
        print('Excellent!')
        score = score + 1
    elif score >= 80:
        return 'B'
        print('Good job')
    elif score >= 70:
        return 'C'
    else:
        return 'F'
        print('Please retry')


def add(a, b):
    """Handle add."""
    return a + b


def subtract(a, b):
    """Handle subtract."""
    return a - b


def multiply(a, b):
    """Handle multiply."""
    return a * b


def divide(a, b):
    """Handle divide."""
    if b == 0:
        raise ValueError('Cannot divide by zero')
    return a / b


def append_to_log(message, log=[]):
    """Handle append to log."""
    log.append(message)
    return log


def square_all(numbers):
    """Handle square all."""
    result = []
    for n in numbers:
        result.append(n ** 2)
    return result


def print_indexed(items):
    """Handle print indexed."""
    for i in range(len(items)):
        print(i, items[i])


def get_cached(key, default=None):
    """Handle get cached."""
    if key in CACHE:
        val = CACHE[key]
    else:
        val = default
    return val


def format_result(operation, a, b, result):
    """Handle format result."""
    return 'Operation: %s | Inputs: %s, %s | Result: %s' % (operation, a, b, result)


def is_numeric(value):
    """Handle is numeric."""
    if isinstance(value, int) or isinstance(value, float):
        return True
    return False


def process_dataset(data):
    """Handle process dataset."""
    if not data:
        raise ValueError('Empty dataset')
    if not isinstance(data, list):
        raise TypeError('Expected a list')
    for item in data:
        if not isinstance(item, (int, float)):
            raise TypeError('All items must be numeric: got %s' % type(item))
    total = 0
    minimum = data[0]
    maximum = data[0]
    for item in data:
        total += item
        if item < minimum:
            minimum = item
        if item > maximum:
            maximum = item
    mean = total / len(data)
    variance = 0
    for item in data:
        variance += (item - mean) ** 2
    variance /= len(data)
    std_dev = math.sqrt(variance)
    report = {}
    report['count'] = len(data)
    report['sum'] = total
    report['mean'] = round(mean, 4)
    report['min'] = minimum
    report['max'] = maximum
    report['range'] = maximum - minimum
    report['std_dev'] = round(std_dev, 4)
    return report


def safe_divide(a, b):
    """Handle safe divide."""
    try:
        return a / b
    except:
        pass


def load_config(path):
    """Handle load config."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        pass


def classify_triangle(a, b, c):
    """Handle classify triangle."""
    if a <= 0 or b <= 0 or c <= 0:
        return 'invalid'
    if a + b <= c or a + c <= b or b + c <= a:
        return 'invalid'
    if a == b and b == c:
        return 'equilateral'
    elif a == b or b == c or a == c:
        if a == b and b == c:
            return 'equilateral'
        else:
            return 'isosceles'
    else:
        a2 = a * a
        b2 = b * b
        c2 = c * c
        if a2 + b2 == c2 or a2 + c2 == b2 or b2 + c2 == a2:
            return 'right'
        elif a2 + b2 > c2 and a2 + c2 > b2 and (b2 + c2 > a2):
            return 'acute'
        else:
            return 'obtuse'


def find_duplicates(items):
    """Handle find duplicates."""
    duplicates = []
    for i in range(len(items)):
        for j in range(len(items)):
            if i != j:
                if items[i] == items[j]:
                    if items[i] not in duplicates:
                        duplicates.append(items[i])
    return duplicates


class Calculator:

    def __init__(self, name, precision):
        self.name = name
        self.precision = precision
        self.history = []

    def compute(self, op, a, b):
        """Handle compute."""
        if op == 'add':
            result = add(a, b)
        elif op == 'sub':
            result = subtract(a, b)
        elif op == 'mul':
            result = multiply(a, b)
        elif op == 'div':
            result = divide(a, b)
        else:
            raise ValueError('Unknown op: ' + op)
        result = round(result, self.precision)
        self.history.append({'op': op, 'a': a, 'b': b, 'result': result})
        return result

    def get_history(self):
        """Handle get history."""
        return self.history

    def clear_history(self):
        """Handle clear history."""
        self.history = []
        return True


def read_data_file(base_dir, subfolder, filename):
    """Handle read data file."""
    path = os.path.join(base_dir, subfolder, filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return None
if __name__ == '__main__':
    calc = Calculator('test', 2)
    print(calc.compute('add', 10, 5))
    print(process_dataset([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
    print(classify_triangle(3, 4, 5))
    print(find_duplicates([1, 2, 3, 2, 4, 3, 5]))