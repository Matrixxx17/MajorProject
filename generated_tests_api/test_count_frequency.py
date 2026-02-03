import sys
sys.path.insert(0, "../practice/")
from arr import countFreq
def test_function():
    arr = [10,5,10,15,10,5]
    n = len(arr)
    countFreq(arr,n)
    
test_file.close()

Run pytest to check that it worked:
pytest test.py