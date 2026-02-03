print("To verify the numbe is even or odd")

def even(n):
    if(n % 2 == 0):
        return True
    else:
        return False

n = int(input("Enter the number tot be verified: "))

if(even(n)):
    print("The number is even")
else: 
    print("The number is odd")
