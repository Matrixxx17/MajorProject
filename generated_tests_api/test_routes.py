import sys
sys.path.append('../') # assuming you have models in the same directory as fastapi app file
from unittest import mock
import pytest
from fastapi import HTTPException
from main_app import router , Note
# from yourmodels here (the model of FastAPI application) for instance: 
    #   from schemas.note import NoteSchema, CreateNoteSchema      ...(add these as per the need in models module.)      
import pytest_mock    
            
@pytest.fixture()              #Fixtures are executed before each test case            (setup)          -> It's a setup method to run befor every function inside tests       
def app():                      #Defining FastAPI application instance    http://localhost:5021/docs#/default-route  -->  This is the main API documentation page.     //Refer this doc for understanding and using our endpoints..   -> It's a setup method to run before each function inside tests
      app = FastAPI()             #Instantiate an instance of fastapi application    (setup)          ----->>It sets up the test client by creating an App object  in memory. This will be used for all requests made on this TestClient   -> It's a setup method to run before each function inside tests
      app.include_router(router ) #Include our router    (setup)          ----->>It includes the defined APIRouter into FastAPI application so we can call its methods from within test cases     //Refer this doc for understanding and using fastapi endpoints  -> It's a setup method to run before each function inside tests
      yield app                  #Returning an instance of created App object (setup) ----->>It returns the FastAPI application so it can be used in other parts/tests. This is called after every test case execution and helps us close connections etc.,     //Refer this doc for understanding and using fastapi endpoints  -> It's a setup method to run before each function inside tests
      app = None                #After the process of all above, we set FastAPI application as `None` so that it can be reused in other test cases.     //Refer this doc for understanding and using fastapi endpoints  -> It's a setup method to run after each function inside tests
   @pytest_mock()             #A decorator used with pytest-mock fixture    (setup)          ---->>>It will mock all dependencies needed in the test case, This is an equivalent of using dependency injection.     //Refer this doc for understanding and how fastapi application works at a more fundamental level
   def client(app):             #Client instance used to call API endpoints  app: FastAPI      -> It's set up before each function inside tests (Setup method) , Refers documentation about using the test Client.     //Refer this doc for understanding and how fastapi application works at a more fundamental level
   ...                         ......                   #Rest of your code here...            -->>Please see below lines which include all necessary imports, setup methods etc.,      -> It's set up before each function inside tests (Setup method) , Refers documentation about using the test Client.     //Refer this doc for understanding and how fastapi application works at a more fundamental level
```  [END OF CODE]   -->  After running all of these functions, pytest will execute them in order they are called within your tests (setup method). The `yield` keyword is used to return data from setup methods. This can be useful if you want the same test client instance for multiple function calls inside one file/method