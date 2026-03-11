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
    from test_strategy_selector import select_test_strategy, TestStrategy
    from test_quality_analyzer import analyze_test_quality
    from ensemble_test_generator import generate_ensemble_tests
    # from generate_and_run_tests import generate_tests_pynguin 
except ImportError as e:
    print(f"Warning: Could not import test generation modules: {e}")
    generate_tests_ollama = None
    calculate_all_metrics = None
    select_test_strategy = None
    analyze_test_quality = None
    generate_ensemble_tests = None

app = Flask(__name__)
CORS(app)

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, 'uploads')
EXTRACT_FOLDER = os.path.join(PROJECT_ROOT, 'extracted_source')
GENERATED_TESTS_FOLDER = os.path.join(PROJECT_ROOT, 'generated_tests_api')
CONFIG_FILE = os.path.join(PROJECT_ROOT, 'test_config.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXTRACT_FOLDER, exist_ok=True)
os.makedirs(GENERATED_TESTS_FOLDER, exist_ok=True)

# In-memory job store (for demonstration purposes; use DB in production)
jobs = {}

# Load configuration
def load_config():
    """Load configuration from file or use defaults"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "default_strategy": "auto",
        "enable_quality_analysis": True,
        "enable_ensemble": False,
        "quality_threshold": 70.0
    }

config = load_config()

# Helper class for efficient context generation
class ProjectContext:
    def __init__(self, file_paths):
        self.file_paths = file_paths
        self.summaries = {}
        self._precompute_summaries()

    def _precompute_summaries(self):
        """Parse all files once and store their summaries"""
        for file_path in self.file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.summaries[file_path] = self._generate_single_summary(file_path, content)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")
                self.summaries[file_path] = ""

    def _generate_single_summary(self, file_path, content):
        """Generate summary for a single file using AST"""
        try:
            tree = ast.parse(content)
            rel_path = os.path.basename(file_path)
            summary_lines = [f"# File: {rel_path}"]
            
            docstring = ast.get_docstring(tree)
            if docstring:
                summary_lines.append(f"\"\"\"{docstring}\"\"\"")
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name.startswith('_'): continue
                    args = [a.arg for a in node.args.args]
                    fn_doc = ast.get_docstring(node)
                    sig = f"def {node.name}({', '.join(args)}):"
                    if fn_doc:
                        sig += f" # {fn_doc.splitlines()[0]}"
                    summary_lines.append(sig)
                elif isinstance(node, ast.ClassDef):
                    if node.name.startswith('_'): continue
                    summary_lines.append(f"class {node.name}:")
                    class_doc = ast.get_docstring(node)
                    if class_doc:
                        summary_lines.append(f"    \"\"\"{class_doc.splitlines()[0]}\"\"\"")
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            m_args = [a.arg for a in item.args.args]
                            m_doc = ast.get_docstring(item)
                            m_sig = f"    def {item.name}({', '.join(m_args)}):"
                            if m_doc:
                                m_sig += f" # {m_doc.splitlines()[0]}"
                            summary_lines.append(m_sig)
            
            return "\n".join(summary_lines)
        except:
            return ""

    def get_context_for_file(self, target_file):
        """Get context from all files EXCEPT the target file"""
        context_parts = []
        for path, summary in self.summaries.items():
            if path != target_file and summary:
                context_parts.append(summary)
        return "\n\n".join(context_parts)

def process_single_file(file_info, project_context, config, job_config):
    """Process a single file: generate tests, run metrics, check quality."""
    py_file = file_info['path']
    file_name = file_info['name']
    job_id = job_config['job_id']
    model = job_config['model']
    timeout = job_config['timeout']
    strategy = job_config['strategy']
    
    print(f"[{job_id}] Processing {file_name}...")
    
    result_entry = {
        'file': file_name,
        'status': 'pending'
    }

    try:
        with open(py_file, 'r', encoding='utf-8') as f:
            code = f.read()
        
        # 1. Get Context (Fast from cache)
        context = project_context.get_context_for_file(py_file)
        prompt_code = f"{code}\n\n# Context from other project files:\n{context}"
        
        # 2. Determine Strategy
        file_strategy = strategy
        if strategy == 'auto' and select_test_strategy:
            selected_strategy, strategy_details = select_test_strategy(code, py_file)
            file_strategy = selected_strategy.value
            result_entry['strategy_details'] = {
                'selected': file_strategy,
                'confidence': strategy_details.get('confidence', 0),
                'complexity_score': strategy_details.get('metrics', {}).get('overall_score', 0)
            }
            print(f"  [STRATEGY] {file_name}: {file_strategy}")

        # 3. Generate Tests
        tests = None
        generation_method = 'unknown'
        
        # Try Ensemble
        if file_strategy == 'ensemble' and generate_ensemble_tests:
            try:
                print(f"  [ENSEMBLE] {file_name}...")
                ensemble_result = generate_ensemble_tests(prompt_code)
                tests = ensemble_result.final_test_code
                generation_method = 'ensemble'
                result_entry['ensemble_details'] = {
                    'models_used': [m.value for m in ensemble_result.models_used],
                    'best_model': ensemble_result.best_model.value,
                    'quality_score': ensemble_result.quality_score
                }
            except Exception as e:
                print(f"  [WARNING] Ensemble failed for {file_name}: {e}")
                file_strategy = 'standard'

        # Try Standard (Ollama)
        if not tests and generate_tests_ollama:
            generation_method = 'single_model'
            tests = generate_tests_ollama(prompt_code, model=model, timeout=timeout)
        
        # FALLBACK: If still no tests, use simple fallback
        if not tests:
            print(f"  [FALLBACK] Generating simple tests for {file_name}")
            from generate_test import fallback_simple_tests
            module_name = os.path.splitext(file_name)[0]
            tests = fallback_simple_tests(code, module_name)
            generation_method = 'fallback'
            result_entry['is_fallback'] = True

        # 4. Save and Analyze
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
            result_entry['generation_method'] = generation_method
            
            # Metrics (Optional - can be slow)
            if calculate_all_metrics:
                try:
                    metrics = calculate_all_metrics(py_file, out_path)
                    result_entry['metrics'] = metrics['summary']
                    result_entry['coverage_details'] = metrics['coverage']
                    result_entry['mutation_details'] = metrics['mutation']
                except Exception as e:
                    print(f"  [WARNING] Metrics failed for {file_name}: {e}")
                    result_entry['metrics'] = {'error': str(e)}

            # Quality Analysis
            if config.get('enable_quality_analysis', True) and analyze_test_quality:
                try:
                    quality = analyze_test_quality(tests, code)
                    result_entry['quality_analysis'] = {
                        'overall_score': quality.overall_score,
                        'smells_count': len(quality.smells_detected)
                    }
                except Exception as e:
                    print(f"  [WARNING] Quality analysis failed for {file_name}: {e}")

        else:
            result_entry['status'] = 'failed'
            result_entry['error'] = 'All generation methods failed'

    except Exception as e:
        print(f"[{job_id}] Error processing {file_name}: {e}")
        result_entry['status'] = 'error'
        result_entry['error'] = str(e)
        
    return result_entry

def process_zip_job(job_id, filepath, extract_path, model='deepseek-coder:1.3b', timeout=120, strategy='auto'):
    """Background worker with parallel processing."""
    print(f"[{job_id}] Starting job for {filepath}")
    jobs[job_id]['status'] = 'processing'
    jobs[job_id]['progress'] = 0
    jobs[job_id]['results'] = []
    
    try:
        # Extract
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
            
        # Find Python files
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

        # Initialize Context Cache
        print(f"[{job_id}] Building project context...")
        project_context = ProjectContext(python_files)
        
        # Thread Pool for Parallel Execution
        # Default to 3 workers to avoid overloading Ollama
        max_workers = config.get('max_concurrency', 3)
        job_config = {
            'job_id': job_id,
            'model': model,
            'timeout': timeout,
            'strategy': strategy
        }
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        completed_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(
                    process_single_file, 
                    {'path': p, 'name': os.path.basename(p)}, 
                    project_context, 
                    config, 
                    job_config
                ): p for p in python_files
            }
            
            for future in as_completed(future_to_file):
                result = future.result()
                jobs[job_id]['results'].append(result)
                completed_count += 1
                jobs[job_id]['progress'] = int((completed_count / total_files) * 100)
                
        # Create Result ZIP
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
        print(f"[{job_id}] Fatal Job Error: {e}")
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
        import traceback
        traceback.print_exc()

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
        
        # Get config from request or env or defaults
        model = request.form.get('model', os.environ.get('OLLAMA_MODEL', 'deepseek-coder:1.3b'))
        timeout = int(request.form.get('timeout', os.environ.get('OLLAMA_TIMEOUT', '120')))
        strategy = request.form.get('strategy', config.get('default_strategy', 'auto'))

        # Start thread
        thread = threading.Thread(target=process_zip_job, args=(job_id, filepath, job_dir, model, timeout, strategy))
        thread.start()
        
        return jsonify({
            'message': 'Job submitted',
            'job_id': job_id,
            'config': {
                'model': model,
                'timeout': timeout,
                'strategy': strategy,
                'quality_analysis_enabled': config.get('enable_quality_analysis', True)
            }
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

@app.route('/analyze_strategy', methods=['POST'])
def analyze_strategy():
    """Analyze code and suggest optimal test strategy"""
    if 'code' not in request.json:
        return jsonify({'error': 'No code provided'}), 400
    
    code = request.json['code']
    
    if not select_test_strategy:
        return jsonify({'error': 'Strategy selector not available'}), 503
    
    try:
        strategy, details = select_test_strategy(code)
        return jsonify({
            'strategy': strategy.value,
            'confidence': details.get('confidence', 0),
            'metrics': details.get('metrics', {}),
            'reasoning': details.get('reasoning', [])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analyze_quality', methods=['POST'])
def analyze_quality():
    """Analyze test code quality"""
    if 'test_code' not in request.json:
        return jsonify({'error': 'No test code provided'}), 400
    
    test_code = request.json['test_code']
    source_code = request.json.get('source_code')
    
    if not analyze_test_quality:
        return jsonify({'error': 'Quality analyzer not available'}), 503
    
    try:
        quality = analyze_test_quality(test_code, source_code)
        return jsonify({
            'overall_score': quality.overall_score,
            'scores': {
                'assertion_quality': quality.assertion_quality,
                'edge_case_coverage': quality.edge_case_coverage,
                'naming_quality': quality.naming_quality,
                'documentation_quality': quality.documentation_quality,
                'maintainability': quality.maintainability
            },
            'strengths': quality.strengths,
            'improvements': quality.improvements,
            'smells': [
                {
                    'type': s.smell_type.value,
                    'severity': s.severity,
                    'line': s.line_number,
                    'message': s.message,
                    'suggestion': s.suggestion
                }
                for s in quality.smells_detected
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/config', methods=['GET', 'POST'])
def manage_config():
    """Get or update configuration"""
    global config
    
    if request.method == 'GET':
        return jsonify(config)
    
    elif request.method == 'POST':
        try:
            new_config = request.json
            config.update(new_config)
            
            # Save to file
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            
            return jsonify({'message': 'Configuration updated', 'config': config})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Threaded mode enabled by default in Flask, but good to be explicit for dev
    app.run(debug=True, port=5000, threaded=True)
