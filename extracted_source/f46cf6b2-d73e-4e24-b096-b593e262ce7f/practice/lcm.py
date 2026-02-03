class solution():
    def lcm(self,a,b):
        big = max(a,b)
        lc=0
        while True:
            if (big % a==0 and big% b ==0):
                lc = big
                break
            big +=1
        return lc
    def usingGcd(self,a,b):
        e =a
        f =b
        while f!=0:
            e,f=f,e%f
        gcd = e
        lcm = (a*b)/gcd
        return lcm

sol = solution()
print("Enter the number whose lcm is to be find:\n")
d=int(input())
c=int(input())
res = sol.lcm(d,c)
abc = sol.usingGcd(d,c)
print("The result is:",abc)