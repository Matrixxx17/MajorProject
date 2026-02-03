def merge_sort(arr):
    if len(arr)<=1: return arr
    else:
        mid = (len(arr))//2
        left_part=arr[:mid]
        right_part=arr[mid:]
        left_sort=merge_sort(left_part)
        right_sort=merge_sort(right_part)
        return merge(left_sort,right_sort)
def merge(left,right):
    result =[]
    i=j=0
    while i<len(left) and j<len(right):
        if left[i]<right[j]:
            result.append(left[i])
            i+=1
        else:
            result.append(right[j])
            j+=1
    result.extend(left[i:])
    result.extend(right[j:])
    return result
arr=list(map(int,input("Enter the number:").split()))
sorted_arr = merge_sort(arr)
print("original array",arr)
print("biggest element",sorted_arr)