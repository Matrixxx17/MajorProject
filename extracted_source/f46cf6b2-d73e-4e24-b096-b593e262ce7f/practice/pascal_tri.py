row = int(input("Enter the row of pascal traingle starting from zeroth row"))
for i in range(row):
    val = 1
    for j in range(i+1):
        print(val,end=" ")
        val = val * (i-j)//(j+1)
    print()