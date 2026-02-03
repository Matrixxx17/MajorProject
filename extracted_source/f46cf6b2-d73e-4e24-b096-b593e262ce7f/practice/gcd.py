class solution:
    def gcd(self,a,b):
        while b!=0:
            a,b=b,a%b
        return a
sol = solution()
print("Enter the two number for whose gcd is to be find")
a=int(input("A="))
b=int(input("B="))
res = sol.gcd(a,b)
print("The answer is:",res)