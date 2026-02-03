def element(arr,k):
    n=len(arr)
    arr[:] = arr[k:]+arr[:k]
    print("rotate=",arr)
arr = [1,2,3,4,5]
k = 2
element(arr,k)