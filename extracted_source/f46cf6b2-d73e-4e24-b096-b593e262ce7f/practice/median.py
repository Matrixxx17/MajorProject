def median(arr):
    total=0
    for i in range(len(arr)):
        total+=arr[i]
    median = total/2
    print("median:",median)
        
arr = [2,5,1,7]
median(arr)