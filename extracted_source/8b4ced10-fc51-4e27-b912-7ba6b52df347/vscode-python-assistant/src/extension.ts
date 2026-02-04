import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import axios from "axios";

export function activate(context: vscode.ExtensionContext) {
  console.log("Python Assistant extension is now active");

  const provider = new PythonAssistantViewProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      PythonAssistantViewProvider.viewType,
      provider
    )
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("python-assistant.openView", () => {
      vscode.commands.executeCommand(
        "workbench.view.extension.python-assistant-container"
      );
    })
  );
}

interface FileInfo {
  path: string;
  relativePath: string;
  size: number;
}

interface AnalysisResult {
  type: "single_file" | "multiple_files" | "codebase";
  fileCount: number;
  totalSize: number;
  files: FileInfo[];
  hasTests: boolean;
  dependencies: string[];
}

class PythonAssistantViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "python-assistant.assistantView";
  private _view?: vscode.WebviewView;

  constructor(private readonly _extensionUri: vscode.Uri) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(async (data) => {
      switch (data.type) {
        case "selectFile":
          await this.handleFileSelection();
          break;
        case "selectFolder":
          await this.handleFolderSelection();
          break;
        case "analyzeContext":
          await this.handleContextAnalysis(data.paths);
          break;
        case "generateTests":
          await this.handleTestGeneration(data);
          break;
        case "refactorCode":
          await this.handleRefactoring(data);
          break;
      }
    });
  }

  private async handleFileSelection() {
    const fileUri = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: true,
      filters: {
        "Python Files": ["py"],
      },
      openLabel: "Select Python File(s)",
    });

    if (fileUri && fileUri.length > 0) {
      const paths = fileUri.map((uri) => uri.fsPath);
      await this.analyzeAndSendContext(paths);
    }
  }

  private async handleFolderSelection() {
    const folderUri = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: "Select Python Project Folder",
    });

    if (folderUri && folderUri[0]) {
      const folderPath = folderUri[0].fsPath;
      const pythonFiles = await this.findPythonFiles(folderPath);
      await this.analyzeAndSendContext(pythonFiles);
    }
  }

  private async findPythonFiles(folderPath: string): Promise<string[]> {
    const pythonFiles: string[] = [];
    
    const findRecursive = async (dir: string) => {
      const entries = await fs.promises.readdir(dir, { withFileTypes: true });
      
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        
        // Skip common ignore patterns
        if (
          entry.name.startsWith(".") ||
          entry.name === "node_modules" ||
          entry.name === "__pycache__" ||
          entry.name === "venv" ||
          entry.name === ".venv"
        ) {
          continue;
        }
        
        if (entry.isDirectory()) {
          await findRecursive(fullPath);
        } else if (entry.isFile() && entry.name.endsWith(".py")) {
          pythonFiles.push(fullPath);
        }
      }
    };
    
    await findRecursive(folderPath);
    return pythonFiles;
  }

  private async analyzeAndSendContext(paths: string[]) {
    const analysis = await this.analyzeContext(paths);
    
    this._view?.webview.postMessage({
      type: "contextAnalyzed",
      analysis: analysis,
    });
  }

  private async analyzeContext(paths: string[]): Promise<AnalysisResult> {
    const files: FileInfo[] = [];
    let totalSize = 0;
    const dependencies = new Set<string>();
    let hasTests = false;

    for (const filePath of paths) {
      try {
        const stats = await fs.promises.stat(filePath);
        const content = await fs.promises.readFile(filePath, "utf-8");
        
        files.push({
          path: filePath,
          relativePath: path.basename(filePath),
          size: stats.size,
        });
        
        totalSize += stats.size;
        
        // Check for test files
        if (
          filePath.includes("test_") ||
          filePath.includes("_test.py") ||
          filePath.includes("/tests/")
        ) {
          hasTests = true;
        }
        
        // Extract imports to identify dependencies
        const importMatches = content.match(/^(?:from|import)\s+(\w+)/gm);
        if (importMatches) {
          importMatches.forEach((match) => {
            const module = match.split(/\s+/)[1];
            if (module && !module.startsWith(".")) {
              dependencies.add(module);
            }
          });
        }
      } catch (error) {
        console.error(`Error analyzing file ${filePath}:`, error);
      }
    }

    let type: "single_file" | "multiple_files" | "codebase";
    if (files.length === 1) {
      type = "single_file";
    } else if (files.length <= 5) {
      type = "multiple_files";
    } else {
      type = "codebase";
    }

    return {
      type,
      fileCount: files.length,
      totalSize,
      files,
      hasTests,
      dependencies: Array.from(dependencies).sort(),
    };
  }

  private async handleContextAnalysis(paths: string[]) {
    const analysis = await this.analyzeContext(paths);
    
    this._view?.webview.postMessage({
      type: "contextAnalyzed",
      analysis: analysis,
    });
  }

  private async handleTestGeneration(data: any) {
    const { files, backendUrl, config } = data;

    this._view?.webview.postMessage({
      type: "operationStarted",
      operation: "test_generation",
      message: "Generating tests...",
    });

    try {
      // Read all file contents
      const fileContents = await Promise.all(
        files.map(async (file: FileInfo) => {
          const content = await fs.promises.readFile(file.path, "utf-8");
          return {
            path: file.path,
            name: path.basename(file.path, ".py"),
            content: content,
          };
        })
      );

      const response = await axios.post(
        `${backendUrl}/generate-tests`,
        {
          files: fileContents,
          config: {
            ollama_model: config.ollamaModel || "codellama",
            ollama_url: config.ollamaUrl || "http://localhost:11434",
            pynguin_timeout: config.pynguinTimeout || 60,
            mutation_threshold: config.mutationThreshold || 0.3,
          },
        },
        { timeout: 300000 } // 5 minute timeout
      );

      const result = response.data;

      this._view?.webview.postMessage({
        type: "operationComplete",
        operation: "test_generation",
        result: result,
      });

      // Offer to create test files
      if (result.test_files && result.test_files.length > 0) {
        await this.createTestFiles(result.test_files);
      }
    } catch (error) {
      const errorMsg =
        error instanceof Error ? error.message : "Unknown error occurred";
      this._view?.webview.postMessage({
        type: "operationError",
        operation: "test_generation",
        error: errorMsg,
      });
      vscode.window.showErrorMessage(`Test generation failed: ${errorMsg}`);
    }
  }

  private async handleRefactoring(data: any) {
    const { files, backendUrl, config } = data;

    this._view?.webview.postMessage({
      type: "operationStarted",
      operation: "refactoring",
      message: "Analyzing and refactoring code...",
    });

    try {
      const fileContents = await Promise.all(
        files.map(async (file: FileInfo) => {
          const content = await fs.promises.readFile(file.path, "utf-8");
          return {
            path: file.path,
            name: path.basename(file.path, ".py"),
            content: content,
          };
        })
      );

      const response = await axios.post(
        `${backendUrl}/refactor-code`,
        {
          files: fileContents,
          config: {
            model_name: config.modelName || "Salesforce/codet5p-770m",
            optimization_level: config.optimizationLevel || "balanced",
            analyze_performance: config.analyzePerformance !== false,
          },
        },
        { timeout: 300000 }
      );

      const result = response.data;

      this._view?.webview.postMessage({
        type: "operationComplete",
        operation: "refactoring",
        result: result,
      });

      // Show diff view for refactoring suggestions
      if (result.refactorings && result.refactorings.length > 0) {
        await this.showRefactoringDiffs(result.refactorings);
      }
    } catch (error) {
      const errorMsg =
        error instanceof Error ? error.message : "Unknown error occurred";
      this._view?.webview.postMessage({
        type: "operationError",
        operation: "refactoring",
        error: errorMsg,
      });
      vscode.window.showErrorMessage(`Refactoring failed: ${errorMsg}`);
    }
  }

  private async createTestFiles(testFiles: any[]) {
    for (const testFile of testFiles) {
      const answer = await vscode.window.showInformationMessage(
        `Create test file: ${testFile.filename}?`,
        "Yes",
        "No",
        "Yes to All"
      );

      if (answer === "Yes" || answer === "Yes to All") {
        const testUri = vscode.Uri.file(testFile.path);
        await vscode.workspace.fs.writeFile(
          testUri,
          Buffer.from(testFile.content, "utf8")
        );

        const doc = await vscode.workspace.openTextDocument(testUri);
        await vscode.window.showTextDocument(doc);

        vscode.window.showInformationMessage(
          `Test file created: ${testFile.filename}`
        );

        if (answer !== "Yes to All") {
          continue;
        }
      } else {
        break;
      }
    }
  }

  private async showRefactoringDiffs(refactorings: any[]) {
    for (const refactoring of refactorings) {
      const originalUri = vscode.Uri.file(refactoring.original_path);
      
      // Create temporary file for refactored version
      const tempPath = path.join(
        path.dirname(refactoring.original_path),
        `.refactored_${path.basename(refactoring.original_path)}`
      );
      const refactoredUri = vscode.Uri.file(tempPath);
      
      await vscode.workspace.fs.writeFile(
        refactoredUri,
        Buffer.from(refactoring.refactored_code, "utf8")
      );

      // Show diff
      await vscode.commands.executeCommand(
        "vscode.diff",
        originalUri,
        refactoredUri,
        `Refactoring: ${refactoring.filename} (Original ↔ Suggested)`
      );

      const answer = await vscode.window.showInformationMessage(
        `Apply refactoring to ${refactoring.filename}?`,
        "Apply",
        "Skip",
        "Cancel"
      );

      if (answer === "Apply") {
        await vscode.workspace.fs.writeFile(
          originalUri,
          Buffer.from(refactoring.refactored_code, "utf8")
        );
        vscode.window.showInformationMessage(
          `Applied refactoring to ${refactoring.filename}`
        );
      } else if (answer === "Cancel") {
        break;
      }

      // Clean up temp file
      try {
        await vscode.workspace.fs.delete(refactoredUri);
      } catch (e) {
        // Ignore cleanup errors
      }
    }
  }

  private _getHtmlForWebview(webview: vscode.Webview) {
    return `<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Python Assistant</title>
            <style>
                body {
                    padding: 15px;
                    font-family: var(--vscode-font-family);
                    color: var(--vscode-foreground);
                    background-color: var(--vscode-sideBar-background);
                }
                
                h2 {
                    margin-top: 0;
                    font-size: 16px;
                    font-weight: 600;
                    margin-bottom: 20px;
                }

                h3 {
                    font-size: 14px;
                    font-weight: 600;
                    margin-top: 20px;
                    margin-bottom: 10px;
                    color: var(--vscode-textPreformat-foreground);
                }

                .input-group {
                    margin-bottom: 15px;
                }

                label {
                    display: block;
                    margin-bottom: 5px;
                    font-size: 12px;
                    font-weight: 500;
                }

                input[type="text"], input[type="number"], select {
                    width: 100%;
                    padding: 6px 8px;
                    background-color: var(--vscode-input-background);
                    color: var(--vscode-input-foreground);
                    border: 1px solid var(--vscode-input-border);
                    border-radius: 2px;
                    font-size: 13px;
                    box-sizing: border-box;
                }

                input:focus, select:focus {
                    outline: 1px solid var(--vscode-focusBorder);
                }

                .button-group {
                    display: flex;
                    gap: 8px;
                    margin-bottom: 15px;
                }

                button {
                    padding: 6px 14px;
                    background-color: var(--vscode-button-background);
                    color: var(--vscode-button-foreground);
                    border: none;
                    border-radius: 2px;
                    cursor: pointer;
                    font-size: 13px;
                    font-family: var(--vscode-font-family);
                    flex: 1;
                }

                button:hover {
                    background-color: var(--vscode-button-hoverBackground);
                }

                button:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }

                .btn-primary {
                    width: 100%;
                    padding: 8px;
                    font-weight: 500;
                    margin-bottom: 8px;
                }

                .btn-secondary {
                    background-color: var(--vscode-button-secondaryBackground);
                    color: var(--vscode-button-secondaryForeground);
                }

                .btn-secondary:hover {
                    background-color: var(--vscode-button-secondaryHoverBackground);
                }

                .status {
                    margin-top: 15px;
                    padding: 10px;
                    border-radius: 2px;
                    font-size: 12px;
                }

                .status.info {
                    background-color: var(--vscode-inputValidation-infoBackground);
                    border: 1px solid var(--vscode-inputValidation-infoBorder);
                }

                .status.success {
                    background-color: rgba(0, 128, 0, 0.1);
                    border: 1px solid rgba(0, 128, 0, 0.3);
                }

                .status.error {
                    background-color: var(--vscode-inputValidation-errorBackground);
                    border: 1px solid var(--vscode-inputValidation-errorBorder);
                }

                .loading {
                    display: none;
                    text-align: center;
                    margin-top: 10px;
                }

                .loading.active {
                    display: block;
                }

                .spinner {
                    border: 2px solid var(--vscode-progressBar-background);
                    border-top: 2px solid var(--vscode-button-background);
                    border-radius: 50%;
                    width: 20px;
                    height: 20px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto;
                }

                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }

                .context-info {
                    margin: 15px 0;
                    padding: 10px;
                    background-color: var(--vscode-editor-background);
                    border-radius: 2px;
                    border: 1px solid var(--vscode-panel-border);
                }

                .context-info p {
                    margin: 5px 0;
                    font-size: 12px;
                }

                .badge {
                    display: inline-block;
                    padding: 2px 8px;
                    background-color: var(--vscode-badge-background);
                    color: var(--vscode-badge-foreground);
                    border-radius: 10px;
                    font-size: 11px;
                    margin-left: 5px;
                }

                .result-section {
                    margin-top: 20px;
                    padding: 10px;
                    background-color: var(--vscode-editor-background);
                    border-radius: 2px;
                    border: 1px solid var(--vscode-panel-border);
                    max-height: 500px;
                    overflow-y: auto;
                }

                .result-section pre {
                    margin: 0;
                    font-size: 11px;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                }

                .metric {
                    margin: 5px 0;
                    font-size: 12px;
                }

                .metric-label {
                    font-weight: 600;
                    color: var(--vscode-textPreformat-foreground);
                }

                .tab-container {
                    margin-bottom: 15px;
                }

                .tabs {
                    display: flex;
                    gap: 2px;
                    border-bottom: 1px solid var(--vscode-panel-border);
                    margin-bottom: 15px;
                }

                .tab {
                    padding: 8px 16px;
                    background-color: transparent;
                    border: none;
                    border-bottom: 2px solid transparent;
                    cursor: pointer;
                    font-size: 13px;
                    color: var(--vscode-foreground);
                    opacity: 0.7;
                }

                .tab.active {
                    opacity: 1;
                    border-bottom-color: var(--vscode-button-background);
                }

                .tab-content {
                    display: none;
                }

                .tab-content.active {
                    display: block;
                }

                .collapsible {
                    margin-top: 10px;
                }

                .collapsible-header {
                    cursor: pointer;
                    padding: 8px;
                    background-color: var(--vscode-editor-background);
                    border: 1px solid var(--vscode-panel-border);
                    border-radius: 2px;
                    font-size: 12px;
                    font-weight: 600;
                    user-select: none;
                }

                .collapsible-header:hover {
                    background-color: var(--vscode-list-hoverBackground);
                }

                .collapsible-content {
                    display: none;
                    padding: 10px;
                    border: 1px solid var(--vscode-panel-border);
                    border-top: none;
                    border-radius: 0 0 2px 2px;
                    background-color: var(--vscode-editor-background);
                }

                .collapsible-content.open {
                    display: block;
                }
            </style>
        </head>
        <body>
            <h2>🐍 Python Assistant</h2>

            <div class="input-group">
                <label for="backendUrl">Backend URL</label>
                <input type="text" id="backendUrl" value="http://localhost:8000" placeholder="http://localhost:8000">
            </div>

            <h3>Select Context</h3>
            <div class="button-group">
                <button class="btn-secondary" onclick="selectFile()">📄 Select File(s)</button>
                <button class="btn-secondary" onclick="selectFolder()">📁 Select Folder</button>
            </div>

            <div id="contextInfo" class="context-info" style="display: none;">
                <p><strong>Context Type:</strong> <span id="contextType"></span></p>
                <p><strong>Files:</strong> <span id="fileCount"></span></p>
                <p><strong>Total Size:</strong> <span id="totalSize"></span></p>
                <p id="hasTestsInfo" style="display: none;"><span class="badge">Has Tests</span></p>
            </div>

            <div class="tab-container" id="modeSelector" style="display: none;">
                <div class="tabs">
                    <button class="tab active" onclick="switchTab('testgen')">Test Generation</button>
                    <button class="tab" onclick="switchTab('refactor')">Refactoring</button>
                </div>

                <div id="testgen-tab" class="tab-content active">
                    <h3>Test Generation Settings</h3>
                    
                    <div class="input-group">
                        <label for="ollamaModel">Ollama Model</label>
                        <input type="text" id="ollamaModel" value="codellama" placeholder="codellama">
                    </div>

                    <div class="input-group">
                        <label for="ollamaUrl">Ollama URL</label>
                        <input type="text" id="ollamaUrl" value="http://localhost:11434" placeholder="http://localhost:11434">
                    </div>

                    <div class="input-group">
                        <label for="pynguinTimeout">Pynguin Timeout (seconds)</label>
                        <input type="number" id="pynguinTimeout" value="60" min="10" max="300">
                    </div>

                    <div class="input-group">
                        <label for="mutationThreshold">Mutation Threshold</label>
                        <input type="number" id="mutationThreshold" value="0.3" min="0" max="1" step="0.1">
                    </div>

                    <button class="btn-primary" id="generateTestsBtn" onclick="generateTests()" disabled>
                        🧪 Generate Tests
                    </button>
                </div>

                <div id="refactor-tab" class="tab-content">
                    <h3>Refactoring Settings</h3>
                    
                    <div class="input-group">
                        <label for="modelName">Model</label>
                        <select id="modelName">
                            <option value="Salesforce/codet5p-770m">CodeT5+ (770M)</option>
                            <option value="Salesforce/codet5p-2b">CodeT5+ (2B)</option>
                            <option value="bigcode/starcoderbase">StarCoder Base</option>
                        </select>
                    </div>

                    <div class="input-group">
                        <label for="optimizationLevel">Optimization Level</label>
                        <select id="optimizationLevel">
                            <option value="readability">Readability Focus</option>
                            <option value="balanced" selected>Balanced</option>
                            <option value="performance">Performance Focus</option>
                        </select>
                    </div>

                    <div class="input-group">
                        <label>
                            <input type="checkbox" id="analyzePerformance" checked>
                            Analyze Performance Metrics
                        </label>
                    </div>

                    <button class="btn-primary" id="refactorBtn" onclick="refactorCode()" disabled>
                        ✨ Refactor Code
                    </button>
                </div>
            </div>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p id="loadingMessage">Processing...</p>
            </div>

            <div id="status"></div>
            <div id="result" class="result-section" style="display: none;"></div>

            <script>
                const vscode = acquireVsCodeApi();
                let currentContext = null;

                function selectFile() {
                    vscode.postMessage({ type: 'selectFile' });
                }

                function selectFolder() {
                    vscode.postMessage({ type: 'selectFolder' });
                }

                function switchTab(tabName) {
                    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                    
                    event.target.classList.add('active');
                    document.getElementById(tabName + '-tab').classList.add('active');
                }

                function generateTests() {
                    if (!currentContext) return;

                    const config = {
                        ollamaModel: document.getElementById('ollamaModel').value,
                        ollamaUrl: document.getElementById('ollamaUrl').value,
                        pynguinTimeout: parseInt(document.getElementById('pynguinTimeout').value),
                        mutationThreshold: parseFloat(document.getElementById('mutationThreshold').value)
                    };

                    document.getElementById('loading').classList.add('active');
                    document.getElementById('loadingMessage').textContent = 'Generating tests...';
                    document.getElementById('generateTestsBtn').disabled = true;
                    document.getElementById('status').innerHTML = '';
                    document.getElementById('result').style.display = 'none';

                    vscode.postMessage({
                        type: 'generateTests',
                        files: currentContext.files,
                        backendUrl: document.getElementById('backendUrl').value,
                        config: config
                    });
                }

                function refactorCode() {
                    if (!currentContext) return;

                    const config = {
                        modelName: document.getElementById('modelName').value,
                        optimizationLevel: document.getElementById('optimizationLevel').value,
                        analyzePerformance: document.getElementById('analyzePerformance').checked
                    };

                    document.getElementById('loading').classList.add('active');
                    document.getElementById('loadingMessage').textContent = 'Analyzing and refactoring code...';
                    document.getElementById('refactorBtn').disabled = true;
                    document.getElementById('status').innerHTML = '';
                    document.getElementById('result').style.display = 'none';

                    vscode.postMessage({
                        type: 'refactorCode',
                        files: currentContext.files,
                        backendUrl: document.getElementById('backendUrl').value,
                        config: config
                    });
                }

                window.addEventListener('message', event => {
                    const message = event.data;
                    
                    switch (message.type) {
                        case 'contextAnalyzed':
                            handleContextAnalyzed(message.analysis);
                            break;

                        case 'operationStarted':
                            showStatus(message.message, 'info');
                            break;

                        case 'operationComplete':
                            handleOperationComplete(message.operation, message.result);
                            break;

                        case 'operationError':
                            handleOperationError(message.operation, message.error);
                            break;
                    }
                });

                function handleContextAnalyzed(analysis) {
                    currentContext = analysis;
                    
                    document.getElementById('contextInfo').style.display = 'block';
                    document.getElementById('contextType').textContent = formatContextType(analysis.type);
                    document.getElementById('fileCount').textContent = analysis.fileCount;
                    document.getElementById('totalSize').textContent = formatBytes(analysis.totalSize);
                    
                    if (analysis.hasTests) {
                        document.getElementById('hasTestsInfo').style.display = 'block';
                    } else {
                        document.getElementById('hasTestsInfo').style.display = 'none';
                    }

                    document.getElementById('modeSelector').style.display = 'block';
                    document.getElementById('generateTestsBtn').disabled = false;
                    document.getElementById('refactorBtn').disabled = false;

                    showStatus(\`Context loaded: \${analysis.fileCount} Python file(s)\`, 'success');
                }

                function handleOperationComplete(operation, result) {
                    document.getElementById('loading').classList.remove('active');
                    document.getElementById('generateTestsBtn').disabled = false;
                    document.getElementById('refactorBtn').disabled = false;

                    if (operation === 'test_generation') {
                        showStatus('Test generation completed!', 'success');
                        displayTestResults(result);
                    } else if (operation === 'refactoring') {
                        showStatus('Refactoring completed!', 'success');
                        displayRefactoringResults(result);
                    }
                }

                function handleOperationError(operation, error) {
                    document.getElementById('loading').classList.remove('active');
                    document.getElementById('generateTestsBtn').disabled = false;
                    document.getElementById('refactorBtn').disabled = false;
                    showStatus('Error: ' + error, 'error');
                }

                function displayTestResults(result) {
                    const resultDiv = document.getElementById('result');
                    resultDiv.style.display = 'block';
                    
                    let html = '<h3>Test Generation Results</h3>';
                    
                    if (result.total_coverage !== undefined) {
                        html += '<div class="metric"><span class="metric-label">Total Coverage:</span> ' + 
                                (result.total_coverage * 100).toFixed(2) + '%</div>';
                    }
                    
                    if (result.avg_mutation_score !== undefined) {
                        html += '<div class="metric"><span class="metric-label">Avg Mutation Score:</span> ' + 
                                (result.avg_mutation_score * 100).toFixed(2) + '%</div>';
                    }

                    if (result.test_files && result.test_files.length > 0) {
                        html += '<h4>Generated Test Files (' + result.test_files.length + '):</h4>';
                        result.test_files.forEach((file, idx) => {
                            html += '<div class="collapsible">';
                            html += '<div class="collapsible-header" onclick="toggleCollapsible(this)">' +
                                    '▶ ' + escapeHtml(file.filename) + '</div>';
                            html += '<div class="collapsible-content"><pre>' + 
                                    escapeHtml(file.content.substring(0, 500)) + '...</pre></div>';
                            html += '</div>';
                        });
                    }
                    
                    resultDiv.innerHTML = html;
                }

                function displayRefactoringResults(result) {
                    const resultDiv = document.getElementById('result');
                    resultDiv.style.display = 'block';
                    
                    let html = '<h3>Refactoring Results</h3>';
                    
                    if (result.refactorings && result.refactorings.length > 0) {
                        html += '<p><strong>Files Refactored:</strong> ' + result.refactorings.length + '</p>';
                        
                        result.refactorings.forEach((ref, idx) => {
                            html += '<div class="collapsible">';
                            html += '<div class="collapsible-header" onclick="toggleCollapsible(this)">' +
                                    '▶ ' + escapeHtml(ref.filename) + '</div>';
                            html += '<div class="collapsible-content">';
                            
                            if (ref.improvements && ref.improvements.length > 0) {
                                html += '<h4>Improvements:</h4><ul>';
                                ref.improvements.forEach(imp => {
                                    html += '<li>' + escapeHtml(imp) + '</li>';
                                });
                                html += '</ul>';
                            }
                            
                            if (ref.performance_metrics) {
                                html += '<h4>Performance Metrics:</h4>';
                                html += '<div class="metric"><span class="metric-label">Complexity Reduction:</span> ' +
                                        ref.performance_metrics.complexity_reduction + '%</div>';
                                html += '<div class="metric"><span class="metric-label">Code Quality Score:</span> ' +
                                        ref.performance_metrics.quality_score + '/10</div>';
                            }
                            
                            html += '</div></div>';
                        });
                    }
                    
                    resultDiv.innerHTML = html;
                }

                function toggleCollapsible(header) {
                    const content = header.nextElementSibling;
                    const isOpen = content.classList.contains('open');
                    
                    content.classList.toggle('open');
                    header.textContent = (isOpen ? '▶ ' : '▼ ') + header.textContent.substring(2);
                }

                function showStatus(message, type) {
                    const statusDiv = document.getElementById('status');
                    statusDiv.className = 'status ' + type;
                    statusDiv.textContent = message;
                }

                function formatContextType(type) {
                    const types = {
                        'single_file': 'Single File',
                        'multiple_files': 'Multiple Files',
                        'codebase': 'Full Codebase'
                    };
                    return types[type] || type;
                }

                function formatBytes(bytes) {
                    if (bytes < 1024) return bytes + ' B';
                    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
                    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
                }

                function escapeHtml(text) {
                    const div = document.createElement('div');
                    div.textContent = text;
                    return div.innerHTML;
                }
            </script>
        </body>
        </html>`;
  }
}

export function deactivate() {}
