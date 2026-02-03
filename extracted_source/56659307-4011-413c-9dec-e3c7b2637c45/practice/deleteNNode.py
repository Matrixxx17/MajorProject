class Node:
    def __init__(self,data1,next1=None):
        self.data = data1
        self.next = next1
class Solution:
    def printLL(self,head):
        while head:
            print(head.data,end="->")
            head = head.next
    def deleteNode(self,head,N):
        dummy = Node(0,head)
        slow = dummy
        fast = dummy
        for _ in range(N+1):
            fast=fast.next
        while fast is not None:
            slow = slow.next
            fast=fast.next
        slow.next = slow.next.next

        return dummy.next

if __name__=="__main__":
    arr= [1,2,3,4,5]
    N= 3
    head = Node(arr[0])
    head.next = Node(arr[1])
    head.next.next= Node(arr[2])
    head.next.next.next = Node(arr[3])
    head.next.next.next.next = Node(arr[4])

    sol = Solution()

    head = sol.deleteNode(head,N)
    sol.printLL(head)