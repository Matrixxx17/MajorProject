print("Fibonacci Calculator")
def fibonacci(n): 
    if ( n == 0 or n == 1):
        return n
    return fibonacci(n-2) + fibonacci(n-1)
n = int(input("Enter the number whose fibonacci we want"))
print("The Fibonacci number is : ", fibonacci(n))