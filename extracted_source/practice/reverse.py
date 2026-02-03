def reverse(arr):
    result=[]
    for i in range(len(arr)-1,-1,-1):
        result.append(arr[i])
    return result
arr=[1,2,3,4,5]
reverse_arr = reverse(arr)
print("reversed array is:",reverse_arr)