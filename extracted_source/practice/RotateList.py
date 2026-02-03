class ListNode:
    def __init__(self,x):
        self.val = x
        self.next = None
class Solution:
    def rotateList(self,head):
        slow, fast = head,head.next 
        while fast and fast.next:
            slow = slow.next
            fast = fast.next.next
        second = slow.next
        prev = slow.next = None
        while second:
            tmp = second.next
            second.next = prev
            prev = second
            second = tmp
        first = head
        second = prev
        while second:
            tmp1,tmp2 = first.next , second.next
            first.next = second
            second.next = tmp1
            first,second = tmp1,tmp2
        return head
def buildLinkedList(arr):
    head = ListNode(arr[0])
    curr = head
    for x in arr[1:]:
        curr.next = ListNode(x)
        curr = curr.next
    return head
def printLinkedList(head):
    curr = head
    while curr:
        print(curr.val,end= " -> ")
        curr = curr.next
    print("None")

sol = Solution()
x = list(map(int,input("Enter the Linked List:").split()))
head = buildLinkedList(x)
sol = Solution()
head = sol.rotateList(head)
print("The Solution is:")
printLinkedList(head)

