import pytest, sys; sys.path.append('../') # Assuming the file is located inside a folder named 'tests' of your main project directory  
from unittest import mock
# Required for all tests after this line...
pytestmark = pytest.mark.usefixtures("note_fixture")  #Firefox needs to be loaded by default before running the test suite (like in Selenium)   
                                            
def create(self, note): pass      
@mock.patch('routes')  
#... and here are your tests:                   
                                         
class TestNoteClass():                  
  def setup_method(self):               # Before each method call run this function                    
      self.__module__ = "Testing"       
                                                                    
def test_create_note(); pass             # Defining a dummy func to be tested  
                                                      
@mock.patch('routes')                          
class TestNoteClass():                         
    def setup_method(self):                                 
       self.__module__ = "Testing" 
                                                                    
def test_create_note(); pass                     # Defining a dummy func to be tested