import os
import zipfile
import shutil
import uuid
import threading
import time
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sys
from pathlib import Path
import ast

# Add current directory to path so we can import existing modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import existing test generation logic
try:
    from generate_test import generate_tests_ollama
    from metrics import calculate_all_metrics
    # from generate_and_run_tests import generate_tests_pynguin 
except ImportError as e:
    print(f"Warning: Could not import test generation modules: {e}")
    generate_tests_ollama = None
    calculate_all_metrics = None

app = Flask(__name__)
CORS(app)

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, 'uploads')
EXTRACT_FOLDER = os.path.join(PROJECT_ROOT, 'extracted_source')
GENERATED_TESTS_FOLDER = os.path.join(PROJECT_ROOT, 'generated_tests_api')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXTRACT_FOLDER, exist_ok=True)
os.makedirs(GENERATED_TESTS_FOLDER, exist_ok=True)

# In-memory job store (for demonstration purposes; use DB in production)
jobs = {}

def get_file_context(target_file, all_files):
    """Generate context string from other files."""
    context = []
    for file_path in all_files:
        if file_path == target_file:
            continue
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            try:
                tree = ast.parse(content)
                rel_path = os.path.basename(file_path)
                file_summary = [f"# File: {rel_path}"]
                
                # Try to get module docstring
                docstring = ast.get_docstring(tree)
                if docstring:
                    file_summary.append(f"\"\"\"{docstring}\"\"\"")
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Skip private functions
                        if node.name.startswith('_'): continue
                        
                        args = [a.arg for a in node.args.args]
                        fn_doc = ast.get_docstring(node)
                        summary = f"def {node.name}({', '.join(args)}):"
                        if fn_doc:
                            summary += f" # {fn_doc.splitlines()[0]}"
                        file_summary.append(summary)
                    elif isinstance(node, ast.ClassDef):
                        if node.name.startswith('_'): continue
                        
                        file_summary.append(f"class {node.name}:")
                        class_doc = ast.get_docstring(node)
                        if class_doc:
                            file_summary.append(f"    \"\"\"{class_doc.splitlines()[0]}\"\"\"")
                        
                        # List methods
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef):
                                m_args = [a.arg for a in item.args.args]
                                m_doc = ast.get_docstring(item)
                                m_summary = f"    def {item.name}({', '.join(m_args)}):"
                                if m_doc:
                                    m_summary += f" # {m_doc.splitlines()[0]}"
                                file_summary.append(m_summary)
                
                if len(file_summary) > 1:
                    context.append("\n".join(file_summary))
            except:
                pass 
        except:
            pass
    return "\n\n".join(context)

def process_zip_job(job_id, filepath, extract_path, model='deepseek-coder:1.3b', timeout=120):
    """Background worker function."""
    print(f"[{job_id}] Starting processing for {filepath}")
    jobs[job_id]['status'] = 'processing'
    jobs[job_id]['progress'] = 0
    jobs[job_id]['results'] = []
    
    try:
        # Extract ZIP
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
            
        # Identify Python files
        python_files = []
        for root, dirs, files in os.walk(extract_path):
            for f in files:
                if f.endswith('.py') and not f.startswith('test_'):
                    python_files.append(os.path.join(root, f))
        
        total_files = len(python_files)
        jobs[job_id]['total_files'] = total_files
        
        if total_files == 0:
            jobs[job_id]['status'] = 'completed'
            jobs[job_id]['message'] = 'No Python files found.'
            return

        # Generate tests
        for i, py_file in enumerate(python_files):
            file_name = os.path.basename(py_file)
            jobs[job_id]['current_file'] = file_name
            
            # Read code
            with open(py_file, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Get Context
            context = get_file_context(py_file, python_files)
            prompt_code = f"{code}\n\n# Context from other project files:\n{context}"
            
            result_entry = {
                'file': file_name,
                'status': 'pending'
            }
            
            if generate_tests_ollama:
                # Local timeout per file
                tests = generate_tests_ollama(prompt_code, model=model, timeout=timeout)
                if tests:
                    rel_name = os.path.splitext(file_name)[0]
                    out_name = f"test_{rel_name}.py"
                    out_path = os.path.join(GENERATED_TESTS_FOLDER, out_name)
                    
                    with open(out_path, 'w', encoding='utf-8') as tf:
                        tf.write(tests)
                    
                    result_entry['status'] = 'success'
                    result_entry['test_file'] = out_name
                    result_entry['full_path'] = out_path
                    result_entry['content'] = tests
                    
                    # Calculate performance metrics
                    if calculate_all_metrics:
                        try:
                            print(f"  [INFO] Calculating metrics for {file_name}...")
                            metrics = calculate_all_metrics(py_file, out_path)
                            result_entry['metrics'] = metrics['summary']
                            result_entry['coverage_details'] = metrics['coverage']
                            result_entry['mutation_details'] = metrics['mutation']
                        except Exception as e:
                            print(f"  [WARNING] Metrics calculation failed: {e}")
                            result_entry['metrics'] = {
                                'coverage_percent': 0.0,
                                'mutation_score': 0.0,
                                'has_errors': True
                            }
                else:
                    result_entry['status'] = 'failed'
                    result_entry['error'] = 'Ollama generation failed or timed out'
            else:
                 result_entry['status'] = 'skipped'
                 result_entry['error'] = 'Test generation module not loaded'
            
            jobs[job_id]['results'].append(result_entry)
            
            # Update progress
            jobs[job_id]['progress'] = int(((i + 1) / total_files) * 100)
            
        # Prepare a ZIP of all generated tests for download
        results_zip_name = f"tests_{job_id}.zip"
        results_zip_path = os.path.join(UPLOAD_FOLDER, results_zip_name)
        
        with zipfile.ZipFile(results_zip_path, 'w') as job_zip:
            for result in jobs[job_id]['results']:
                if result['status'] == 'success' and 'full_path' in result:
                    job_zip.write(result['full_path'], result['test_file'])
        
        jobs[job_id]['download_url'] = f"/download_tests/{job_id}"
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['message'] = 'Analysis complete'
        
    except Exception as e:
        print(f"[{job_id}] Error: {e}")
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/analyze_zip', methods=['POST'])
def analyze_zip():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file:
        job_id = str(uuid.uuid4())
        
        # Unique paths for this job
        job_dir = os.path.join(EXTRACT_FOLDER, job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        filepath = os.path.join(UPLOAD_FOLDER, f"{job_id}_{file.filename}")
        file.save(filepath)
        
        # Initialize job
        jobs[job_id] = {
            'status': 'queued',
            'submitted_at': time.time(),
            'filename': file.filename
        }
        
        # Get config from env or defaults
        model = os.environ.get('OLLAMA_MODEL', 'deepseek-coder:1.3b')
        timeout = int(os.environ.get('OLLAMA_TIMEOUT', '120'))

        # Start thread
        # modify process_zip_job signature or handle it inside? 
        # process_zip_job is defined above. I need to edit process_zip_job too.
        # It's better to pass config to the thread.
        thread = threading.Thread(target=process_zip_job, args=(job_id, filepath, job_dir, model, timeout))
        thread.start()
        
        return jsonify({
            'message': 'Job submitted',
            'job_id': job_id,
            'config': {'model': model, 'timeout': timeout}
        }), 202
            
    return jsonify({'error': 'Invalid request'}), 400

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(jobs[job_id])

@app.route('/download_tests/<job_id>', methods=['GET'])
def download_tests(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
        
    zip_path = os.path.join(UPLOAD_FOLDER, f"tests_{job_id}.zip")
    if not os.path.exists(zip_path):
        return jsonify({'error': 'Results ZIP not found'}), 404
        
    return send_file(zip_path, as_attachment=True, download_name=f"generated_tests_{jobs[job_id]['filename']}.zip")

if __name__ == '__main__':
    # Threaded mode enabled by default in Flask, but good to be explicit for dev
    app.run(debug=True, port=5000, threaded=True)
