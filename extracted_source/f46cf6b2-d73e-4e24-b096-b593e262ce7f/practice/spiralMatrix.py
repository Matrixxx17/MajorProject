class solution:
    def spiral(self,matrix):
        row = len(matrix)
        col = len(matrix[0])

        left,right,top,bottom = 0,col-1,0,row-1
        res = []

        while top<=bottom and left<=right:
            for i in range(top,bottom+1):
                res.append(matrix[i][left])
            left+=1
            for i in range(left,right+1):
                res.append(matrix[bottom][i])
            bottom-=1
            if left<=right:
                for i in range(bottom,top-1,-1):
                    res.append(matrix[i][right])
            right-=1
            if top<=bottom:
                for i in range(right,left-1,-1):
                    res.append(matrix[top][i])
            top+=1
        print(res)
sol = solution()
matrix = [[1,2,3],[4,5,6],[7,8,9]]
sol.spiral(matrix)

