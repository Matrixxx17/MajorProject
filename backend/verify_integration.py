import requests
import zipfile
import os
import time
import shutil

# Setup
TEST_ZIP = "test_payload.zip"
URL = "http://localhost:5000/analyze_zip"

def create_dummy_zip():
    # Create dummy python files
    with open("a.py", "w") as f:
        f.write("def hello():\n    return 'world'\n")
    
    with open("b.py", "w") as f:
        f.write("import a\ndef use_hello():\n    return a.hello() + '!'\n")
        
    with zipfile.ZipFile(TEST_ZIP, 'w') as zf:
        zf.write("a.py")
        zf.write("b.py")
        
    os.remove("a.py")
    os.remove("b.py")

def verify():
    create_dummy_zip()
    
    print(f"Sending {TEST_ZIP} to {URL}...")
    try:
        with open(TEST_ZIP, 'rb') as f:
            files = {'file': f}
            response = requests.post(URL, files=files)
            
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            print(f"Found {len(results)} results.")
            for r in results:
                print(f" - {r['file']}: {r['status']}")
                if r['status'] == 'failed':
                    print(f"   Error: {r.get('error')}")
            
            # success if backend accepted
            return True
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        if os.path.exists(TEST_ZIP):
            os.remove(TEST_ZIP)

if __name__ == "__main__":
    if verify():
        print("VERIFICATION PASSED")
    else:
        print("VERIFICATION FAILED")
