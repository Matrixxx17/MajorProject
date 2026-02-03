def average(arr):
    total=0
    n=len(arr)
    for i in range(n):
        total+=arr[i]
        average = total/n
    print("Average",average)
arr = [1,2,1,1,5,1]
average(arr)
