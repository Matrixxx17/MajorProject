def summ(arr):
    total = 0
    for i in range(len(arr)):
        total +=arr[i]
    print("Total",total)
arr = [1,2,1,1,5,1]
summ(arr)