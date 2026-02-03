import heapq
class Solution():
    def kth(self,nums,k):
        heapq.heapify(nums)
        for _ in range(k-1):
            heapq.heappop(nums)
        ans = heapq.heappop(nums)
        print("the kth smallest element is",ans)
sol = Solution()
nums = list(map(int,input("List the array: ").split()))
k = int(input("kth smallest element to be found: "))
sol.kth(nums,k)
