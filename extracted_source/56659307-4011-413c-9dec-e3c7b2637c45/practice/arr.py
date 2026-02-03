class Solution(object):
    def searchRange(self, nums, target):
        """
        :type nums: List[int]
        :type target: int
        :rtype: List[int]
        """
        nums.sort()
        # res=0
        for i in range(len(nums)):
            if nums[i]== target:
                res = i
            while nums[i]== target:
                j = len(nums) - 1
                if nums[j]== target:
                    rese = j
                else:
                    j-=1
        return [res, rese]
    
solution = Solution()
nums = [5,7,7,8,8,10]
target = 8
result = solution.searchRange(nums, target)
print(result)