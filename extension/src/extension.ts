import * as vscode from "vscode";
import * as path from "path";
import axios from "axios";

export function activate(context: vscode.ExtensionContext) {
  console.log("Test Generator extension is now active");

  // Register the webview provider
  const provider = new TestGeneratorViewProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      TestGeneratorViewProvider.viewType,
      provider
    )
  );

  // Register command to open the view
  context.subscriptions.push(
    vscode.commands.registerCommand("pynguin-test-gen.openView", () => {
      vscode.commands.executeCommand(
        "workbench.view.extension.pynguin-test-gen-container"
      );
    })
  );
}

class TestGeneratorViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "pynguin-test-gen.testGeneratorView";
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

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage(async (data) => {
      switch (data.type) {
        case "selectFile":
          await this.handleFileSelection();
          break;
        case "generateTests":
          await this.handleTestGeneration(
            data.filePath,
            data.dirPath,
            data.backendUrl
          );
          break;
      }
    });
  }

  private async handleFileSelection() {
    const fileUri = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: {
        "Python Files": ["py"],
      },
      openLabel: "Select Python Module",
    });

    if (fileUri && fileUri[0]) {
      const filePath = fileUri[0].fsPath;
      const dirPath = path.dirname(filePath);
      const fileName = path.basename(filePath);

      this._view?.webview.postMessage({
        type: "fileSelected",
        filePath: filePath,
        dirPath: dirPath,
        fileName: fileName,
      });
    }
  }

  private async handleTestGeneration(
    filePath: string,
    dirPath: string,
    backendUrl: string
  ) {
    if (!filePath || !dirPath) {
      vscode.window.showErrorMessage("Please select a Python file first");
      return;
    }

    const moduleName = path.basename(filePath, ".py");

    this._view?.webview.postMessage({
      type: "generationStarted",
      message: "Starting test generation...",
    });

    try {
      // Read the file content
      const fileUri = vscode.Uri.file(filePath);
      const fileContent = await vscode.workspace.fs.readFile(fileUri);
      const code = Buffer.from(fileContent).toString("utf8");

      // Send request to backend
      const response = await axios.post(`${backendUrl}/generate-tests`, {
        code: code,
        module_name: moduleName,
        directory: dirPath,
        file_path: filePath,
      });

      const result = await response.data as { data?: string; [key: string]: any };

      this._view?.webview.postMessage({
        type: "generationComplete",
        result: result,
      });

      // Optionally create the test file
      if (result.data) {
        await this.createTestFile(dirPath, moduleName, result.data);
      }
    } catch (error) {
      const errorMsg =
        error instanceof Error ? error.message : "Unknown error occurred";
      this._view?.webview.postMessage({
        type: "generationError",
        error: errorMsg,
      });
      vscode.window.showErrorMessage(`Test generation failed: ${errorMsg}`);
    }
  }

  private async createTestFile(
    dirPath: string,
    moduleName: string,
    testCode: string
  ) {
    const testFileName = `test_${moduleName}.py`;
    const testFilePath = path.join(dirPath, testFileName);

    const answer = await vscode.window.showInformationMessage(
      `Create test file: ${testFileName}?`,
      "Yes",
      "No"
    );

    if (answer === "Yes") {
      const testUri = vscode.Uri.file(testFilePath);
      await vscode.workspace.fs.writeFile(
        testUri,
        Buffer.from(testCode, "utf8")
      );

      // Open the test file
      const doc = await vscode.workspace.openTextDocument(testUri);
      await vscode.window.showTextDocument(doc);

      vscode.window.showInformationMessage(
        `Test file created: ${testFileName}`
      );
    }
  }

  private _getHtmlForWebview(webview: vscode.Webview) {
    return `<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Pynguin Test Generator</title>
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

                .input-group {
                    margin-bottom: 15px;
                }

                label {
                    display: block;
                    margin-bottom: 5px;
                    font-size: 12px;
                    font-weight: 500;
                }

                input[type="text"] {
                    width: 100%;
                    padding: 6px 8px;
                    background-color: var(--vscode-input-background);
                    color: var(--vscode-input-foreground);
                    border: 1px solid var(--vscode-input-border);
                    border-radius: 2px;
                    font-size: 13px;
                    box-sizing: border-box;
                }

                input[type="text"]:focus {
                    outline: 1px solid var(--vscode-focusBorder);
                }

                .file-selector {
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
                }

                .btn-secondary {
                    background-color: var(--vscode-button-secondaryBackground);
                    color: var(--vscode-button-secondaryForeground);
                    flex: 1;
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
                    color: var(--vscode-foreground);
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

                .result-section {
                    margin-top: 20px;
                    padding: 10px;
                    background-color: var(--vscode-editor-background);
                    border-radius: 2px;
                    border: 1px solid var(--vscode-panel-border);
                    max-height: 400px;
                    overflow-y: auto;
                }

                .result-section pre {
                    margin: 0;
                    font-size: 12px;
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
            </style>
        </head>
        <body>
            <h2> Codexter (Test Generator)</h2>

            <div class="file-selector">
                <button class="btn-secondary" onclick="selectFile()">📁 Select Python File</button>
            </div>

            <div class="input-group">
                <label for="filePath">File Path</label>
                <input type="text" id="filePath" readonly placeholder="No file selected">
            </div>

            <div class="input-group">
                <label for="dirPath">Directory Path</label>
                <input type="text" id="dirPath" placeholder="Auto-filled from file selection">
            </div>

            <button class="btn-primary" id="generateBtn" onclick="generateTests()" disabled>
                Generate Tests
            </button>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p>Generating tests...</p>
            </div>

            <div id="status"></div>
            <div id="result" class="result-section" style="display: none;"></div>

            <script>
                const vscode = acquireVsCodeApi();
                let selectedFilePath = '';
                let selectedDirPath = '';

                function selectFile() {
                    vscode.postMessage({ type: 'selectFile' });
                }

                function generateTests() {
                    const backendUrl = document.getElementById('backendUrl').value;
                    const filePath = document.getElementById('filePath').value;
                    const dirPath = document.getElementById('dirPath').value;

                    document.getElementById('loading').classList.add('active');
                    document.getElementById('generateBtn').disabled = true;
                    document.getElementById('status').innerHTML = '';
                    document.getElementById('result').style.display = 'none';

                    vscode.postMessage({
                        type: 'generateTests',
                        filePath: filePath,
                        dirPath: dirPath,
                        backendUrl: backendUrl
                    });
                }

                window.addEventListener('message', event => {
                    const message = event.data;
                    
                    switch (message.type) {
                        case 'fileSelected':
                            document.getElementById('filePath').value = message.filePath;
                            document.getElementById('dirPath').value = message.dirPath;
                            document.getElementById('generateBtn').disabled = false;
                            selectedFilePath = message.filePath;
                            selectedDirPath = message.dirPath;
                            showStatus('File selected: ' + message.fileName, 'info');
                            break;

                        case 'generationStarted':
                            showStatus(message.message, 'info');
                            break;

                        case 'generationComplete':
                            document.getElementById('loading').classList.remove('active');
                            document.getElementById('generateBtn').disabled = false;
                            showStatus('Test generation completed successfully!', 'success');
                            displayResult(message.result);
                            break;

                        case 'generationError':
                            document.getElementById('loading').classList.remove('active');
                            document.getElementById('generateBtn').disabled = false;
                            showStatus('Error: ' + message.error, 'error');
                            break;
                    }
                });

                function showStatus(message, type) {
                    const statusDiv = document.getElementById('status');
                    statusDiv.className = 'status ' + type;
                    statusDiv.textContent = message;
                }

                function displayResult(result) {
                    const resultDiv = document.getElementById('result');
                    resultDiv.style.display = 'block';
                    
                    let html = '<h3>Test Generation Results</h3>';
                    
                    if (result.mutation_score !== undefined) {
                        html += '<div class="metric"><span class="metric-label">Mutation Score:</span> ' + 
                                (result.mutation_score * 100).toFixed(2) + '%</div>';
                    }
                    
                    if (result.coverage !== undefined) {
                        html += '<div class="metric"><span class="metric-label">Coverage:</span> ' + 
                                (result.coverage * 100).toFixed(2) + '%</div>';
                    }
                    
                    if (result.tests) {
                        html += '<h4>Generated Tests:</h4><pre>' + escapeHtml(result.tests) + '</pre>';
                    }
                    
                    if (result.message) {
                        html += '<p>' + escapeHtml(result.message) + '</p>';
                    }
                    
                    resultDiv.innerHTML = html;
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
