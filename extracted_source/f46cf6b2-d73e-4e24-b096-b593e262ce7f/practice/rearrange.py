def arranging(arr):
    nums = sorted(arr)
    mid = len(nums)//2
    firstpart= sorted(nums[:mid])
    secondpart = sorted(nums[mid:] , reverse=True)  
    nums = firstpart + secondpart
    print(nums)
arr=[7,4,3,2,1,5]
arranging(arr)
