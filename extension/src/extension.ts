import * as vscode from "vscode";
import * as path from "path";
import axios from "axios";

export function activate(context: vscode.ExtensionContext) {
  console.log("Test Generator extension is now active");

  const provider = new TestGeneratorViewProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      TestGeneratorViewProvider.viewType,
      provider,
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("pynguin-test-gen.openView", () => {
      vscode.commands.executeCommand(
        "workbench.view.extension.pynguin-test-gen-container",
      );
    }),
  );

  // Listen for active editor changes to update refactor view
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && provider.isViewVisible()) {
        provider.notifyActiveFileChanged(editor.document.uri.fsPath);
      }
    }),
  );
}

class TestGeneratorViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "pynguin-test-gen.testGeneratorView";
  private _view?: vscode.WebviewView;

  constructor(private readonly _extensionUri: vscode.Uri) {}

  public isViewVisible(): boolean {
    return !!this._view?.visible;
  }

  public notifyActiveFileChanged(filePath: string) {
    if (filePath.endsWith(".py")) {
      this._view?.webview.postMessage({
        type: "activeFileChanged",
        filePath: filePath,
      });
    }
  }

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ) {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

    // Send the currently active file on load
    const activeEditor = vscode.window.activeTextEditor;
    if (activeEditor && activeEditor.document.uri.fsPath.endsWith(".py")) {
      setTimeout(() => {
        this._view?.webview.postMessage({
          type: "activeFileChanged",
          filePath: activeEditor.document.uri.fsPath,
        });
      }, 300);
    }

    webviewView.webview.onDidReceiveMessage(async (data) => {
      switch (data.type) {
        case "selectFile":
          await this.handleFileSelection();
          break;
        case "generateTests":
          await this.handleTestGeneration(
            data.filePath,
            data.dirPath,
            data.backendUrl,
          );
          break;
        case "refactorCode":
          await this.handleRefactoring(data.filePath, data.backendUrl);
          break;
        case "requestActiveFile":
          const editor = vscode.window.activeTextEditor;
          if (editor && editor.document.uri.fsPath.endsWith(".py")) {
            this._view?.webview.postMessage({
              type: "activeFileChanged",
              filePath: editor.document.uri.fsPath,
            });
          }
          break;
      }
    });
  }

  private async handleFileSelection() {
    const fileUri = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { "Python Files": ["py"] },
      openLabel: "Select Python Module",
    });

    if (fileUri && fileUri[0]) {
      const filePath = fileUri[0].fsPath;
      const dirPath = path.dirname(filePath);
      const fileName = path.basename(filePath);
      this._view?.webview.postMessage({
        type: "fileSelected",
        filePath,
        dirPath,
        fileName,
      });
    }
  }

  private async handleTestGeneration(
    filePath: string,
    dirPath: string,
    backendUrl: string,
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
      const fileContent = await vscode.workspace.fs.readFile(
        vscode.Uri.file(filePath),
      );
      const code = Buffer.from(fileContent).toString("utf8");

      const response = await axios.post(
        `${backendUrl}/generate-tests`,
        {
          code,
          module_name: moduleName,
          directory: dirPath,
          file_path: filePath,
        },
        { timeout: 300000 },
      );

      const result = response.data;
      this._view?.webview.postMessage({ type: "generationComplete", result });

      if (result.tests) {
        await this.createTestFile(dirPath, moduleName, result.tests);
      }
    } catch (error) {
      let errorMsg = "Unknown error occurred";
      if (axios.isAxiosError(error)) {
        if (error.response?.data?.detail?.error) {
          errorMsg = error.response.data.detail.error;
          this._view?.webview.postMessage({
            type: "generationError",
            error: errorMsg,
            logs: error.response.data.detail.logs || [],
          });
          return;
        } else if (error.code === "ECONNREFUSED") {
          errorMsg = `Cannot connect to backend at ${backendUrl}`;
        } else {
          errorMsg = error.message;
        }
      } else if (error instanceof Error) {
        errorMsg = error.message;
      }
      this._view?.webview.postMessage({
        type: "generationError",
        error: errorMsg,
      });
      vscode.window.showErrorMessage(`Test generation failed: ${errorMsg}`);
    }
  }

  private async handleRefactoring(filePath: string, backendUrl: string) {
    if (!filePath) {
      vscode.window.showErrorMessage("No Python file selected for refactoring");
      return;
    }
    this._view?.webview.postMessage({
      type: "refactorStarted",
      message: "Refactoring in progress...",
    });

    // Placeholder — wire up to your backend endpoint when ready
    setTimeout(() => {
      this._view?.webview.postMessage({
        type: "refactorComplete",
        message: "Refactoring endpoint not yet connected.",
      });
    }, 1500);
  }

  private async createTestFile(
    dirPath: string,
    moduleName: string,
    testCode: string,
  ) {
    const testFileName = `test_${moduleName}.py`;
    const testFilePath = path.join(dirPath, testFileName);
    const answer = await vscode.window.showInformationMessage(
      `Create test file: ${testFileName}?`,
      "Yes",
      "No",
    );
    if (answer === "Yes") {
      const testUri = vscode.Uri.file(testFilePath);
      await vscode.workspace.fs.writeFile(
        testUri,
        Buffer.from(testCode, "utf8"),
      );
      const doc = await vscode.workspace.openTextDocument(testUri);
      await vscode.window.showTextDocument(doc);
      vscode.window.showInformationMessage(
        `Test file created: ${testFileName}`,
      );
    }
  }

  private _getHtmlForWebview(webview: vscode.Webview) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Codexter</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Syne:wght@400;600;700&display=swap');

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:        #0d0d0f;
      --surface:   #13131a;
      --border:    #1e1e2e;
      --accent:    #7b6ef6;
      --accent-lo: rgba(123,110,246,0.12);
      --accent-hi: #a89af9;
      --green:     #4ade80;
      --green-lo:  rgba(74,222,128,0.1);
      --red:       #f87171;
      --red-lo:    rgba(248,113,113,0.1);
      --text:      #e2e2f0;
      --muted:     #6b6b8a;
      --mono:      'JetBrains Mono', monospace;
      --sans:      'Syne', sans-serif;
    }

    html, body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      height: 100%;
      overflow-x: hidden;
    }

    /* ── Header ── */
    .header {
      padding: 18px 16px 0;
      animation: fadeDown 0.4s ease both;
    }
    .wordmark {
      font-family: var(--sans);
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.04em;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 7px;
    }
    .wordmark .dot {
      width: 7px; height: 7px;
      background: var(--accent);
      border-radius: 50%;
      box-shadow: 0 0 8px var(--accent);
      animation: pulse 2.5s ease-in-out infinite;
    }
    .tagline {
      font-size: 10px;
      color: var(--muted);
      margin-top: 3px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    /* ── Tabs ── */
    .tabs {
      display: flex;
      gap: 2px;
      margin: 16px 16px 0;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 3px;
      animation: fadeDown 0.4s 0.06s ease both;
    }
    .tab {
      flex: 1;
      padding: 7px 0;
      border: none;
      background: transparent;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.04em;
      cursor: pointer;
      border-radius: 5px;
      transition: all 0.2s ease;
    }
    .tab:hover { color: var(--text); }
    .tab.active {
      background: var(--accent-lo);
      color: var(--accent-hi);
      border: 1px solid rgba(123,110,246,0.28);
    }
    .tab-icon { margin-right: 5px; }

    /* ── View Panels ── */
    .panel {
      display: none;
      padding: 16px;
      animation: fadeUp 0.22s ease both;
    }
    .panel.active { display: block; }

    /* ── Section label ── */
    .section-label {
      font-size: 9px;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }

    /* ── Input group ── */
    .input-group { margin-bottom: 14px; }

    .input-wrap { position: relative; display: flex; align-items: center; }
    .input-icon {
      position: absolute; left: 10px;
      color: var(--muted); font-size: 11px; pointer-events: none;
    }
    input[type="text"] {
      width: 100%;
      padding: 8px 10px 8px 28px;
      background: var(--surface);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      font-family: var(--mono);
      font-size: 11px;
      outline: none;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }
    input[type="text"]:focus {
      border-color: rgba(123,110,246,0.5);
      box-shadow: 0 0 0 3px rgba(123,110,246,0.08);
    }
    input[type="text"][readonly] { color: var(--muted); cursor: default; }
    input[type="text"]::placeholder { color: #2e2e48; }

    /* ── Buttons ── */
    .btn {
      display: flex; align-items: center; justify-content: center; gap: 6px;
      width: 100%; padding: 9px;
      border: none; border-radius: 7px;
      font-family: var(--mono); font-size: 11px; font-weight: 600;
      letter-spacing: 0.04em; cursor: pointer;
      transition: all 0.2s ease; position: relative; overflow: hidden;
    }
    .btn::after {
      content: ''; position: absolute; inset: 0;
      background: white; opacity: 0; transition: opacity 0.15s ease;
    }
    .btn:active::after { opacity: 0.06; }

    .btn-primary {
      background: linear-gradient(135deg, var(--accent) 0%, #9b8bf8 100%);
      color: #fff;
      box-shadow: 0 4px 16px rgba(123,110,246,0.28);
    }
    .btn-primary:hover:not(:disabled) {
      box-shadow: 0 6px 22px rgba(123,110,246,0.42);
      transform: translateY(-1px);
    }
    .btn-primary:disabled { opacity: 0.35; cursor: not-allowed; transform: none; box-shadow: none; }

    .btn-ghost {
      background: var(--surface); color: var(--muted);
      border: 1px solid var(--border);
      width: auto; padding: 7px 12px; font-size: 12px;
    }
    .btn-ghost:hover { color: var(--text); border-color: #2e2e45; }

    .btn-refactor {
      background: linear-gradient(135deg, #16a34a 0%, #4ade80 100%);
      color: #051a0e;
      box-shadow: 0 4px 16px rgba(74,222,128,0.22);
    }
    .btn-refactor:hover:not(:disabled) {
      box-shadow: 0 6px 22px rgba(74,222,128,0.38);
      transform: translateY(-1px);
    }
    .btn-refactor:disabled { opacity: 0.35; cursor: not-allowed; transform: none; box-shadow: none; }

    /* ── File row ── */
    .file-row {
      display: flex; gap: 8px; align-items: flex-end; margin-bottom: 14px;
    }
    .file-row .input-group { flex: 1; margin-bottom: 0; }

    /* ── Divider ── */
    .divider { height: 1px; background: var(--border); margin: 14px 0; }

    /* ── Spinner / loading ── */
    .loading {
      display: none; flex-direction: column; align-items: center;
      gap: 10px; padding: 20px 0 8px;
      color: var(--muted); font-size: 10px; letter-spacing: 0.06em;
    }
    .loading.active { display: flex; }
    .spinner-ring {
      width: 24px; height: 24px; border-radius: 50%;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      animation: spin 0.75s linear infinite;
    }
    .loading-dots::after { content: ''; animation: dots 1.4s infinite; }

    /* ── Status badge ── */
    .status {
      display: none; align-items: center; gap: 7px;
      padding: 9px 11px; border-radius: 7px; font-size: 11px;
      margin-top: 12px; animation: fadeUp 0.2s ease both;
    }
    .status.show { display: flex; }
    .status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
    .status.info    { background: rgba(123,110,246,0.08); border: 1px solid rgba(123,110,246,0.2); color: var(--accent-hi); }
    .status.info    .status-dot { background: var(--accent); box-shadow: 0 0 6px var(--accent); animation: pulse 1.5s ease-in-out infinite; }
    .status.success { background: var(--green-lo); border: 1px solid rgba(74,222,128,0.25); color: var(--green); }
    .status.success .status-dot { background: var(--green); }
    .status.error   { background: var(--red-lo); border: 1px solid rgba(248,113,113,0.25); color: var(--red); }
    .status.error   .status-dot { background: var(--red); }

    /* ── Results ── */
    .results { display: none; margin-top: 14px; animation: fadeUp 0.25s ease both; }
    .results.show { display: block; }

    .metrics-row { display: flex; gap: 8px; margin-bottom: 12px; }
    .metric-card {
      flex: 1; background: var(--surface);
      border: 1px solid var(--border); border-radius: 8px; padding: 10px 10px 8px;
    }
    .metric-card .m-label {
      font-size: 9px; color: var(--muted);
      letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 4px;
    }
    .metric-card .m-value {
      font-family: var(--sans); font-size: 18px; font-weight: 700;
      color: var(--accent-hi); line-height: 1;
    }
    .metric-card .m-value.good { color: var(--green); }
    .metric-card .m-value.warn { color: #fbbf24; }
    .metric-card .m-value.bad  { color: var(--red); }

    .code-block {
      background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
    }
    .code-block-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 12px; border-bottom: 1px solid var(--border);
    }
    .code-block-title { font-size: 10px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
    .code-block pre {
      padding: 12px; font-size: 10.5px; line-height: 1.6; color: #c4c4e0;
      max-height: 260px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
    }
    .code-block pre::-webkit-scrollbar { width: 4px; }
    .code-block pre::-webkit-scrollbar-track { background: transparent; }
    .code-block pre::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

    /* ── Refactor panel ── */
    .refactor-file-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 12px 14px; margin-bottom: 14px;
      display: flex; align-items: flex-start; gap: 10px;
    }
    .rfc-icon { font-size: 18px; line-height: 1; flex-shrink: 0; margin-top: 1px; }
    .rfc-body { flex: 1; min-width: 0; }
    .rfc-label {
      font-size: 9px; color: var(--muted);
      letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 4px;
    }
    .rfc-path { font-size: 11px; color: var(--text); word-break: break-all; line-height: 1.4; }
    .rfc-path.empty { color: var(--muted); font-style: italic; }
    .rfc-badge {
      display: inline-block; margin-top: 5px; font-size: 9px;
      background: var(--accent-lo); color: var(--accent-hi);
      border: 1px solid rgba(123,110,246,0.25);
      border-radius: 4px; padding: 2px 6px; letter-spacing: 0.06em;
    }
    .rfc-badge.none {
      background: rgba(107,107,138,0.1); color: var(--muted); border-color: var(--border);
    }

    /* ── Keyframes ── */
    @keyframes fadeDown {
      from { opacity: 0; transform: translateY(-8px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.4; }
    }
    @keyframes dots {
      0%   { content: ''; }
      33%  { content: '.'; }
      66%  { content: '..'; }
      100% { content: '...'; }
    }
  </style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div class="wordmark">
      <span class="dot"></span>Codexter
    </div>
    <div class="tagline">AI-powered test &amp; refactor</div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <button class="tab active" onclick="switchTab('generate', this)">
      <span class="tab-icon">⬡</span>Test Gen
    </button>
    <button class="tab" onclick="switchTab('refactor', this)">
      <span class="tab-icon">⟳</span>Refactor
    </button>
  </div>

  <!-- ══════════ PANEL: Test Generation ══════════ -->
  <div class="panel active" id="panel-generate">

    <div class="input-group" style="margin-bottom:10px;">
      <div class="section-label">Backend URL</div>
      <div class="input-wrap">
        <span class="input-icon">◈</span>
        <input type="text" id="backendUrl" value="http://localhost:8000" placeholder="http://localhost:8000" />
      </div>
    </div>

    <div class="divider"></div>

    <div class="file-row">
      <div class="input-group">
        <div class="section-label">Python File</div>
        <div class="input-wrap">
          <span class="input-icon">◉</span>
          <input type="text" id="filePath" readonly placeholder="No file selected" />
        </div>
      </div>
      <button class="btn btn-ghost" onclick="selectFile()" title="Browse">📁</button>
    </div>

    <div class="input-group">
      <div class="section-label">Directory</div>
      <div class="input-wrap">
        <span class="input-icon">◈</span>
        <input type="text" id="dirPath" placeholder="Auto-filled" />
      </div>
    </div>

    <button class="btn btn-primary" id="generateBtn" onclick="generateTests()" disabled>
      <span>⬡</span> Generate Tests
    </button>

    <div class="loading" id="gen-loading">
      <div class="spinner-ring"></div>
      <span>Running pipeline<span class="loading-dots"></span></span>
    </div>

    <div class="status" id="gen-status">
      <span class="status-dot"></span>
      <span id="gen-status-text"></span>
    </div>

    <div class="results" id="gen-results">
      <div class="metrics-row">
        <div class="metric-card">
          <div class="m-label">Mutation</div>
          <div class="m-value" id="res-mutation">—</div>
        </div>
        <div class="metric-card">
          <div class="m-label">Coverage</div>
          <div class="m-value" id="res-coverage">—</div>
        </div>
      </div>
      <div class="code-block">
        <div class="code-block-header">
          <span class="code-block-title">Generated Tests</span>
        </div>
        <pre id="res-code"></pre>
      </div>
    </div>

  </div>

  <!-- ══════════ PANEL: Refactor ══════════ -->
  <div class="panel" id="panel-refactor">

    <div class="input-group" style="margin-bottom:10px;">
      <div class="section-label">Backend URL</div>
      <div class="input-wrap">
        <span class="input-icon">◈</span>
        <input type="text" id="refactorBackendUrl" value="http://localhost:8000" placeholder="http://localhost:8000" />
      </div>
    </div>

    <div class="divider"></div>

    <div class="section-label">Selected File</div>
    <div class="refactor-file-card">
      <div class="rfc-icon">🐍</div>
      <div class="rfc-body">
        <div class="rfc-label">Active Editor</div>
        <div class="rfc-path empty" id="rfc-path">No Python file open</div>
        <span class="rfc-badge none" id="rfc-badge">none</span>
      </div>
    </div>

    <button class="btn btn-refactor" id="refactorBtn" onclick="refactorCode()" disabled>
      <span>⟳</span> Refactor Code
    </button>

    <div class="loading" id="ref-loading">
      <div class="spinner-ring" style="border-top-color: var(--green);"></div>
      <span>Refactoring<span class="loading-dots"></span></span>
    </div>

    <div class="status" id="ref-status">
      <span class="status-dot"></span>
      <span id="ref-status-text"></span>
    </div>

  </div>

  <script>
    const vscode = acquireVsCodeApi();

    // ── Tab switching ──────────────────────────────────────
    function switchTab(tab, btn) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + tab).classList.add('active');
    }

    // ── Test Gen ───────────────────────────────────────────
    function selectFile() {
      vscode.postMessage({ type: 'selectFile' });
    }

    function generateTests() {
      const backendUrl = document.getElementById('backendUrl').value.trim();
      const filePath   = document.getElementById('filePath').value.trim();
      const dirPath    = document.getElementById('dirPath').value.trim();
      if (!filePath) { showStatus('gen', 'error', 'Select a Python file first'); return; }
      setLoading('gen', true);
      clearStatus('gen');
      document.getElementById('gen-results').classList.remove('show');
      vscode.postMessage({ type: 'generateTests', filePath, dirPath, backendUrl });
    }

    // ── Refactor ──────────────────────────────────────────
    let currentRefactorPath = '';

    function refactorCode() {
      const backendUrl = document.getElementById('refactorBackendUrl').value.trim();
      if (!currentRefactorPath) { showStatus('ref', 'error', 'No Python file open'); return; }
      setLoading('ref', true);
      clearStatus('ref');
      vscode.postMessage({ type: 'refactorCode', filePath: currentRefactorPath, backendUrl });
    }

    function updateRefactorFile(filePath) {
      currentRefactorPath = filePath || '';
      const pathEl = document.getElementById('rfc-path');
      const badge  = document.getElementById('rfc-badge');
      const btn    = document.getElementById('refactorBtn');

      if (filePath) {
        const fileName = filePath.split(/[\\\\/]/).pop();
        pathEl.textContent = filePath;
        pathEl.classList.remove('empty');
        badge.textContent  = fileName;
        badge.className    = 'rfc-badge';
        btn.disabled       = false;
      } else {
        pathEl.textContent = 'No Python file open';
        pathEl.classList.add('empty');
        badge.textContent  = 'none';
        badge.className    = 'rfc-badge none';
        btn.disabled       = true;
      }
    }

    // ── Helpers ───────────────────────────────────────────
    function setLoading(panel, on) {
      document.getElementById(panel === 'gen' ? 'gen-loading' : 'ref-loading').classList.toggle('active', on);
      document.getElementById(panel === 'gen' ? 'generateBtn' : 'refactorBtn').disabled = on;
    }

    function showStatus(panel, type, msg) {
      const el = document.getElementById(panel + '-status');
      el.className = 'status show ' + type;
      document.getElementById(panel + '-status-text').textContent = msg;
    }

    function clearStatus(panel) {
      document.getElementById(panel + '-status').className = 'status';
    }

    function escapeHtml(t) {
      const d = document.createElement('div');
      d.textContent = t;
      return d.innerHTML;
    }

    function scoreClass(pct) {
      if (pct >= 70) return 'good';
      if (pct >= 40) return 'warn';
      return 'bad';
    }

    // ── Messages from extension ────────────────────────────
    window.addEventListener('message', event => {
      const msg = event.data;
      switch (msg.type) {

        case 'fileSelected':
          document.getElementById('filePath').value = msg.filePath;
          document.getElementById('dirPath').value  = msg.dirPath;
          document.getElementById('generateBtn').disabled = false;
          showStatus('gen', 'info', 'Ready: ' + msg.fileName);
          break;

        case 'generationStarted':
          showStatus('gen', 'info', msg.message);
          break;

        case 'generationComplete': {
          setLoading('gen', false);
          const r = msg.result;
          showStatus('gen', 'success', 'Tests generated successfully');
          const mutPct = Math.round((r.mutation_score || 0) * 100);
          const covPct = Math.round((r.coverage || 0) * 100);
          const mutEl  = document.getElementById('res-mutation');
          const covEl  = document.getElementById('res-coverage');
          mutEl.textContent = mutPct + '%';
          mutEl.className   = 'm-value ' + scoreClass(mutPct);
          covEl.textContent = covPct + '%';
          covEl.className   = 'm-value ' + scoreClass(covPct);
          document.getElementById('res-code').innerHTML = escapeHtml(r.tests || '');
          document.getElementById('gen-results').classList.add('show');
          break;
        }

        case 'generationError':
          setLoading('gen', false);
          document.getElementById('generateBtn').disabled = false;
          showStatus('gen', 'error', msg.error);
          break;

        case 'activeFileChanged':
          updateRefactorFile(msg.filePath || '');
          break;

        case 'refactorStarted':
          showStatus('ref', 'info', msg.message);
          break;

        case 'refactorComplete':
          setLoading('ref', false);
          document.getElementById('refactorBtn').disabled = false;
          showStatus('ref', 'success', msg.message || 'Done');
          break;

        case 'refactorError':
          setLoading('ref', false);
          document.getElementById('refactorBtn').disabled = false;
          showStatus('ref', 'error', msg.error);
          break;
      }
    });

    // Request the current active file on load
    vscode.postMessage({ type: 'requestActiveFile' });
  </script>
</body>
</html>`;
  }
}

export function deactivate() {}
