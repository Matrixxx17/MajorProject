import pytest


def test_function():
    assert True == True # replace with your code

Run pytest on this file and verify it passes. Note: you may need to import numpy for this to work!
'''

import pytest

@pytest.mark.parametrize("arr,k",[
    [1,2,3,4,5],
    0,
    1
])
def test_function(arr,k):
    assert True == True # replace with your code