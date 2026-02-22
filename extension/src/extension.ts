import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import axios from "axios";

export function activate(context: vscode.ExtensionContext) {
  const provider = new TestGeneratorViewProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      TestGeneratorViewProvider.viewType,
      provider
    )
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("pynguin-test-gen.openView", () => {
      vscode.commands.executeCommand(
        "workbench.view.extension.pynguin-test-gen-container"
      );
    })
  );

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && editor.document.uri.fsPath.endsWith(".py")) {
        provider.notifyActiveFileChanged(editor.document.uri.fsPath);
      }
    })
  );
}

class TestGeneratorViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "pynguin-test-gen.testGeneratorView";
  private _view?: vscode.WebviewView;

  constructor(private readonly _extensionUri: vscode.Uri) {}

  public notifyActiveFileChanged(filePath: string) {
    this._view?.webview.postMessage({ type: "activeFileChanged", filePath });
  }

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };
    webviewView.webview.html = this._getHtml(webviewView.webview);

    // Push active file on load
    const active = vscode.window.activeTextEditor;
    if (active?.document.uri.fsPath.endsWith(".py")) {
      setTimeout(
        () => this.notifyActiveFileChanged(active.document.uri.fsPath),
        300
      );
    }

    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case "requestActiveFile": {
          const ed = vscode.window.activeTextEditor;
          if (ed?.document.uri.fsPath.endsWith(".py"))
            this.notifyActiveFileChanged(ed.document.uri.fsPath);
          break;
        }
        case "pickSingleFile":
          await this.pickSingleFile(msg.rootFolder);
          break;
        case "pickMultipleFiles":
          await this.pickMultipleFiles();
          break;
        case "pickZipFile":
          await this.pickZipFile();
          break;
        case "generateSingle":
          await this.handleSingleGeneration(
            msg.filePath,
            msg.dirPath,
            msg.backendUrl
          );
          break;
        case "generateMultiple":
          await this.handleMultipleGeneration(msg.filePaths, msg.backendUrl);
          break;
        case "generateZip":
          await this.handleZipGeneration(msg.zipPath, msg.backendUrl);
          break;
        case "pollJob":
          await this.pollJob(msg.jobId, msg.backendUrl);
          break;
        case "refactorCode":
          await this.handleRefactoring(msg.filePath, msg.backendUrl);
          break;
      }
    });
  }

  // ── File pickers ────────────────────────────────────────────────────────

  private async pickSingleFile(rootFolder?: string) {
    const defaultUri = rootFolder
      ? vscode.Uri.file(rootFolder)
      : vscode.workspace.workspaceFolders?.[0]?.uri;

    const uris = await vscode.window.showOpenDialog({
      defaultUri,
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { "Python Files": ["py"] },
      openLabel: "Select Python File",
    });
    if (uris?.[0]) {
      this._view?.webview.postMessage({
        type: "singleFilePicked",
        filePath: uris[0].fsPath,
        dirPath: path.dirname(uris[0].fsPath),
        fileName: path.basename(uris[0].fsPath),
      });
    }
  }

  private async pickMultipleFiles() {
    const uris = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: true,
      filters: { "Python Files": ["py"] },
      openLabel: "Select Python Files",
    });
    if (uris?.length) {
      this._view?.webview.postMessage({
        type: "multipleFilesPicked",
        filePaths: uris.map((u) => u.fsPath),
        fileNames: uris.map((u) => path.basename(u.fsPath)),
      });
    }
  }

  private async pickZipFile() {
    const uris = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { "ZIP Archives": ["zip"] },
      openLabel: "Select ZIP Archive",
    });
    if (uris?.[0]) {
      this._view?.webview.postMessage({
        type: "zipFilePicked",
        zipPath: uris[0].fsPath,
        zipName: path.basename(uris[0].fsPath),
      });
    }
  }

  // ── Generation handlers ─────────────────────────────────────────────────

  private async handleSingleGeneration(
    filePath: string,
    dirPath: string,
    backendUrl: string
  ) {
    const moduleName = path.basename(filePath, ".py");
    this._view?.webview.postMessage({
      type: "generationStarted",
      scope: "single",
    });
    try {
      const code = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.file(filePath))
      ).toString("utf8");

      const { data } = await axios.post(
        `${backendUrl}/generate-tests`,
        { code, module_name: moduleName, directory: dirPath, file_path: filePath },
        { timeout: 300000 }
      );

      this._view?.webview.postMessage({
        type: "generationComplete",
        scope: "single",
        result: data,
      });

      if (data.tests) await this.saveTestFile(dirPath, moduleName, data.tests);
    } catch (err) {
      this._view?.webview.postMessage({
        type: "generationError",
        scope: "single",
        error: this.extractError(err, backendUrl),
      });
    }
  }

  private async handleMultipleGeneration(
    filePaths: string[],
    backendUrl: string
  ) {
    this._view?.webview.postMessage({
      type: "generationStarted",
      scope: "multiple",
    });

    const results: any[] = [];
    for (let i = 0; i < filePaths.length; i++) {
      const fp = filePaths[i];
      const moduleName = path.basename(fp, ".py");
      const dirPath = path.dirname(fp);

      this._view?.webview.postMessage({
        type: "multiProgress",
        current: i + 1,
        total: filePaths.length,
        fileName: path.basename(fp),
      });

      try {
        const code = Buffer.from(
          await vscode.workspace.fs.readFile(vscode.Uri.file(fp))
        ).toString("utf8");

        const { data } = await axios.post(
          `${backendUrl}/generate-tests`,
          { code, module_name: moduleName, directory: dirPath, file_path: fp },
          { timeout: 300000 }
        );

        results.push({
          file: path.basename(fp),
          status: "success",
          tests: data.tests,
          coverage: data.coverage,
          mutation_score: data.mutation_score,
          dirPath,
          moduleName,
        });

        if (data.tests) await this.saveTestFile(dirPath, moduleName, data.tests, false);
      } catch (err) {
        results.push({
          file: path.basename(fp),
          status: "failed",
          error: this.extractError(err, backendUrl),
        });
      }
    }

    this._view?.webview.postMessage({
      type: "multipleComplete",
      results,
    });
  }

  private async handleZipGeneration(zipPath: string, backendUrl: string) {
    this._view?.webview.postMessage({
      type: "generationStarted",
      scope: "zip",
    });
    try {
      // Read ZIP as a Node Buffer — no Blob/FormData needed
      const zipBuffer = fs.readFileSync(zipPath);
      const fileName  = path.basename(zipPath);

      // Build a minimal multipart/form-data body manually
      const boundary = `----CodBoundary${Date.now()}`;
      const CRLF     = "\r\n";

      const header = Buffer.from(
        `--${boundary}${CRLF}` +
        `Content-Disposition: form-data; name="file"; filename="${fileName}"${CRLF}` +
        `Content-Type: application/zip${CRLF}${CRLF}`
      );
      const footer = Buffer.from(`${CRLF}--${boundary}--${CRLF}`);
      const body   = Buffer.concat([header, zipBuffer, footer]);

      const { data } = await axios.post(`${backendUrl}/analyze_zip`, body, {
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": body.length,
        },
        timeout: 30000,
      });

      this._view?.webview.postMessage({
        type: "zipJobStarted",
        jobId: data.job_id,
        backendUrl,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "generationError",
        scope: "zip",
        error: this.extractError(err, backendUrl),
      });
    }
  }

  private async pollJob(jobId: string, backendUrl: string) {
    try {
      const { data } = await axios.get(`${backendUrl}/status/${jobId}`, {
        timeout: 10000,
      });
      this._view?.webview.postMessage({ type: "jobStatus", status: data });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "jobStatus",
        status: { status: "error", error: "Could not reach backend" },
      });
    }
  }

  private async handleRefactoring(filePath: string, backendUrl: string) {
    this._view?.webview.postMessage({ type: "refactorStarted" });
    try {
      const moduleName = path.basename(filePath, ".py");
      const code = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.file(filePath))
      ).toString("utf8");

      const { data } = await axios.post(
        `${backendUrl}/refactor`,
        { code, module_name: moduleName, file_path: filePath },
        { timeout: 300000 }
      );

      this._view?.webview.postMessage({ type: "refactorComplete", result: data });

      // Offer to overwrite the file with refactored code
      if (data.refactored_code) {
        const answer = await vscode.window.showInformationMessage(
          `Overwrite ${path.basename(filePath)} with refactored version?`,
          "Yes",
          "Save as new file",
          "No"
        );
        if (answer === "Yes") {
          await vscode.workspace.fs.writeFile(
            vscode.Uri.file(filePath),
            Buffer.from(data.refactored_code, "utf8")
          );
          vscode.window.showInformationMessage("File refactored successfully.");
        } else if (answer === "Save as new file") {
          const dir = path.dirname(filePath);
          const base = path.basename(filePath, ".py");
          const newPath = path.join(dir, `${base}_refactored.py`);
          await vscode.workspace.fs.writeFile(
            vscode.Uri.file(newPath),
            Buffer.from(data.refactored_code, "utf8")
          );
          const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(newPath));
          await vscode.window.showTextDocument(doc);
        }
      }
    } catch (err) {
      this._view?.webview.postMessage({
        type: "refactorError",
        error: this.extractError(err, backendUrl),
      });
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────

  private async saveTestFile(
    dirPath: string,
    moduleName: string,
    testCode: string,
    prompt = true
  ) {
    const testFileName = `test_${moduleName}.py`;
    const testFilePath = path.join(dirPath, testFileName);

    let save = !prompt;
    if (prompt) {
      const answer = await vscode.window.showInformationMessage(
        `Save ${testFileName}?`,
        "Yes",
        "No"
      );
      save = answer === "Yes";
    }

    if (save) {
      await vscode.workspace.fs.writeFile(
        vscode.Uri.file(testFilePath),
        Buffer.from(testCode, "utf8")
      );
      if (prompt) {
        const doc = await vscode.workspace.openTextDocument(
          vscode.Uri.file(testFilePath)
        );
        await vscode.window.showTextDocument(doc);
      }
    }
  }

  private extractError(err: any, backendUrl: string): string {
    if (axios.isAxiosError(err)) {
      if (err.response?.data?.detail?.error)
        return err.response.data.detail.error;
      if (err.code === "ECONNREFUSED")
        return `Cannot connect to backend at ${backendUrl}`;
      if (err.code === "ECONNABORTED") return "Request timed out";
      return err.message;
    }
    return err instanceof Error ? err.message : "Unknown error";
  }

  // ── HTML ─────────────────────────────────────────────────────────────────

  private _getHtml(_webview: vscode.Webview): string {
    return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Codexter</title>
<style>
/* ─── Reset ───────────────────────────────────────────────── */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

/* ─── Design tokens ───────────────────────────────────────── */
:root{
  --bg:       #0c0c10;
  --surf:     #111118;
  --surf2:    #16161f;
  --bd:       #1c1c2a;
  --bd2:      #242436;
  --accent:   #7c6ef5;
  --accent2:  #a899f8;
  --aclo:     rgba(124,110,245,0.10);
  --acbd:     rgba(124,110,245,0.24);
  --green:    #3ecf6e;
  --greenlo:  rgba(62,207,110,0.09);
  --greenbd:  rgba(62,207,110,0.22);
  --amber:    #f5a623;
  --red:      #f07070;
  --redlo:    rgba(240,112,112,0.09);
  --redbd:    rgba(240,112,112,0.22);
  --text:     #ddddf0;
  --muted:    #5a5a7a;
  --muted2:   #3a3a58;
  --mono:     'Cascadia Code','Cascadia Mono','Fira Code','Consolas','Courier New',monospace;
  --sans:     var(--vscode-font-family,'Segoe UI','SF Pro Display',system-ui,sans-serif);
  --r:        7px;
  --ease:     cubic-bezier(.4,0,.2,1);
}

/* ─── Base ────────────────────────────────────────────────── */
html,body{
  background:var(--bg);color:var(--text);
  font-family:var(--mono);font-size:11.5px;line-height:1.5;
  overflow-x:hidden;overflow-y:auto;min-height:100vh;
}

/* ─── Header ──────────────────────────────────────────────── */
.hdr{
  padding:15px 15px 0;
  opacity:0;animation:fdown .38s var(--ease) .04s forwards;
}
.wordmark{
  font-family:var(--sans);font-size:14px;font-weight:700;
  letter-spacing:.03em;display:flex;align-items:center;gap:8px;
}
.pulse-dot{
  width:7px;height:7px;border-radius:50%;
  background:var(--accent);box-shadow:0 0 9px var(--accent);
  animation:pulse 2.6s ease-in-out infinite;flex-shrink:0;
}
.tagline{
  font-size:9.5px;color:var(--muted);margin-top:3px;
  letter-spacing:.09em;text-transform:uppercase;
}

/* ─── Outer tabs (Test Gen / Refactor) ────────────────────── */
.outer-tabs{
  display:flex;gap:2px;margin:14px 15px 0;
  background:var(--surf);border:1px solid var(--bd);
  border-radius:var(--r);padding:3px;
  opacity:0;animation:fdown .38s var(--ease) .1s forwards;
}
.otab{
  flex:1;padding:7px 4px;border:none;background:transparent;
  color:var(--muted);font-family:var(--mono);font-size:11px;
  font-weight:500;letter-spacing:.04em;cursor:pointer;
  border-radius:5px;transition:all .18s var(--ease);
}
.otab:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.otab.on{
  background:var(--aclo);color:var(--accent2);
  border:1px solid var(--acbd);
}

/* ─── Main panels ─────────────────────────────────────────── */
.mpanel{display:none;padding:14px 15px 0}
.mpanel.on{display:block;animation:fup .22s var(--ease) forwards}

/* ─── Inner sub-tabs (Single / Multiple / Codebase) ──────── */
.inner-tabs-wrap{
  background:var(--surf2);border:1px solid var(--bd);
  border-radius:var(--r);padding:3px;
  display:flex;gap:2px;margin-bottom:14px;
}
.itab{
  flex:1;padding:5px 2px;border:none;background:transparent;
  color:var(--muted);font-family:var(--mono);font-size:10px;
  font-weight:500;letter-spacing:.05em;cursor:pointer;
  border-radius:4px;transition:all .17s var(--ease);
  white-space:nowrap;
}
.itab:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.itab.on{
  background:rgba(255,255,255,.06);color:var(--text);
  border:1px solid var(--bd2);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
}

/* ─── Sub-panels ──────────────────────────────────────────── */
.spanel{display:none}
.spanel.on{display:block;animation:fup .2s var(--ease) forwards;padding-bottom:24px}

/* ─── Backend row ─────────────────────────────────────────── */
.backend-row{margin-bottom:12px}

/* ─── Labels ──────────────────────────────────────────────── */
.lbl{
  font-size:9px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);margin-bottom:5px;display:flex;align-items:center;gap:5px;
}
.lbl-badge{
  font-size:8.5px;padding:1px 5px;border-radius:20px;
  background:var(--aclo);color:var(--accent2);
  border:1px solid var(--acbd);letter-spacing:.04em;
}
.lbl-badge.green{
  background:var(--greenlo);color:var(--green);border-color:var(--greenbd);
}

/* ─── Input ───────────────────────────────────────────────── */
input[type=text]{
  width:100%;padding:7px 9px;
  background:var(--surf);color:var(--text);
  border:1px solid var(--bd);border-radius:var(--r);
  font-family:var(--mono);font-size:11px;outline:none;
  transition:border-color .17s,box-shadow .17s;
}
input[type=text]:focus{
  border-color:rgba(124,110,245,.45);
  box-shadow:0 0 0 3px rgba(124,110,245,.08);
}
input[type=text][readonly],input[type=text].dim{opacity:.6;cursor:default}
input[type=text]::placeholder{color:var(--muted2)}

/* ─── File chip / card ────────────────────────────────────── */
.file-card{
  background:var(--surf);border:1px solid var(--bd);
  border-radius:var(--r);padding:10px 12px;
  display:flex;align-items:flex-start;gap:9px;
  transition:border-color .17s;
}
.file-card.active{border-color:var(--acbd)}
.file-card.green-active{border-color:var(--greenbd)}
.fc-icon{font-size:15px;flex-shrink:0;line-height:1;padding-top:1px}
.fc-body{flex:1;min-width:0}
.fc-name{font-size:11px;color:var(--text);word-break:break-all;line-height:1.4}
.fc-name.empty{color:var(--muted);font-style:italic}
.fc-sub{font-size:9.5px;color:var(--muted);margin-top:3px;word-break:break-all}

/* ─── File list (multiple) ────────────────────────────────── */
.file-list{
  background:var(--surf);border:1px solid var(--bd);
  border-radius:var(--r);max-height:130px;overflow-y:auto;
}
.file-list:empty::before{
  content:'No files selected';color:var(--muted);font-style:italic;
  font-size:11px;display:block;padding:10px 12px;
}
.fli{
  display:flex;align-items:center;gap:8px;
  padding:7px 12px;border-bottom:1px solid var(--bd);
  font-size:11px;
}
.fli:last-child{border-bottom:none}
.fli-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fli-dir{font-size:9.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fli-status{font-size:10px;flex-shrink:0}

/* ─── Buttons ─────────────────────────────────────────────── */
.btn{
  display:flex;align-items:center;justify-content:center;gap:6px;
  width:100%;padding:9px;border:none;border-radius:var(--r);
  font-family:var(--mono);font-size:11px;font-weight:600;
  letter-spacing:.04em;cursor:pointer;
  transition:all .18s var(--ease);position:relative;overflow:hidden;
}
.btn::after{
  content:'';position:absolute;inset:0;
  background:#fff;opacity:0;transition:opacity .13s;
}
.btn:active:not(:disabled)::after{opacity:.05}
.btn:disabled{opacity:.32;cursor:not-allowed;transform:none !important;box-shadow:none !important}

.btn-violet{
  background:linear-gradient(135deg,var(--accent),#9b8af8);color:#fff;
  box-shadow:0 3px 14px rgba(124,110,245,.3);
}
.btn-violet:hover:not(:disabled){
  box-shadow:0 5px 20px rgba(124,110,245,.44);transform:translateY(-1px);
}

.btn-green{
  background:linear-gradient(135deg,#16a34a,var(--green));color:#051a0e;
  box-shadow:0 3px 14px rgba(62,207,110,.22);
}
.btn-green:hover:not(:disabled){
  box-shadow:0 5px 20px rgba(62,207,110,.36);transform:translateY(-1px);
}

.btn-ghost{
  background:var(--surf);color:var(--muted);
  border:1px solid var(--bd);width:auto;
  padding:7px 11px;font-size:11px;
}
.btn-ghost:hover{color:var(--text);border-color:var(--bd2)}

/* ─── Row helpers ─────────────────────────────────────────── */
.row{display:flex;gap:8px;align-items:flex-end;margin-bottom:12px}
.row .fld{flex:1;margin:0}
.mb{margin-bottom:12px}
.mb-sm{margin-bottom:8px}
.mt{margin-top:12px}
.fld{margin-bottom:12px}

/* ─── Divider ─────────────────────────────────────────────── */
.divider{height:1px;background:var(--bd);margin:12px 0}

/* ─── Loader ──────────────────────────────────────────────── */
.loader{
  display:none;flex-direction:column;
  align-items:center;gap:10px;padding:18px 0 8px;
}
.loader.on{display:flex}
.ring{
  width:22px;height:22px;border-radius:50%;
  border:2px solid var(--bd2);border-top-color:var(--accent);
  animation:spin .7s linear infinite;
}
.ring.green{border-top-color:var(--green)}
.loader-txt{font-size:10px;color:var(--muted);letter-spacing:.06em}

/* ─── Status pill ─────────────────────────────────────────── */
.pill{
  display:none;align-items:center;gap:7px;
  padding:8px 11px;border-radius:var(--r);font-size:11px;
}
.pill.on{display:flex;animation:fup .2s var(--ease) forwards}
.pdot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.pill.info  {background:var(--aclo);border:1px solid var(--acbd);color:var(--accent2)}
.pill.info  .pdot{background:var(--accent);box-shadow:0 0 6px var(--accent);animation:pulse 1.4s ease-in-out infinite}
.pill.ok    {background:var(--greenlo);border:1px solid var(--greenbd);color:var(--green)}
.pill.ok    .pdot{background:var(--green)}
.pill.err   {background:var(--redlo);border:1px solid var(--redbd);color:var(--red)}
.pill.err   .pdot{background:var(--red)}

/* ─── Progress bar ────────────────────────────────────────── */
.progress-wrap{
  background:var(--surf2);border:1px solid var(--bd);border-radius:20px;
  height:5px;overflow:hidden;margin-bottom:6px;
}
.progress-bar{
  height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));
  border-radius:20px;transition:width .4s var(--ease);width:0%;
}
.progress-label{font-size:9.5px;color:var(--muted);text-align:center;margin-bottom:8px}

/* ─── Results card ────────────────────────────────────────── */
.result-card{
  display:none;margin-top:16px;
  background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  overflow:hidden;
}
.result-card.on{display:block;animation:fup .26s var(--ease) forwards}
.rc-hdr{
  padding:8px 12px;border-bottom:1px solid var(--bd);
  display:flex;align-items:center;justify-content:space-between;
}
.rc-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.rc-time{font-size:9px;color:var(--muted2)}

.metrics{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--bd)}
.met{background:var(--surf);padding:9px 12px}
.met-lbl{font-size:8.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-bottom:3px}
.met-val{font-family:var(--sans);font-size:17px;font-weight:700;letter-spacing:-.02em}
.met-val.g{color:var(--green)}.met-val.a{color:var(--amber)}.met-val.r{color:var(--red)}.met-val.d{color:var(--muted)}

.rc-code{padding:11px 12px;max-height:220px;overflow-y:auto}
.rc-code pre{font-size:10.5px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#bbbbd8}

/* ─── Multi results table ─────────────────────────────────── */
.multi-table{
  display:none;margin-top:16px;
  background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;
}
.multi-table.on{display:block;animation:fup .26s var(--ease) forwards}
.mt-hdr{padding:8px 12px;border-bottom:1px solid var(--bd)}
.mt-hdr-txt{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.mt-row{
  display:grid;grid-template-columns:1fr 56px 56px 56px;
  gap:6px;align-items:center;
  padding:7px 12px;border-bottom:1px solid var(--bd);font-size:10.5px;
}
.mt-row:last-child{border-bottom:none}
.mt-row.hd{font-size:9px;color:var(--muted);letter-spacing:.07em;text-transform:uppercase;background:var(--surf2)}
.mt-file{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mt-val{text-align:right}
.tag{
  display:inline-flex;align-items:center;justify-content:center;
  font-size:8.5px;padding:2px 6px;border-radius:4px;letter-spacing:.04em;
}
.tag.ok {background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd)}
.tag.err{background:var(--redlo);color:var(--red);border:1px solid var(--redbd)}

/* ─── ZIP result ──────────────────────────────────────────── */
.zip-result{
  display:none;margin-top:16px;
  background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  overflow:hidden;
}
.zip-result.on{display:block;animation:fup .26s var(--ease) forwards}
.zr-hdr{padding:8px 12px;border-bottom:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between}
.zr-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.zr-body{padding:10px 12px;max-height:220px;overflow-y:auto}
.zr-row{
  display:grid;grid-template-columns:1fr 56px 56px 60px;
  gap:6px;align-items:center;padding:5px 0;border-bottom:1px solid var(--bd);font-size:10.5px;
}
.zr-row:last-child{border-bottom:none}
.zr-row.hd{font-size:9px;color:var(--muted);letter-spacing:.07em;text-transform:uppercase}
.dl-link{color:var(--accent2);text-decoration:none;font-size:9.5px}
.dl-link:hover{color:var(--accent)}

/* ─── Refactor panel ──────────────────────────────────────── */
.ref-file-card{
  background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);
  padding:11px 13px;margin-bottom:13px;
  display:flex;align-items:flex-start;gap:9px;
}
.ref-icon{font-size:16px;flex-shrink:0;line-height:1;padding-top:1px}
.ref-body{flex:1;min-width:0}
.ref-name{font-size:11px;color:var(--text);word-break:break-all;line-height:1.4}
.ref-name.empty{color:var(--muted);font-style:italic}
.ref-sub{font-size:9.5px;color:var(--muted);margin-top:3px}

.ref-result{
  display:none;margin-top:16px;
  background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;
}
.ref-result.on{display:block;animation:fup .26s var(--ease) forwards}
.ref-summary{padding:11px 12px;font-size:10.5px;line-height:1.7;color:#c4c4e0;border-bottom:1px solid var(--bd);white-space:pre-wrap}

/* ─── Scrollbar ───────────────────────────────────────────── */
::-webkit-scrollbar{width:3px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:3px}

/* ─── Animations ──────────────────────────────────────────── */
@keyframes fdown{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
@keyframes fup  {from{opacity:0;transform:translateY(7px)} to{opacity:1;transform:translateY(0)}}
@keyframes spin {to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
</style>
</head>
<body>

<!-- ── Header ──────────────────────────────────────────────── -->
<div class="hdr">
  <div class="wordmark"><span class="pulse-dot"></span>Codexter</div>
  <div class="tagline">AI-powered test &amp; refactor</div>
</div>

<!-- ── Outer tabs ──────────────────────────────────────────── -->
<div class="outer-tabs">
  <button class="otab on" onclick="oSwitch('testgen',this)">⬡ Test Gen</button>
  <button class="otab"     onclick="oSwitch('refactor',this)">⟳ Refactor</button>
</div>

<!-- ════════════════════════════════════════════════════════ -->
<!-- OUTER PANEL: Test Generation                           -->
<!-- ════════════════════════════════════════════════════════ -->
<div class="mpanel on" id="mp-testgen">

  <!-- Backend URL (shared) -->
  <div class="fld backend-row">
    <div class="lbl">Backend URL</div>
    <input type="text" id="backendUrl" value="http://localhost:8000"/>
  </div>

  <!-- Inner tabs -->
  <div class="inner-tabs-wrap">
    <button class="itab on" onclick="iSwitch('single',this)">Single File</button>
    <button class="itab"    onclick="iSwitch('multi',this)">Multiple Files</button>
    <button class="itab"    onclick="iSwitch('zip',this)">Codebase</button>
  </div>

  <!-- ────────── Sub-panel: Single File ────────── -->
  <div class="spanel on" id="sp-single">

    <div class="fld">
      <div class="lbl">
        Python File
        <span class="lbl-badge" id="sf-auto-badge" style="display:none">auto</span>
      </div>
      <div class="file-card" id="sf-card">
        <div class="fc-icon">🐍</div>
        <div class="fc-body">
          <div class="fc-name empty" id="sf-name">Open a .py file or browse below</div>
          <div class="fc-sub" id="sf-dir"></div>
        </div>
      </div>
    </div>

    <div class="row mb">
      <button class="btn btn-ghost" onclick="pickSingle()">Browse other file</button>
    </div>

    <button class="btn btn-violet" id="btn-single" onclick="genSingle()" disabled>
      ⬡ Generate Tests
    </button>

    <div class="loader" id="ld-single">
      <div class="ring"></div>
      <span class="loader-txt">Running pipeline…</span>
    </div>
    <div class="pill" id="pill-single"><span class="pdot"></span><span id="pill-single-txt"></span></div>

    <div class="result-card" id="rc-single">
      <div class="rc-hdr">
        <span class="rc-title">Results</span>
        <span class="rc-time" id="rc-single-time"></span>
      </div>
      <div class="metrics">
        <div class="met"><div class="met-lbl">Coverage</div><div class="met-val d" id="rc-cov">—</div></div>
        <div class="met"><div class="met-lbl">Mutation</div><div class="met-val d" id="rc-mut">—</div></div>
      </div>
      <div class="rc-code"><pre id="rc-code"></pre></div>
    </div>

  </div><!-- /sp-single -->

  <!-- ────────── Sub-panel: Multiple Files ────────── -->
  <div class="spanel" id="sp-multi">

    <div class="fld">
      <div class="lbl">Selected Files <span class="lbl-badge green" id="multi-count-badge" style="display:none"></span></div>
      <div class="file-list" id="multi-file-list"></div>
    </div>

    <div class="row mb">
      <button class="btn btn-ghost" onclick="pickMulti()">Add / change files</button>
    </div>

    <button class="btn btn-violet" id="btn-multi" onclick="genMulti()" disabled>
      ⬡ Generate Tests for All
    </button>

    <div class="loader" id="ld-multi">
      <div class="ring"></div>
      <span class="loader-txt" id="ld-multi-txt">Processing…</span>
    </div>
    <div class="progress-wrap" id="multi-prog-wrap" style="display:none">
      <div class="progress-bar" id="multi-prog-bar"></div>
    </div>
    <div class="progress-label" id="multi-prog-lbl" style="display:none"></div>
    <div class="pill" id="pill-multi"><span class="pdot"></span><span id="pill-multi-txt"></span></div>

    <div class="multi-table" id="mt-table">
      <div class="mt-hdr"><span class="mt-hdr-txt">File Results</span></div>
      <div class="mt-row hd">
        <div>File</div><div class="mt-val">Cov</div><div class="mt-val">Mut</div><div class="mt-val">Status</div>
      </div>
      <div id="mt-rows"></div>
    </div>

  </div><!-- /sp-multi -->

  <!-- ────────── Sub-panel: Codebase (ZIP) ────────── -->
  <div class="spanel" id="sp-zip">

    <div class="fld">
      <div class="lbl">ZIP Archive</div>
      <div class="file-card" id="zip-card">
        <div class="fc-icon">📦</div>
        <div class="fc-body">
          <div class="fc-name empty" id="zip-name">No archive selected</div>
          <div class="fc-sub" id="zip-sub"></div>
        </div>
      </div>
    </div>

    <div class="row mb">
      <button class="btn btn-ghost" onclick="pickZip()">Browse ZIP</button>
    </div>

    <button class="btn btn-violet" id="btn-zip" onclick="genZip()" disabled>
      ⬡ Analyse Codebase
    </button>

    <div class="loader" id="ld-zip">
      <div class="ring"></div>
      <span class="loader-txt" id="ld-zip-txt">Uploading…</span>
    </div>
    <div class="progress-wrap" id="zip-prog-wrap" style="display:none">
      <div class="progress-bar" id="zip-prog-bar"></div>
    </div>
    <div class="progress-label" id="zip-prog-lbl" style="display:none"></div>
    <div class="pill" id="pill-zip"><span class="pdot"></span><span id="pill-zip-txt"></span></div>

    <div class="zip-result" id="zr-main">
      <div class="zr-hdr">
        <span class="zr-title">Codebase Results</span>
        <a class="dl-link" id="zr-dl" href="#" style="display:none">↓ Download All Tests</a>
      </div>
      <div class="zr-body">
        <div class="zr-row hd">
          <div>File</div><div class="mt-val">Cov%</div><div class="mt-val">Mut</div><div class="mt-val">Status</div>
        </div>
        <div id="zr-rows"></div>
      </div>
    </div>

  </div><!-- /sp-zip -->

</div><!-- /mp-testgen -->

<!-- ════════════════════════════════════════════════════════ -->
<!-- OUTER PANEL: Refactor                                  -->
<!-- ════════════════════════════════════════════════════════ -->
<div class="mpanel" id="mp-refactor">

  <div class="fld backend-row">
    <div class="lbl">Backend URL</div>
    <input type="text" id="refBackendUrl" value="http://localhost:8000"/>
  </div>

  <div class="divider"></div>

  <div class="lbl">Active File <span class="lbl-badge" id="ref-auto-badge">auto</span></div>
  <div class="ref-file-card mb">
    <div class="ref-icon">🐍</div>
    <div class="ref-body">
      <div class="ref-name empty" id="ref-name">Open a Python file in the editor</div>
      <div class="ref-sub" id="ref-sub"></div>
    </div>
  </div>

  <button class="btn btn-green" id="btn-refactor" onclick="doRefactor()" disabled>
    ⟳ Refactor Code
  </button>

  <div class="loader" id="ld-ref">
    <div class="ring green"></div>
    <span class="loader-txt">Analysing &amp; refactoring…</span>
  </div>
  <div class="pill" id="pill-ref"><span class="pdot"></span><span id="pill-ref-txt"></span></div>

  <div class="ref-result" id="ref-result">
    <div class="rc-hdr">
      <span class="rc-title">Refactor Summary</span>
    </div>
    <div class="ref-summary" id="ref-summary"></div>
  </div>

</div><!-- /mp-refactor -->

<script>
const vscode = acquireVsCodeApi();

/* ── State ─────────────────────────────────────────── */
let singleFilePath = '';
let singleDirPath  = '';
let multiFilePaths = [];
let zipFilePath    = '';
let refactorPath   = '';
let zipJobId       = '';
let zipPollTimer   = null;

/* ── Tab switching ─────────────────────────────────── */
function oSwitch(id, btn) {
  document.querySelectorAll('.otab').forEach(t => t.classList.remove('on'));
  document.querySelectorAll('.mpanel').forEach(p => p.classList.remove('on'));
  btn.classList.add('on');
  document.getElementById('mp-' + id).classList.add('on');
}

function iSwitch(id, btn) {
  document.querySelectorAll('.itab').forEach(t => t.classList.remove('on'));
  document.querySelectorAll('.spanel').forEach(p => p.classList.remove('on'));
  btn.classList.add('on');
  document.getElementById('sp-' + id).classList.add('on');
}

/* ── Single file ───────────────────────────────────── */
function pickSingle() {
  vscode.postMessage({ type: 'pickSingleFile', rootFolder: singleDirPath });
}

function setSingleFile(fp, dir, name) {
  singleFilePath = fp;
  singleDirPath  = dir || fp.replace(/[\\/][^\\/]+$/, '');
  const nameEl = document.getElementById('sf-name');
  const dirEl  = document.getElementById('sf-dir');
  const card   = document.getElementById('sf-card');
  nameEl.textContent = name || fp.split(/[\\/]/).pop();
  nameEl.classList.remove('empty');
  dirEl.textContent = singleDirPath;
  card.classList.add('active');
  document.getElementById('btn-single').disabled = false;
}

function genSingle() {
  if (!singleFilePath) { showPill('single','err','No file selected'); return; }
  const backendUrl = document.getElementById('backendUrl').value.trim();
  setLoader('single', true);
  hidePill('single');
  document.getElementById('rc-single').classList.remove('on');
  document.getElementById('btn-single').disabled = true;
  vscode.postMessage({ type:'generateSingle', filePath:singleFilePath, dirPath:singleDirPath, backendUrl });
}

/* ── Multiple files ────────────────────────────────── */
function pickMulti() {
  vscode.postMessage({ type: 'pickMultipleFiles' });
}

function setMultiFiles(paths, names) {
  multiFilePaths = paths;
  const list = document.getElementById('multi-file-list');
  list.innerHTML = '';
  paths.forEach((fp, i) => {
    const dir = fp.replace(/[\\/][^\\/]+$/, '');
    const li = document.createElement('div');
    li.className = 'fli';
    li.innerHTML = \`<span class="fli-status">🐍</span>
      <div style="flex:1;min-width:0">
        <div class="fli-name">\${esc(names[i])}</div>
        <div class="fli-dir">\${esc(dir)}</div>
      </div>\`;
    list.appendChild(li);
  });
  const badge = document.getElementById('multi-count-badge');
  badge.textContent = paths.length + ' file' + (paths.length !== 1 ? 's' : '');
  badge.style.display = '';
  document.getElementById('btn-multi').disabled = paths.length === 0;
}

function genMulti() {
  if (!multiFilePaths.length) { showPill('multi','err','No files selected'); return; }
  const backendUrl = document.getElementById('backendUrl').value.trim();
  setLoader('multi', true);
  hidePill('multi');
  document.getElementById('mt-table').classList.remove('on');
  document.getElementById('btn-multi').disabled = true;
  showMultiProgress(0, multiFilePaths.length, '');
  vscode.postMessage({ type:'generateMultiple', filePaths:multiFilePaths, backendUrl });
}

function showMultiProgress(cur, total, file) {
  const pct = total > 0 ? Math.round((cur / total) * 100) : 0;
  document.getElementById('multi-prog-wrap').style.display = 'block';
  document.getElementById('multi-prog-lbl').style.display = 'block';
  document.getElementById('multi-prog-bar').style.width = pct + '%';
  document.getElementById('multi-prog-lbl').textContent =
    file ? \`\${cur}/\${total} — \${file}\` : \`0/\${total} queued\`;
}

/* ── ZIP ───────────────────────────────────────────── */
function pickZip() {
  vscode.postMessage({ type: 'pickZipFile' });
}

function genZip() {
  if (!zipFilePath) { showPill('zip','err','No ZIP selected'); return; }
  const backendUrl = document.getElementById('backendUrl').value.trim();
  setLoader('zip', true, 'Uploading ZIP…');
  hidePill('zip');
  document.getElementById('zr-main').classList.remove('on');
  document.getElementById('btn-zip').disabled = true;
  document.getElementById('zip-prog-wrap').style.display = 'none';
  document.getElementById('zip-prog-lbl').style.display = 'none';
  vscode.postMessage({ type:'generateZip', zipPath:zipFilePath, backendUrl });
}

function startZipPolling(jobId, backendUrl) {
  zipJobId = jobId;
  if (zipPollTimer) clearInterval(zipPollTimer);
  zipPollTimer = setInterval(() => {
    vscode.postMessage({ type:'pollJob', jobId, backendUrl });
  }, 2000);
}

/* ── Refactor ──────────────────────────────────────── */
function doRefactor() {
  if (!refactorPath) { showPill('ref','err','No Python file open'); return; }
  const backendUrl = document.getElementById('refBackendUrl').value.trim();
  setLoader('ref', true);
  hidePill('ref');
  document.getElementById('ref-result').classList.remove('on');
  document.getElementById('btn-refactor').disabled = true;
  vscode.postMessage({ type:'refactorCode', filePath:refactorPath, backendUrl });
}

/* ── Shared helpers ────────────────────────────────── */
function setLoader(scope, on, msg) {
  const el = document.getElementById('ld-' + scope);
  el.classList.toggle('on', on);
  if (msg) el.querySelector('.loader-txt').textContent = msg;
}

function showPill(scope, type, msg) {
  const el = document.getElementById('pill-' + scope);
  el.className = 'pill on ' + type;
  document.getElementById('pill-' + scope + '-txt').textContent = msg;
}

function hidePill(scope) {
  document.getElementById('pill-' + scope).classList.remove('on');
}

function scoreClass(pct) {
  return pct >= 70 ? 'g' : pct >= 40 ? 'a' : 'r';
}

function esc(t) {
  const d = document.createElement('div');
  d.textContent = t;
  return d.innerHTML;
}

function ts() {
  return new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
}

/* ── Message handler ───────────────────────────────── */
window.addEventListener('message', ev => {
  const m = ev.data;
  switch(m.type) {

    /* Active editor changed → update single & refactor */
    case 'activeFileChanged': {
      const fp   = m.filePath || '';
      const name = fp.split(/[\\/]/).pop();
      const dir  = fp.replace(/[\\/][^\\/]+$/, '');

      // Single file — set as default if nothing chosen yet
      document.getElementById('sf-auto-badge').style.display = '';
      setSingleFile(fp, dir, name);

      // Refactor panel
      refactorPath = fp;
      const rn = document.getElementById('ref-name');
      rn.textContent = fp || 'No Python file open';
      rn.classList.toggle('empty', !fp);
      document.getElementById('ref-sub').textContent = fp ? dir : '';
      document.getElementById('btn-refactor').disabled = !fp;
      break;
    }

    /* Browse picked a different single file */
    case 'singleFilePicked':
      document.getElementById('sf-auto-badge').style.display = 'none';
      setSingleFile(m.filePath, m.dirPath, m.fileName);
      break;

    /* Multiple files picked */
    case 'multipleFilesPicked':
      setMultiFiles(m.filePaths, m.fileNames);
      break;

    /* ZIP picked */
    case 'zipFilePicked': {
      zipFilePath = m.zipPath;
      const zn = document.getElementById('zip-name');
      zn.textContent = m.zipName;
      zn.classList.remove('empty');
      document.getElementById('zip-sub').textContent = m.zipPath;
      document.getElementById('zip-card').classList.add('active');
      document.getElementById('btn-zip').disabled = false;
      break;
    }

    /* Generation started */
    case 'generationStarted':
      break;

    /* Single complete */
    case 'generationComplete': {
      if (m.scope === 'single') {
        setLoader('single', false);
        document.getElementById('btn-single').disabled = false;
        showPill('single','ok','Tests generated successfully');
        const r = m.result;
        const cov = Math.round((r.coverage || 0) * 100);
        const mut = Math.round((r.mutation_score || 0) * 100);
        const covEl = document.getElementById('rc-cov');
        const mutEl = document.getElementById('rc-mut');
        covEl.textContent = cov + '%'; covEl.className = 'met-val ' + scoreClass(cov);
        mutEl.textContent = mut + '%'; mutEl.className = 'met-val ' + scoreClass(mut);
        document.getElementById('rc-code').innerHTML = esc(r.tests || '');
        document.getElementById('rc-single-time').textContent = ts();
        document.getElementById('rc-single').classList.add('on');
      }
      break;
    }

    /* Single error */
    case 'generationError': {
      const scope = m.scope || 'single';
      setLoader(scope, false);
      document.getElementById('btn-' + scope).disabled = false;
      showPill(scope, 'err', m.error || 'Error');
      break;
    }

    /* Multi progress */
    case 'multiProgress':
      document.getElementById('ld-multi-txt').textContent =
        \`Processing \${m.current}/\${m.total}…\`;
      showMultiProgress(m.current, m.total, m.fileName);
      break;

    /* Multi complete */
    case 'multipleComplete': {
      setLoader('multi', false);
      document.getElementById('btn-multi').disabled = false;
      document.getElementById('multi-prog-wrap').style.display = 'none';
      document.getElementById('multi-prog-lbl').style.display = 'none';
      const ok = m.results.filter(r => r.status === 'success').length;
      showPill('multi', ok === m.results.length ? 'ok' : 'info',
        \`\${ok}/\${m.results.length} files generated\`);
      const rows = document.getElementById('mt-rows');
      rows.innerHTML = '';
      m.results.forEach(r => {
        const cov = r.coverage != null ? Math.round(r.coverage * 100) : null;
        const mut = r.mutation_score != null ? Math.round(r.mutation_score * 100) : null;
        const row = document.createElement('div');
        row.className = 'mt-row';
        row.innerHTML = \`
          <div class="mt-file" title="\${esc(r.file)}">\${esc(r.file)}</div>
          <div class="mt-val \${cov != null ? scoreClass(cov) : ''}">\${cov != null ? cov+'%' : '—'}</div>
          <div class="mt-val \${mut != null ? scoreClass(mut) : ''}">\${mut != null ? mut+'%' : '—'}</div>
          <div class="mt-val"><span class="tag \${r.status==='success'?'ok':'err'}">\${r.status}</span></div>\`;
        rows.appendChild(row);
      });
      document.getElementById('mt-table').classList.add('on');
      break;
    }

    /* ZIP job started → begin polling */
    case 'zipJobStarted':
      setLoader('zip', true, 'Analysing codebase…');
      startZipPolling(m.jobId, m.backendUrl);
      break;

    /* ZIP job status poll result */
    case 'jobStatus': {
      const s = m.status;
      if (s.status === 'processing' || s.status === 'queued') {
        const pct = s.progress || 0;
        document.getElementById('zip-prog-wrap').style.display = 'block';
        document.getElementById('zip-prog-lbl').style.display = 'block';
        document.getElementById('zip-prog-bar').style.width = pct + '%';
        document.getElementById('zip-prog-lbl').textContent =
          s.current_file
            ? \`\${pct}% — \${s.current_file}\`
            : \`\${pct}% complete\`;
        document.getElementById('ld-zip-txt').textContent =
          s.status === 'queued' ? 'Queued…' : 'Analysing codebase…';
      } else {
        // completed or error
        clearInterval(zipPollTimer);
        setLoader('zip', false);
        document.getElementById('btn-zip').disabled = false;
        document.getElementById('zip-prog-wrap').style.display = 'none';
        document.getElementById('zip-prog-lbl').style.display = 'none';

        if (s.status === 'error') {
          showPill('zip','err', s.error || 'Job failed');
          return;
        }

        const results = s.results || [];
        const ok = results.filter(r => r.status === 'success').length;
        showPill('zip','ok', \`\${ok}/\${results.length} files analysed\`);

        const rows = document.getElementById('zr-rows');
        rows.innerHTML = '';
        results.forEach(r => {
          const cov = r.metrics?.coverage_percent ?? null;
          const mut = r.metrics?.mutation_score != null
            ? Math.round(r.metrics.mutation_score * 100) : null;
          const row = document.createElement('div');
          row.className = 'zr-row';
          row.innerHTML = \`
            <div class="mt-file" title="\${esc(r.file)}">\${esc(r.file)}</div>
            <div class="mt-val \${cov != null ? scoreClass(cov) : ''}">\${cov != null ? cov+'%' : '—'}</div>
            <div class="mt-val \${mut != null ? scoreClass(mut) : ''}">\${mut != null ? mut+'%' : '—'}</div>
            <div class="mt-val"><span class="tag \${r.status==='success'?'ok':'err'}">\${r.status}</span></div>\`;
          rows.appendChild(row);
        });

        if (s.download_url) {
          const dlEl = document.getElementById('zr-dl');
          dlEl.href = document.getElementById('backendUrl').value.trim() + s.download_url;
          dlEl.style.display = '';
        }
        document.getElementById('zr-main').classList.add('on');
      }
      break;
    }

    /* Refactor */
    case 'refactorStarted':
      break;
    case 'refactorComplete': {
      setLoader('ref', false);
      document.getElementById('btn-refactor').disabled = false;
      showPill('ref', 'ok', 'Refactoring complete');
      if (m.result?.summary) {
        document.getElementById('ref-summary').textContent = m.result.summary;
        document.getElementById('ref-result').classList.add('on');
      }
      break;
    }
    case 'refactorError':
      setLoader('ref', false);
      document.getElementById('btn-refactor').disabled = false;
      showPill('ref','err', m.error || 'Error');
      break;
  }
});

/* Request active file on load */
vscode.postMessage({ type: 'requestActiveFile' });
</script>
</body>
</html>`;
  }
}

export function deactivate() {}