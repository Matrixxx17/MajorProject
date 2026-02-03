print("Factorial Calculator")
def factorial(n):
    if (n == 0 or n == 1):
        return 1
    else:
        return n * factorial(n-1)

n = int(input("Enter the number whose factorial is to be calculated: "))


print("Factorial of number is : ", factorial(n))