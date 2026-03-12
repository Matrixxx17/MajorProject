import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import axios from "axios";

const BACKEND_URL = "http://localhost:8000";

export function activate(context: vscode.ExtensionContext) {
  const provider = new TestGeneratorViewProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      TestGeneratorViewProvider.viewType,
      provider,
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("codexter.openView", () => {
      vscode.commands.executeCommand(
        "workbench.view.extension.codexter-container",
      );
    }),
  );

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && editor.document.uri.fsPath.endsWith(".py")) {
        provider.notifyActiveFileChanged(editor.document.uri.fsPath);
      }
    }),
  );
}

class TestGeneratorViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "codexter.testGeneratorView";
  private _view?: vscode.WebviewView;

  constructor(private readonly _extensionUri: vscode.Uri) {}

  public notifyActiveFileChanged(filePath: string) {
    this._view?.webview.postMessage({ type: "activeFileChanged", filePath });
  }

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ) {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };
    webviewView.webview.html = this._getHtml(webviewView.webview);

    const active = vscode.window.activeTextEditor;
    if (active?.document.uri.fsPath.endsWith(".py")) {
      setTimeout(
        () => this.notifyActiveFileChanged(active.document.uri.fsPath),
        300,
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
        case "pickZipFile":
          await this.pickZipFile();
          break;
        case "generateSingle":
          await this.handleSingleGeneration(msg.filePath, msg.dirPath);
          break;
        case "generateZip":
          await this.handleZipGeneration(
            msg.zipPath,
            msg.analysisMode ?? "single",
          );
          break;
        case "pollJob":
          await this.pollJob(msg.jobId, msg.scope);
          break;
        case "checkBackend":
          await this.checkBackend();
          break;
        case "refactorSingleModel":
          await this.handleRefactorSingleModel(msg.filePath, msg.model);
          break;
        case "refactorMultiModel":
          await this.handleRefactorMultiModel(msg.filePath);
          break;
        case "saveRefactored":
          await this.saveRefactoredFile(msg.filePath, msg.code, msg.model);
          break;
        case "saveTestFile":
          await this.saveTestFile(msg.filePath, msg.code, msg.suggestedName);
          break;
      }
    });
  }

  // ── File pickers ────────────────────────────────────────────────────────────

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

  // ── Test Generation handlers ────────────────────────────────────────────────

  private async handleSingleGeneration(filePath: string, dirPath: string) {
    this._view?.webview.postMessage({
      type: "generationStarted",
      scope: "single",
    });

    try {
      const code = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.file(filePath)),
      ).toString("utf8");

      const moduleName = path.basename(filePath, ".py");

      const { data } = await axios.post(
        `${BACKEND_URL}/generate-tests`,
        {
          code,
          module_name: moduleName,
          directory: dirPath,
          file_path: filePath,
        },
        { timeout: 30000 },
      );

      this._view?.webview.postMessage({
        type: "jobStarted",
        scope: "single",
        jobId: data.job_id,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "generationError",
        scope: "single",
        error: this.extractError(err),
      });
    }
  }

  private async handleZipGeneration(
    zipPath: string,
    analysisMode: "single" | "ensemble" = "single",
  ) {
    this._view?.webview.postMessage({
      type: "generationStarted",
      scope: "zip",
    });
    try {
      const zipBuffer = fs.readFileSync(zipPath);
      const fileName = path.basename(zipPath);
      const boundary = `----CodBoundary${Date.now()}`;
      const CRLF = "\r\n";

      const fileHeader = Buffer.from(
        `--${boundary}${CRLF}` +
          `Content-Disposition: form-data; name="file"; filename="${fileName}"${CRLF}` +
          `Content-Type: application/zip${CRLF}${CRLF}`,
      );
      const fileSeparator = Buffer.from(`${CRLF}`);
      const modeField = Buffer.from(
        `--${boundary}${CRLF}` +
          `Content-Disposition: form-data; name="analysis_mode"${CRLF}${CRLF}` +
          `${analysisMode}${CRLF}`,
      );
      const footer = Buffer.from(`--${boundary}--${CRLF}`);
      const body = Buffer.concat([
        fileHeader,
        zipBuffer,
        fileSeparator,
        modeField,
        footer,
      ]);

      const { data } = await axios.post(`${BACKEND_URL}/analyze_zip`, body, {
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": body.length,
        },
        timeout: 30000,
      });

      this._view?.webview.postMessage({
        type: "jobStarted",
        scope: "zip",
        jobId: data.job_id,
        analysisMode,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "generationError",
        scope: "zip",
        error: this.extractError(err),
      });
    }
  }

  private async pollJob(jobId: string, scope: string) {
    try {
      const { data } = await axios.get(`${BACKEND_URL}/status/${jobId}`, {
        timeout: 10000,
      });
      this._view?.webview.postMessage({
        type: "jobStatus",
        scope,
        status: data,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "jobStatus",
        scope,
        status: { status: "error", error: "Could not reach backend" },
      });
    }
  }

  private async checkBackend() {
    let apiOk = false;
    let apiDetail = "";
    try {
      const { data } = await axios.get(`${BACKEND_URL}/health`, {
        timeout: 4000,
      });
      apiOk = data?.status === "healthy";
      apiDetail = apiOk ? `v${data?.version ?? "?"}` : "unexpected response";
    } catch (err) {
      if (axios.isAxiosError(err)) {
        apiDetail =
          err.code === "ECONNREFUSED"
            ? "not running"
            : (err.message ?? "unreachable");
      } else {
        apiDetail = "unreachable";
      }
    }

    let ollamaOk = false;
    let ollamaDetail = "";
    let ollamaModels: string[] = [];
    if (apiOk) {
      try {
        const { data } = await axios.get(`${BACKEND_URL}/ollama-status`, {
          timeout: 6000,
        });
        ollamaOk = data?.status === "connected";
        if (ollamaOk) {
          ollamaModels = data?.models ?? [];
          const hasDeepseek = ollamaModels.some((m: string) =>
            m.startsWith("deepseek-coder"),
          );
          ollamaDetail = hasDeepseek
            ? `${ollamaModels.length} model${ollamaModels.length !== 1 ? "s" : ""} — deepseek-coder ✓`
            : `${ollamaModels.length} model${ollamaModels.length !== 1 ? "s" : ""} — deepseek-coder missing`;
          if (!hasDeepseek) ollamaOk = false;
        } else {
          ollamaDetail = data?.error ?? "not running";
        }
      } catch (err) {
        ollamaDetail = "not running";
      }
    } else {
      ollamaDetail = "api offline";
    }

    this._view?.webview.postMessage({
      type: "backendStatus",
      apiOk,
      apiDetail,
      ollamaOk,
      ollamaDetail,
      ollamaModels,
    });
  }

  // ── Refactor: PPO single-model job ──────────────────────────────────────────
  private async handleRefactorSingleModel(filePath: string, model: string) {
    try {
      const moduleName = path.basename(filePath, ".py");
      const code = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.file(filePath)),
      ).toString("utf8");

      const { data } = await axios.post(
        `${BACKEND_URL}/refactor-ppo`,
        {
          code,
          module_name: moduleName,
          file_path: filePath,
          ollama_model: model,
          ollama_url: "http://localhost:11434",
        },
        { timeout: 30000 },
      );

      this._view?.webview.postMessage({
        type: "refactorJobStarted",
        model,
        jobId: data.job_id,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "refactorJobError",
        model,
        error: this.extractError(err),
      });
    }
  }

  // ── Refactor: Multi-model job ───────────────────────────────────────────────
  private async handleRefactorMultiModel(filePath: string) {
    try {
      const moduleName = path.basename(filePath, ".py");
      const code = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.file(filePath)),
      ).toString("utf8");

      const { data } = await axios.post(
        `${BACKEND_URL}/refactor-multimodel`,
        {
          code,
          module_name: moduleName,
          file_path: filePath,
          ollama_url: "http://localhost:11434",
          ollama_timeout: 300,
        },
        { timeout: 30000 },
      );

      this._view?.webview.postMessage({
        type: "multiModelJobStarted",
        jobId: data.job_id,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "multiModelJobError",
        error: this.extractError(err),
      });
    }
  }

  private async saveRefactoredFile(
    filePath: string,
    code: string,
    model: string,
  ) {
    try {
      const answer = await vscode.window.showInformationMessage(
        `Save refactored version (${model})?`,
        "Overwrite original",
        "Save as new file",
        "Cancel",
      );
      if (answer === "Overwrite original") {
        await vscode.workspace.fs.writeFile(
          vscode.Uri.file(filePath),
          Buffer.from(code, "utf8"),
        );
        vscode.window.showInformationMessage("File saved.");
      } else if (answer === "Save as new file") {
        const dir = path.dirname(filePath);
        const base = path.basename(filePath, ".py");
        const tag = model.split(":")[0].replace("deepseek-coder", "deepseek");
        const newPath = path.join(dir, `${base}_refactored_${tag}.py`);
        await vscode.workspace.fs.writeFile(
          vscode.Uri.file(newPath),
          Buffer.from(code, "utf8"),
        );
        const doc = await vscode.workspace.openTextDocument(
          vscode.Uri.file(newPath),
        );
        await vscode.window.showTextDocument(doc);
      }
    } catch (err) {
      vscode.window.showErrorMessage(
        "Save failed: " + (err instanceof Error ? err.message : String(err)),
      );
    }
  }

  // ── Save generated test file ────────────────────────────────────────────────
  private async saveTestFile(
    sourceFilePath: string,
    code: string,
    suggestedName: string,
  ) {
    try {
      const rootDir =
        vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ??
        path.dirname(sourceFilePath);

      const defaultUri = vscode.Uri.file(
        path.join(rootDir, suggestedName),
      );

      const uri = await vscode.window.showSaveDialog({
        defaultUri,
        filters: { "Python Files": ["py"] },
        saveLabel: "Save Test File",
      });

      if (uri) {
        await vscode.workspace.fs.writeFile(
          uri,
          Buffer.from(code, "utf8"),
        );
        const doc = await vscode.workspace.openTextDocument(uri);
        await vscode.window.showTextDocument(doc);
        vscode.window.showInformationMessage(
          `Test file saved: ${path.basename(uri.fsPath)}`,
        );
      }
    } catch (err) {
      vscode.window.showErrorMessage(
        "Save failed: " + (err instanceof Error ? err.message : String(err)),
      );
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  private extractError(err: any): string {
    if (axios.isAxiosError(err)) {
      if (err.response?.data?.detail?.error)
        return err.response.data.detail.error;
      if (err.code === "ECONNREFUSED")
        return `Cannot connect to backend at ${BACKEND_URL}`;
      if (err.code === "ECONNABORTED") return "Request timed out";
      return err.message;
    }
    return err instanceof Error ? err.message : "Unknown error";
  }

  // ── HTML ─────────────────────────────────────────────────────────────────────

  private _getHtml(_webview: vscode.Webview): string {
    return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Codexter</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root{
  --bg:#0c0c10;--surf:#111118;--surf2:#16161f;--bd:#1c1c2a;--bd2:#242436;
  --accent:#7c6ef5;--accent2:#a899f8;--aclo:rgba(124,110,245,0.10);--acbd:rgba(124,110,245,0.24);
  --green:#3ecf6e;--greenlo:rgba(62,207,110,0.09);--greenbd:rgba(62,207,110,0.22);
  --amber:#f5a623;--amberlo:rgba(245,166,35,0.10);--amberbd:rgba(245,166,35,0.28);
  --red:#f07070;--redlo:rgba(240,112,112,0.09);--redbd:rgba(240,112,112,0.22);
  --teal:#22d3ee;--teallo:rgba(34,211,238,0.09);--tealbd:rgba(34,211,238,0.22);
  --text:#ddddf0;--muted:#5a5a7a;--muted2:#3a3a58;
  --mono:'Cascadia Code','Fira Code','Consolas','Courier New',monospace;
  --sans:var(--vscode-font-family,'Segoe UI',system-ui,sans-serif);
  --r:7px;--ease:cubic-bezier(.4,0,.2,1);
}

html,body{background:var(--bg);color:var(--text);font-family:var(--mono);
  font-size:11.5px;line-height:1.5;overflow-x:hidden;overflow-y:auto;min-height:100vh;}

.hdr{padding:15px 15px 0;opacity:0;animation:fdown .38s var(--ease) .04s forwards}
.wordmark{font-family:var(--sans);font-size:14px;font-weight:700;letter-spacing:.03em;
  display:flex;align-items:center;gap:8px;}
.pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 9px var(--accent);animation:pulse 2.6s ease-in-out infinite;flex-shrink:0;}
.tagline{font-size:9.5px;color:var(--muted);margin-top:3px;letter-spacing:.09em;text-transform:uppercase;}

.conn-bar{display:flex;align-items:center;gap:6px;margin:10px 15px 0;padding:7px 10px;
  background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  opacity:0;animation:fdown .38s var(--ease) .16s forwards;}
.conn-item{display:flex;align-items:center;gap:5px;font-size:9.5px;color:var(--muted);flex:1;min-width:0;}
.conn-sep{width:1px;height:12px;background:var(--bd2);flex-shrink:0}
.conn-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;background:var(--muted2);transition:background .25s,box-shadow .25s;}
.conn-dot.ok{background:var(--green);box-shadow:0 0 6px rgba(62,207,110,.5)}
.conn-dot.err{background:var(--red);box-shadow:0 0 6px rgba(240,112,112,.4)}
.conn-dot.chk{background:var(--amber);animation:pulse .9s ease-in-out infinite}
.conn-lbl{letter-spacing:.06em;text-transform:uppercase;font-size:8.5px}
.conn-detail{font-size:8.5px;color:var(--muted2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.conn-recheck{margin-left:auto;padding:2px 6px;border:1px solid var(--bd2);border-radius:4px;
  background:transparent;color:var(--muted);font-family:var(--mono);font-size:8.5px;
  cursor:pointer;transition:color .14s,border-color .14s;flex-shrink:0;}
.conn-recheck:hover{color:var(--text);border-color:var(--accent)}

.outer-tabs{display:flex;gap:2px;margin:14px 15px 0;background:var(--surf);
  border:1px solid var(--bd);border-radius:var(--r);padding:3px;
  opacity:0;animation:fdown .38s var(--ease) .1s forwards;}
.otab{flex:1;padding:7px 4px;border:none;background:transparent;color:var(--muted);
  font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.04em;cursor:pointer;
  border-radius:5px;transition:all .18s var(--ease);}
.otab:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.otab.on{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}

.mpanel{display:none;padding:14px 15px 0}
.mpanel.on{display:block;animation:fup .22s var(--ease) forwards}

.inner-tabs-wrap{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);
  padding:3px;display:flex;gap:2px;margin-bottom:14px;}
.itab{flex:1;padding:5px 2px;border:none;background:transparent;color:var(--muted);
  font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.05em;cursor:pointer;
  border-radius:4px;transition:all .17s var(--ease);white-space:nowrap;}
.itab:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.itab.on{background:rgba(255,255,255,.06);color:var(--text);border:1px solid var(--bd2);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.04);}

.spanel{display:none}
.spanel.on{display:block;animation:fup .2s var(--ease) forwards;padding-bottom:24px}

.lbl{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  margin-bottom:5px;display:flex;align-items:center;gap:5px;}
.lbl-badge{font-size:8.5px;padding:1px 5px;border-radius:20px;background:var(--aclo);
  color:var(--accent2);border:1px solid var(--acbd);letter-spacing:.04em;}

.file-card{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  padding:10px 12px;display:flex;align-items:flex-start;gap:9px;transition:border-color .17s;}
.file-card.active{border-color:var(--acbd)}
.fc-icon{font-size:15px;flex-shrink:0;line-height:1;padding-top:1px}
.fc-body{flex:1;min-width:0}
.fc-name{font-size:11px;color:var(--text);word-break:break-all;line-height:1.4}
.fc-name.empty{color:var(--muted);font-style:italic}
.fc-sub{font-size:9.5px;color:var(--muted);margin-top:3px;word-break:break-all}
.fc-dismiss{display:none;flex-shrink:0;align-self:center;width:18px;height:18px;
  border-radius:4px;border:none;background:transparent;color:var(--muted);font-size:13px;
  line-height:1;cursor:pointer;padding:0;transition:background .14s,color .14s;}
.fc-dismiss:hover{background:var(--redlo);color:var(--red)}
.fc-dismiss.visible{display:flex;align-items:center;justify-content:center}
.fc-dismiss:disabled{opacity:.25;cursor:not-allowed;pointer-events:none}

.btn{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;
  padding:9px;border:none;border-radius:var(--r);font-family:var(--mono);font-size:11px;
  font-weight:600;letter-spacing:.04em;cursor:pointer;transition:all .18s var(--ease);
  position:relative;overflow:hidden;}
.btn::after{content:'';position:absolute;inset:0;background:#fff;opacity:0;transition:opacity .13s;}
.btn:active:not(:disabled)::after{opacity:.05}
.btn:disabled{opacity:.32;cursor:not-allowed;transform:none !important;box-shadow:none !important}
.btn-violet{background:linear-gradient(135deg,var(--accent),#9b8af8);color:#fff;box-shadow:0 3px 14px rgba(124,110,245,.3);}
.btn-violet:hover:not(:disabled){box-shadow:0 5px 20px rgba(124,110,245,.44);transform:translateY(-1px);}
.btn-green{background:linear-gradient(135deg,#16a34a,var(--green));color:#051a0e;box-shadow:0 3px 14px rgba(62,207,110,.22);}
.btn-green:hover:not(:disabled){box-shadow:0 5px 20px rgba(62,207,110,.36);transform:translateY(-1px);}
.btn-amber{background:linear-gradient(135deg,#b45309,var(--amber));color:#0d0800;box-shadow:0 3px 14px rgba(245,166,35,.22);}
.btn-amber:hover:not(:disabled){box-shadow:0 5px 20px rgba(245,166,35,.36);transform:translateY(-1px);}
.btn-teal{background:linear-gradient(135deg,#0e7490,var(--teal));color:#011419;box-shadow:0 3px 14px rgba(34,211,238,.22);}
.btn-teal:hover:not(:disabled){box-shadow:0 5px 20px rgba(34,211,238,.36);transform:translateY(-1px);}
.btn-ghost{background:var(--surf);color:var(--muted);border:1px solid var(--bd);width:auto;padding:7px 11px;font-size:11px;}
.btn-ghost:hover{color:var(--text);border-color:var(--bd2)}

.row{display:flex;gap:8px;align-items:flex-end;margin-bottom:12px}
.mb{margin-bottom:12px}.fld{margin-bottom:12px}
.divider{height:1px;background:var(--bd);margin:12px 0}

.loader{display:none;flex-direction:column;align-items:center;gap:10px;padding:18px 0 8px;}
.loader.on{display:flex}
.ring{width:22px;height:22px;border-radius:50%;border:2px solid var(--bd2);border-top-color:var(--accent);animation:spin .7s linear infinite;}
.ring.green{border-top-color:var(--green)}.ring.amber{border-top-color:var(--amber)}.ring.teal{border-top-color:var(--teal)}
.loader-txt{font-size:10px;color:var(--muted);letter-spacing:.06em}

.pill{display:none;align-items:center;gap:7px;padding:8px 11px;border-radius:var(--r);font-size:11px;}
.pill.on{display:flex;animation:fup .2s var(--ease) forwards}
.pdot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.pill.info{background:var(--aclo);border:1px solid var(--acbd);color:var(--accent2)}
.pill.info .pdot{background:var(--accent);box-shadow:0 0 6px var(--accent);animation:pulse 1.4s ease-in-out infinite}
.pill.ok{background:var(--greenlo);border:1px solid var(--greenbd);color:var(--green)}
.pill.ok .pdot{background:var(--green)}
.pill.err{background:var(--redlo);border:1px solid var(--redbd);color:var(--red)}
.pill.err .pdot{background:var(--red)}

.progress-wrap{background:var(--surf2);border:1px solid var(--bd);border-radius:20px;height:5px;overflow:hidden;margin-bottom:6px;}
.progress-bar{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:20px;transition:width .4s var(--ease);width:0%;}
.progress-bar.amber{background:linear-gradient(90deg,var(--amber),#f5c842);}
.progress-bar.teal{background:linear-gradient(90deg,var(--teal),#67e8f9);}
.progress-label{font-size:9.5px;color:var(--muted);text-align:center;margin-bottom:8px}

/* ── Approach selector (3 modes) ── */
.approach-wrap{margin-bottom:14px;}
.approach-lbl{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:7px;}
.approach-cards{display:flex;flex-direction:column;gap:5px;}
.approach-card{padding:9px 11px;background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  cursor:pointer;transition:all .17s var(--ease);display:grid;grid-template-columns:16px 1fr auto;align-items:center;gap:9px;}
.approach-card:hover:not(.on){background:var(--surf2);border-color:var(--bd2)}
.approach-card.on.pynguin{background:var(--aclo);border-color:var(--acbd);}
.approach-card.on.llm{background:var(--amberlo);border-color:var(--amberbd);}
.approach-card.on.hybrid{background:var(--teallo);border-color:var(--tealbd);}
.approach-card input[type=radio]{accent-color:var(--accent);width:13px;height:13px;cursor:pointer;pointer-events:none;}
.approach-title{font-size:11px;color:var(--text);font-weight:600;}
.approach-desc{font-size:9px;color:var(--muted);margin-top:2px;line-height:1.5;}
.approach-badge{font-size:8px;padding:2px 6px;border-radius:4px;border:1px solid;white-space:nowrap;flex-shrink:0;}
.approach-badge.pynguin{background:var(--aclo);border-color:var(--acbd);color:var(--accent2);}
.approach-badge.llm{background:var(--amberlo);border-color:var(--amberbd);color:var(--amber);}
.approach-badge.hybrid{background:var(--teallo);border-color:var(--tealbd);color:var(--teal);}

/* ── Approach config panels ── */
.approach-config{display:none;margin-bottom:12px;}
.approach-config.on{display:block;animation:fup .18s var(--ease) forwards;}

/* ── Checkbox selector grid ── */
.sel-wrap{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);padding:9px 11px;margin-bottom:12px;}
.sel-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:7px;}
.sel-items{display:flex;flex-direction:column;gap:4px;}
.sel-row{display:grid;grid-template-columns:16px auto 1fr auto;align-items:center;gap:8px;
  cursor:pointer;padding:6px 8px;border-radius:5px;border:1px solid transparent;transition:all .14s;}
.sel-row:hover{background:rgba(255,255,255,.03);border-color:var(--bd2)}
.sel-row.checked.pynguin{background:var(--aclo);border-color:var(--acbd);}
.sel-row.checked.llm{background:var(--amberlo);border-color:var(--amberbd);}
.sel-row.checked.hybrid-a{background:var(--aclo);border-color:var(--acbd);}
.sel-row.checked.hybrid-l{background:var(--amberlo);border-color:var(--amberbd);}
.sel-row input[type=checkbox],.sel-row input[type=radio]{accent-color:var(--accent);width:13px;height:13px;cursor:pointer;pointer-events:none;}
.sel-badge{font-size:8.5px;padding:2px 6px;border-radius:4px;border:1px solid;flex-shrink:0;}
.sel-badge.algo{background:var(--aclo);border-color:var(--acbd);color:var(--accent2);}
.sel-badge.ds{background:#1e1440;border-color:#7c3aed;color:#c4b5fd;}
.sel-badge.cl{background:#271505;border-color:#b45309;color:#fcd34d;}
.sel-label{font-size:10.5px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.sel-meta{font-size:9px;color:var(--muted);white-space:nowrap;}

/* ── Results / metrics table ── */
.section-hdr{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.section-hdr::after{content:'';flex:1;height:1px;background:var(--bd);}

.gen-table{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;margin-bottom:8px;}
.gt-row{display:grid;gap:0;align-items:center;border-bottom:1px solid var(--bd);font-size:10.5px;}
.gt-row:last-child{border-bottom:none}
.gt-row.hd{background:var(--surf2);font-size:8.5px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;}
.gt-cell{padding:7px 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.gt-cell.right{text-align:right;}

/* Pynguin table: Key | Coverage% | Mutation% | Status  (4 cols) */
.gt-row.pynguin-row{grid-template-columns:100px 1fr 70px 70px 60px;}
/* LLM table: Key | Coverage% | Mutation% | Status  (4 cols) */
.gt-row.llm-row{grid-template-columns:1fr 70px 70px 60px;}
/* Hybrid table: single row — Algorithm | LLM | Coverage% | Mutation% | Status */
.gt-row.hybrid-row{grid-template-columns:90px 1fr 70px 70px 60px;}

.algo-badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;font-size:8.5px;letter-spacing:.05em;font-weight:600;}
.algo-badge.random{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.algo-badge.whole_suite{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd);}
.algo-badge.dynamosa{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd);}
.model-badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;font-size:8.5px;letter-spacing:.04em;font-weight:600;}
.model-badge.ds{background:#1e1440;border:1px solid #7c3aed;color:#c4b5fd;}
.model-badge.cl{background:#271505;border:1px solid #b45309;color:#fcd34d;}
.score-g{color:var(--green)}.score-a{color:var(--amber)}.score-r{color:var(--red)}.score-d{color:var(--muted)}
.tag{display:inline-flex;align-items:center;justify-content:center;font-size:8.5px;padding:2px 6px;border-radius:4px;letter-spacing:.04em;}
.tag.ok{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd)}
.tag.err{background:var(--redlo);color:var(--red);border:1px solid var(--redbd)}
.tag.run{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd)}
.tag.skip{background:var(--surf2);color:var(--muted);border:1px solid var(--bd2)}

/* ── Generated test file cards ── */
.test-files-section{display:none;margin-top:14px;}
.test-files-section.on{display:block;animation:fup .24s var(--ease) forwards}
.test-file-card{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  margin-bottom:8px;overflow:hidden;transition:border-color .17s;}
.test-file-card:hover{border-color:var(--bd2)}
.tfc-hdr{padding:7px 10px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;
  background:var(--surf2);flex-wrap:wrap;row-gap:4px;}
.tfc-icon{font-size:12px;flex-shrink:0;}
.tfc-name{font-size:9.5px;color:var(--text);flex:1;min-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tfc-tag{font-size:8px;padding:1px 5px;border-radius:3px;flex-shrink:0;}
.tfc-save{font-size:9px;padding:3px 8px;background:var(--surf);border:1px solid var(--bd2);border-radius:4px;
  color:var(--accent2);cursor:pointer;white-space:nowrap;font-family:var(--mono);transition:all .14s;flex-shrink:0;}
.tfc-save:hover{background:var(--aclo);border-color:var(--acbd);}
.tfc-save:disabled{opacity:.3;cursor:not-allowed;pointer-events:none;}
.tfc-body{padding:10px;max-height:220px;overflow-y:auto;}
.tfc-pre{font-size:9px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#bbbbd8;margin:0;}
.tfc-empty{color:var(--muted);font-style:italic;font-size:10px;padding:12px;text-align:center;}
.tfc-toggle{background:none;border:none;color:var(--muted);font-family:var(--mono);font-size:9px;
  cursor:pointer;padding:2px 6px;border-radius:3px;transition:color .13s;}
.tfc-toggle:hover{color:var(--text)}

/* ── Results area wrapping ── */
.results-area{display:none;margin-top:14px;}
.results-area.on{display:block;animation:fup .22s var(--ease) forwards}

.dl-link{color:var(--accent2);text-decoration:none;font-size:9.5px;}
.dl-link:hover{color:var(--accent)}

.zip-result{display:none;margin-top:16px;background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.zip-result.on{display:block;animation:fup .26s var(--ease) forwards}
.zr-hdr{padding:8px 12px;border-bottom:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between}
.zr-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.zr-body{padding:10px 12px;max-height:220px;overflow-y:auto}
.zr-row{display:grid;grid-template-columns:1fr 46px 46px 52px 52px;gap:5px;align-items:center;padding:5px 0;border-bottom:1px solid var(--bd);font-size:10.5px;}
.zr-row:last-child{border-bottom:none}
.zr-row.hd{font-size:9px;color:var(--muted);letter-spacing:.07em;text-transform:uppercase}
.mt-val{text-align:right}.mt-file{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.mode-toggle{display:flex;gap:2px;margin-bottom:12px;background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);padding:3px;}
.mtog{flex:1;padding:6px 4px;border:none;background:transparent;color:var(--muted);font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.04em;cursor:pointer;border-radius:5px;transition:all .17s var(--ease);display:flex;align-items:center;justify-content:center;gap:5px;}
.mtog:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.mtog.on.single{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.mtog.on.ensemble{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd);}
.mode-desc{font-size:9px;color:var(--muted);margin-bottom:10px;padding:6px 9px;background:var(--surf2);border:1px solid var(--bd);border-radius:5px;line-height:1.6;}
.mode-desc .hi{color:var(--text)}

/* ── Shared refactor styles ── */
.ref-file-card{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);
  padding:11px 13px;margin-bottom:13px;display:flex;align-items:flex-start;gap:9px;}
.ref-body{flex:1;min-width:0}
.ref-name{font-size:11px;color:var(--text);word-break:break-all;line-height:1.4}
.ref-name.empty{color:var(--muted);font-style:italic}
.ref-sub{font-size:9.5px;color:var(--muted);margin-top:3px}

/* ── Multi-model metrics table ── */
.mm-mtable{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.mm-mhdr{display:grid;grid-template-columns:1fr 52px 48px 42px 52px 46px;gap:4px;
  padding:6px 10px;font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;
  border-bottom:1px solid var(--bd);background:var(--surf2);}
.mm-mrow{display:grid;grid-template-columns:1fr 52px 48px 42px 52px 46px;gap:4px;
  padding:7px 10px;font-size:10px;border-bottom:1px solid var(--bd2);align-items:center;transition:background .15s;}
.mm-mrow:last-child{border-bottom:none}
.mm-mrow.best-row{background:#0d1f10;}
.mm-mrow.loading-row{opacity:.6;}

/* ── PPO metrics table ── */
.ppo-mtable{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.ppo-mhdr{display:grid;grid-template-columns:1fr 46px 46px 46px 46px 56px;gap:4px;
  padding:6px 10px;font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;
  border-bottom:1px solid var(--bd);background:var(--surf2);}
.ppo-mrow{display:grid;grid-template-columns:1fr 46px 46px 46px 46px 56px;gap:4px;
  padding:7px 10px;font-size:10px;border-bottom:1px solid var(--bd2);align-items:center;transition:background .15s;}
.ppo-mrow:last-child{border-bottom:none}
.ppo-mrow.best-row{background:#0d1f10;}
.ppo-mrow.loading-row{opacity:.6;}

.delta-pos{color:#4ade80;}.delta-neg{color:#f87171;}.delta-neu{color:#fbbf24;}.delta-dim{color:var(--muted)}
.reward-cell{display:flex;align-items:center;gap:4px;}
.tag.sm{font-size:8px;padding:1px 5px;}

/* Model checkboxes (PPO) */
.model-pick-wrap{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);padding:10px 12px;margin-bottom:12px;}
.model-pick-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;}
.model-checks{display:flex;flex-direction:column;gap:5px;}
.mc-row{display:grid;grid-template-columns:16px auto 1fr auto;align-items:center;gap:8px;
  cursor:pointer;padding:7px 9px;border-radius:5px;border:1px solid transparent;transition:all .15s;}
.mc-row:hover{background:rgba(255,255,255,.03);border-color:var(--bd2)}
.mc-row.checked{background:var(--aclo);border-color:var(--acbd);}
.mc-row input[type=checkbox]{accent-color:var(--accent);width:13px;height:13px;cursor:pointer;flex-shrink:0;pointer-events:none;}
.mc-badge{font-size:8.5px;padding:2px 6px;border-radius:4px;border:1px solid;flex-shrink:0;}
.mc-badge.ds{background:#1e1440;border-color:#7c3aed;color:#c4b5fd;}
.mc-badge.sc{background:#0d2b1e;border-color:#059669;color:#6ee7b7;}
.mc-badge.cl{background:#271505;border-color:#b45309;color:#fcd34d;}
.mc-label{font-size:10.5px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mc-meta{font-size:9px;color:var(--muted);white-space:nowrap;}

/* Ensemble stepper */
.ens-stepper{display:none;margin-top:10px;margin-bottom:4px;}
.ens-stepper.on{display:block}
.ens-step-hdr{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:7px;display:flex;align-items:center;gap:6px;}
.ens-step-hdr::after{content:'';flex:1;height:1px;background:var(--bd);}
.ens-steps{display:flex;flex-direction:column;gap:4px;}
.ens-step{padding:7px 10px;background:var(--surf);border:1px solid var(--bd2);border-radius:5px;transition:border-color .2s,background .2s;}
.ens-step.active{background:var(--aclo);border-color:var(--acbd);}
.ens-step.done{background:var(--greenlo);border-color:var(--greenbd);}
.ens-step.fail{background:var(--redlo);border-color:var(--redbd);}
.ens-step-top{display:grid;grid-template-columns:18px 1fr auto;align-items:center;gap:8px;font-size:10px;}
.step-ico{font-size:11px;text-align:center;}
.step-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text);}
.step-status{font-size:9px;color:var(--muted);white-space:nowrap;}
.ens-step-prog{display:none;height:3px;background:var(--bd2);border-radius:2px;margin-top:6px;overflow:hidden;}
.ens-step-prog.on{display:block;}
.ens-step-prog-bar{height:100%;background:var(--accent);border-radius:2px;transition:width .35s var(--ease);width:0%;}

/* ── Refactored code output ── */
.ref-code-section{display:none;margin-top:14px;}
.ref-code-section.on{display:block;animation:fup .24s var(--ease) forwards}
.ref-code-wrap{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.ref-code-hdr{padding:7px 10px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;background:var(--surf2);flex-wrap:wrap;row-gap:5px;}
.ref-code-title{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;flex:1;min-width:80px;}
.ref-model-btns{display:flex;gap:4px;flex-wrap:wrap;}
.ref-mbtn{font-size:9px;padding:2px 7px;border-radius:4px;border:1px solid;cursor:pointer;opacity:.55;background:transparent;font-family:var(--mono);transition:opacity .14s;}
.ref-mbtn.on{opacity:1;font-weight:700;}
.ref-mbtn.ds{border-color:#7c3aed;color:#c4b5fd;}
.ref-mbtn.sc{border-color:#059669;color:#6ee7b7;}
.ref-mbtn.cl{border-color:#b45309;color:#fcd34d;}
.ref-code-pre{margin:0;padding:10px;font-size:9.5px;line-height:1.6;overflow-x:auto;max-height:280px;white-space:pre;font-family:var(--mono);color:#c4c4e0;}
.btn-save-ref{font-size:9.5px;padding:3px 9px;background:var(--surf);border:1px solid var(--bd);border-radius:4px;color:var(--text);cursor:pointer;white-space:nowrap;font-family:var(--mono);}
.btn-save-ref:hover{background:var(--surf2);}

/* Metrics section shared */
.ref-metrics-section{display:none;margin-top:14px;}
.ref-metrics-section.on{display:block;animation:fup .24s var(--ease) forwards}

::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:3px}
@keyframes fdown{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
@keyframes fup{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:translateY(0)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
</style>
</head>
<body>

<div class="hdr">
  <div class="wordmark"><span class="pulse-dot"></span>Codexter</div>
  <div class="tagline">AI-powered test &amp; refactor</div>
</div>

<div class="conn-bar" id="conn-bar">
  <div class="conn-item">
    <span class="conn-dot chk" id="dot-api"></span>
    <span class="conn-lbl">API</span>
    <span class="conn-detail" id="det-api">checking…</span>
  </div>
  <div class="conn-sep"></div>
  <div class="conn-item">
    <span class="conn-dot chk" id="dot-ollama"></span>
    <span class="conn-lbl">Ollama</span>
    <span class="conn-detail" id="det-ollama">checking…</span>
  </div>
  <button class="conn-recheck" onclick="triggerCheck()" title="Re-check connections">↺</button>
</div>

<div class="outer-tabs">
  <button class="otab on" onclick="oSwitch('testgen',this)">⬡ Test Gen</button>
  <button class="otab"    onclick="oSwitch('refactor',this)">⟳ Refactor</button>
</div>

<!-- ══ Test Generation panel ════════════════════════════════════ -->
<div class="mpanel on" id="mp-testgen">
  <div class="inner-tabs-wrap">
    <button class="itab on" onclick="iSwitch('single',this)">Single File</button>
    <button class="itab"    onclick="iSwitch('zip',this)">Codebase</button>
  </div>

  <!-- ══ Single File ══ -->
  <div class="spanel on" id="sp-single">
    <!-- File picker -->
    <div class="fld">
      <div class="lbl">Python File <span class="lbl-badge" id="sf-auto-badge" style="display:none">auto</span></div>
      <div class="file-card" id="sf-card">
        <div class="fc-icon">🐍</div>
        <div class="fc-body">
          <div class="fc-name empty" id="sf-name">Open a .py file or browse below</div>
          <div class="fc-sub" id="sf-dir"></div>
        </div>
        <button class="fc-dismiss" id="sf-dismiss" title="Clear file" onclick="clearSingle()">×</button>
      </div>
    </div>
    <div class="row mb">
      <button class="btn btn-ghost" id="btn-browse-single" onclick="pickSingle()">Browse other file</button>
    </div>

    <!-- ── Approach selector ── -->
    <div class="approach-wrap">
      <div class="approach-lbl">Generation Approach</div>
      <div class="approach-cards">
        <div class="approach-card on pynguin" id="ac-pynguin" onclick="selectApproach('pynguin')">
          <input type="radio" name="sg-approach" checked>
          <div>
            <div class="approach-title">⬡ Pynguin</div>
            <div class="approach-desc">Search-based algorithmic test generation</div>
          </div>
          <span class="approach-badge pynguin">Algorithmic</span>
        </div>
        <div class="approach-card llm" id="ac-llm" onclick="selectApproach('llm')">
          <input type="radio" name="sg-approach">
          <div>
            <div class="approach-title">◈ LLM</div>
            <div class="approach-desc">Language model test generation</div>
          </div>
          <span class="approach-badge llm">AI Models</span>
        </div>
        <div class="approach-card hybrid" id="ac-hybrid" onclick="selectApproach('hybrid')">
          <input type="radio" name="sg-approach">
          <div>
            <div class="approach-title">⟳ Hybrid</div>
            <div class="approach-desc">Pynguin generates → LLM refines</div>
          </div>
          <span class="approach-badge hybrid">Best of Both</span>
        </div>
      </div>
    </div>

    <!-- ── Pynguin config ── -->
    <div class="approach-config on" id="cfg-pynguin">
      <div class="sel-wrap">
        <div class="sel-title">Select Algorithms (one or more)</div>
        <div class="sel-items">
          <div class="sel-row pynguin checked" id="ar-random" onclick="toggleAlgo('RANDOM',this)">
            <input type="checkbox" checked>
            <span class="sel-badge algo">RND</span>
            <span class="sel-label">RANDOM</span>
            <span class="sel-meta">fast · baseline</span>
          </div>
          <div class="sel-row pynguin checked" id="ar-whole" onclick="toggleAlgo('WHOLE_SUITE',this)">
            <input type="checkbox" checked>
            <span class="sel-badge algo">WS</span>
            <span class="sel-label">WHOLE_SUITE</span>
            <span class="sel-meta">coverage · recommended</span>
          </div>
          <div class="sel-row pynguin checked" id="ar-dynamosa" onclick="toggleAlgo('DYNAMOSA',this)">
            <input type="checkbox" checked>
            <span class="sel-badge algo">DYN</span>
            <span class="sel-label">DYNAMOSA</span>
            <span class="sel-meta">branch-guided · thorough</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── LLM config ── -->
    <div class="approach-config" id="cfg-llm">
      <div class="sel-wrap">
        <div class="sel-title">Select Models (one or more)</div>
        <div class="sel-items">
          <div class="sel-row llm checked" id="lr-ds" onclick="toggleLlm('deepseek-coder:1.3b',this)">
            <input type="checkbox" checked>
            <span class="sel-badge ds">DS</span>
            <span class="sel-label">deepseek-coder:1.3b</span>
            <span class="sel-meta">1.3B · fast</span>
          </div>
          <div class="sel-row llm" id="lr-cl" onclick="toggleLlm('codellama:7b',this)">
            <input type="checkbox">
            <span class="sel-badge cl">CL</span>
            <span class="sel-label">codellama:7b</span>
            <span class="sel-meta">7B · quality</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Hybrid config ── -->
    <div class="approach-config" id="cfg-hybrid">
      <div class="sel-wrap">
        <div class="sel-title">Algorithm (pick one)</div>
        <div class="sel-items">
          <div class="sel-row hybrid-a checked" id="har-random" onclick="selectHybridAlgo('RANDOM',this)">
            <input type="radio" name="h-algo" checked>
            <span class="sel-badge algo">RND</span>
            <span class="sel-label">RANDOM</span>
            <span class="sel-meta">fast · baseline</span>
          </div>
          <div class="sel-row hybrid-a" id="har-whole" onclick="selectHybridAlgo('WHOLE_SUITE',this)">
            <input type="radio" name="h-algo">
            <span class="sel-badge algo">WS</span>
            <span class="sel-label">WHOLE_SUITE</span>
            <span class="sel-meta">coverage</span>
          </div>
          <div class="sel-row hybrid-a" id="har-dynamosa" onclick="selectHybridAlgo('DYNAMOSA',this)">
            <input type="radio" name="h-algo">
            <span class="sel-badge algo">DYN</span>
            <span class="sel-label">DYNAMOSA</span>
            <span class="sel-meta">thorough</span>
          </div>
        </div>
      </div>
      <div class="sel-wrap" style="margin-top:0">
        <div class="sel-title">LLM Refiner (pick one)</div>
        <div class="sel-items">
          <div class="sel-row hybrid-l checked" id="hlr-ds" onclick="selectHybridLlm('deepseek-coder:1.3b',this)">
            <input type="radio" name="h-llm" checked>
            <span class="sel-badge ds">DS</span>
            <span class="sel-label">deepseek-coder:1.3b</span>
            <span class="sel-meta">1.3B · fast</span>
          </div>
          <div class="sel-row hybrid-l" id="hlr-cl" onclick="selectHybridLlm('codellama:7b',this)">
            <input type="radio" name="h-llm">
            <span class="sel-badge cl">CL</span>
            <span class="sel-label">codellama:7b</span>
            <span class="sel-meta">7B · quality</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Run button ── -->
    <button class="btn btn-violet" id="btn-single" onclick="genSingle()" disabled>⬡ Generate Tests</button>

    <!-- ── Progress ── -->
    <div class="loader" id="ld-single"><div class="ring" id="single-ring"></div><span class="loader-txt" id="ld-single-txt">Submitting…</span></div>
    <div class="progress-wrap" id="single-prog-wrap" style="display:none"><div class="progress-bar" id="single-prog-bar"></div></div>
    <div class="progress-label" id="single-prog-lbl" style="display:none"></div>
    <div class="pill" id="pill-single"><span class="pdot"></span><span id="pill-single-txt"></span></div>

    <!-- ── Results ── -->
    <div class="results-area" id="single-results">

      <!-- Metrics table -->
      <div id="single-metrics-wrap">
        <div class="section-hdr" id="single-metrics-hdr">Results</div>
        <div class="gen-table" id="single-metrics-table">
          <div id="single-metrics-head"></div>
          <div id="single-metrics-rows"></div>
        </div>
        <div style="margin-top:6px;text-align:right">
          <a class="dl-link" id="single-dl" href="#" style="display:none">↓ Download All Tests</a>
        </div>
      </div>

      <!-- Generated test file cards -->
      <div class="test-files-section" id="single-file-cards">
        <div class="section-hdr">Generated Test Files</div>
        <div id="single-file-cards-body"></div>
      </div>

    </div><!-- /single-results -->
  </div><!-- /sp-single -->

  <!-- ══ Codebase ZIP ══ -->
  <div class="spanel" id="sp-zip">
    <div class="fld">
      <div class="lbl">ZIP Archive</div>
      <div class="file-card" id="zip-card">
        <div class="fc-icon">📦</div>
        <div class="fc-body">
          <div class="fc-name empty" id="zip-name">No archive selected</div>
          <div class="fc-sub" id="zip-sub"></div>
        </div>
        <button class="fc-dismiss" id="zip-dismiss" title="Clear archive" onclick="clearZip()">×</button>
      </div>
    </div>
    <div class="row mb">
      <button class="btn btn-ghost" id="btn-browse-zip" onclick="pickZip()">Browse ZIP</button>
    </div>
    <div class="lbl" style="margin-bottom:6px">Analysis Mode</div>
    <div class="mode-toggle">
      <button class="mtog single on" id="mtog-single" onclick="setMode('single')">⬡ Single Model</button>
      <button class="mtog ensemble"  id="mtog-ensemble" onclick="setMode('ensemble')">◈ Ensemble</button>
    </div>
    <div class="mode-desc" id="mode-desc">
      <span class="hi">Single Model</span> — fast analysis using <span class="hi">deepseek-coder:1.3b</span>. Good for most codebases.
    </div>
    <button class="btn btn-violet" id="btn-zip" onclick="genZip()" disabled>⬡ Analyse Codebase</button>
    <div class="loader" id="ld-zip"><div class="ring" id="zip-ring"></div><span class="loader-txt" id="ld-zip-txt">Uploading…</span></div>
    <div class="progress-wrap" id="zip-prog-wrap" style="display:none"><div class="progress-bar" id="zip-prog-bar"></div></div>
    <div class="progress-label" id="zip-prog-lbl" style="display:none"></div>
    <div class="pill" id="pill-zip"><span class="pdot"></span><span id="pill-zip-txt"></span></div>
    <div class="zip-result" id="zr-main">
      <div class="zr-hdr">
        <span class="zr-title">Codebase Results</span>
        <a class="dl-link" id="zr-dl" href="#" style="display:none">↓ Download All Tests</a>
      </div>
      <div class="zr-body">
        <div class="zr-row hd"><div>File</div><div class="mt-val">Cov%</div><div class="mt-val">Mut</div><div class="mt-val">Method</div><div class="mt-val">Status</div></div>
        <div id="zr-rows"></div>
      </div>
    </div>
  </div><!-- /sp-zip -->
</div><!-- /mp-testgen -->

<!-- ══ Refactor panel ════════════════════════════════════════════ -->
<div class="mpanel" id="mp-refactor">

  <!-- Shared file picker at top -->
  <div class="lbl">Active File <span class="lbl-badge" id="ref-auto-badge">auto</span></div>
  <div class="ref-file-card mb">
    <div style="font-size:16px;flex-shrink:0;line-height:1;padding-top:1px">🐍</div>
    <div class="ref-body">
      <div class="ref-name empty" id="ref-name">Open a Python file in the editor</div>
      <div class="ref-sub" id="ref-sub"></div>
    </div>
    <button class="fc-dismiss" id="ref-dismiss" title="Clear file" onclick="clearRef()">×</button>
  </div>

  <!-- Sub-tabs: Multi-Model vs TRL+PPO -->
  <div class="inner-tabs-wrap">
    <button class="itab on" id="rtab-mm"  onclick="rSwitch('mm',this)">◈ Multi-Model</button>
    <button class="itab"    id="rtab-ppo" onclick="rSwitch('ppo',this)">⟳ TRL+PPO</button>
  </div>

  <!-- ── Multi-Model sub-panel ── -->
  <div class="spanel on" id="rsp-mm">
    <div style="font-size:9px;color:var(--muted);margin-bottom:10px;padding:6px 9px;background:var(--surf2);border:1px solid var(--bd);border-radius:5px;line-height:1.6;">
      Runs <span style="color:var(--text)">deepseek-coder:1.3b</span>, <span style="color:var(--text)">starcoder</span>, and <span style="color:var(--text)">codellama:7b</span> in parallel. Compares Test Pass Rate, Cyclomatic Complexity, LOC, Maintainability Index, and Pylint Score.
    </div>

    <button class="btn btn-violet" id="btn-mm-run" onclick="runMultiModel()" disabled>◈ Run Multi-Model Refactor</button>

    <div class="loader" id="ld-mm"><div class="ring" id="mm-ring"></div><span class="loader-txt" id="ld-mm-txt">Running 3 models in parallel…</span></div>
    <div class="progress-wrap" id="mm-prog-wrap" style="display:none;margin-top:10px;"><div class="progress-bar" id="mm-prog-bar"></div></div>
    <div class="progress-label" id="mm-prog-lbl" style="display:none"></div>
    <div class="pill" id="pill-mm"><span class="pdot"></span><span id="pill-mm-txt"></span></div>

    <!-- Multi-model metrics table -->
    <div class="ref-metrics-section" id="mm-metrics-section">
      <div class="section-hdr">Metrics Comparison (Original → Refactored)</div>
      <div class="mm-mtable">
        <div class="mm-mhdr">
          <span>Model</span><span>Pass Rate</span><span>CC Δ</span><span>LOC Δ</span><span>Maint. Idx</span><span>Pylint</span>
        </div>
        <div id="mm-mrows"></div>
      </div>
    </div>

    <!-- Refactored code viewer (no original) -->
    <div class="ref-code-section" id="mm-code-section">
      <div class="section-hdr">Refactored Code</div>
      <div class="ref-code-wrap">
        <div class="ref-code-hdr">
          <span class="ref-code-title" id="mm-code-title">select a model below</span>
          <div class="ref-model-btns" id="mm-model-btns"></div>
          <button class="btn-save-ref" onclick="saveMmChoice()">💾 Save</button>
        </div>
        <pre class="ref-code-pre" id="mm-code-pre"></pre>
      </div>
    </div>
  </div><!-- /rsp-mm -->

  <!-- ── TRL+PPO sub-panel ── -->
  <div class="spanel" id="rsp-ppo">
    <!-- Model picker for PPO -->
    <div class="model-pick-wrap">
      <div class="model-pick-title">Select Model for Iterative Refactor</div>
      <div style="font-size:9px;color:var(--muted);margin-bottom:8px;line-height:1.6;">
        No pretrained PPO model needed — the selected Ollama model generates each 
        iteration. Reward feedback is injected into the prompt to guide improvement.
      </div>
      <div class="model-checks">
        <div class="mc-row checked" id="mc-ds" onclick="selectPpoModel('deepseek-coder:1.3b',this)">
          <input type="radio" id="chk-ds" name="ppo-model" checked>
          <span class="mc-badge ds">DS</span>
          <span class="mc-label">deepseek-coder:1.3b</span>
          <span class="mc-meta">1.3B · fast</span>
        </div>
        <div class="mc-row" id="mc-sc" onclick="selectPpoModel('starcoder',this)">
          <input type="radio" id="chk-sc" name="ppo-model">
          <span class="mc-badge sc">SC</span>
          <span class="mc-label">starcoder</span>
          <span class="mc-meta">15.5B</span>
        </div>
        <div class="mc-row" id="mc-cl" onclick="selectPpoModel('codellama:7b',this)">
          <input type="radio" id="chk-cl" name="ppo-model">
          <span class="mc-badge cl">CL</span>
          <span class="mc-label">codellama:7b</span>
          <span class="mc-meta">7B · quality</span>
        </div>
      </div>
    </div>

    <button class="btn btn-amber" id="btn-ppo-run" onclick="runPpo()" disabled>⟳ Run TRL+PPO Refactor</button>

    <div class="loader" id="ld-ppo"><div class="ring amber" id="ppo-ring"></div><span class="loader-txt" id="ld-ppo-txt">Initialising PPO loop…</span></div>
    <div class="progress-wrap" id="ppo-prog-wrap" style="display:none;margin-top:10px;"><div class="progress-bar amber" id="ppo-prog-bar"></div></div>
    <div class="progress-label" id="ppo-prog-lbl" style="display:none"></div>

    <!-- Ensemble stepper (iterations) -->
    <div class="ens-stepper" id="ppo-stepper">
      <div class="ens-step-hdr">PPO Iterations</div>
      <div class="ens-steps" id="ppo-steps"></div>
    </div>

    <div class="pill" id="pill-ppo"><span class="pdot"></span><span id="pill-ppo-txt"></span></div>

    <!-- PPO metrics table: CC Δ, PEP8 Δ, HD Δ, LOC Δ, Reward -->
    <div class="ref-metrics-section" id="ppo-metrics-section">
      <div class="section-hdr">PPO Metrics (per iteration)</div>
      <div class="ppo-mtable">
        <div class="ppo-mhdr">
          <span>Iter</span><span>CC Δ</span><span>PEP8 Δ</span><span>HD Δ</span><span>LOC Δ</span><span>Reward</span>
        </div>
        <div id="ppo-mrows"></div>
      </div>
    </div>

    <!-- PPO refactored code (best iteration, no original) -->
    <div class="ref-code-section" id="ppo-code-section">
      <div class="section-hdr">Best Refactored Code</div>
      <div class="ref-code-wrap">
        <div class="ref-code-hdr">
          <span class="ref-code-title" id="ppo-code-title">best iteration output</span>
          <button class="btn-save-ref" onclick="savePpoChoice()">💾 Save</button>
        </div>
        <pre class="ref-code-pre" id="ppo-code-pre"></pre>
      </div>
    </div>
  </div><!-- /rsp-ppo -->

</div><!-- /mp-refactor -->

<script>
const vscode = acquireVsCodeApi();
const BACKEND_URL = 'http://localhost:8000';

const PPO_MODELS = [
  { id:'deepseek-coder:1.3b', rowId:'mc-ds', cls:'ds' },
  { id:'starcoder',           rowId:'mc-sc', cls:'sc' },
  { id:'codellama:7b',        rowId:'mc-cl', cls:'cl' },
];

/* ══════════════════════════════════════════════
   State
══════════════════════════════════════════════ */
let singleFilePath = '', singleDirPath = '', singleModuleName = '';
let zipFilePath = '', refactorPath = '';
let zipAnalysisMode = 'single';
const pollTimers = {};
let connApiOk = false, connOllamaOk = false;

// Single-file approach state
let sgApproach = 'pynguin'; // 'pynguin' | 'llm' | 'hybrid'
let sgAlgos    = new Set(['RANDOM','WHOLE_SUITE','DYNAMOSA']); // for pynguin
let sgLlms     = new Set(['deepseek-coder:1.3b']);              // for llm
let sgHybridAlgo = 'RANDOM';
let sgHybridLlm  = 'deepseek-coder:1.3b';
let sgRunning    = false;
let sgPollTimer  = null;
let sgJobId      = null;
// Results store: { key, label, code, coverage, mutationScore, status, error }
let sgResults = [];

// PPO state
let ppoRunning = false;
let ppoResults = [];
let ppoBestCode = null;
let ppoBestReward = -99;
let ppoSelectedModel = 'deepseek-coder:1.3b';
let ppoPollTimer = null;
let ppoCurrentJobId = null;

// Multi-model state
let mmRunning = false;
let mmResults = [];
let mmSelectedModel = null;
let mmPollTimer = null;
let mmCurrentJobId = null;

/* ══════════════════════════════════════════════
   Connection bar
══════════════════════════════════════════════ */
function triggerCheck() {
  updateConnBar('chk','checking…','chk','checking…');
  vscode.postMessage({ type:'checkBackend' });
}
function updateConnBar(as,at,os,ot) {
  document.getElementById('dot-api').className = 'conn-dot '+as;
  document.getElementById('det-api').textContent = at;
  document.getElementById('dot-ollama').className = 'conn-dot '+os;
  document.getElementById('det-ollama').textContent = ot;
}

/* ══════════════════════════════════════════════
   Tab switching
══════════════════════════════════════════════ */
function oSwitch(id,btn) {
  document.querySelectorAll('.otab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('.mpanel').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById('mp-'+id).classList.add('on');
}
function iSwitch(id,btn) {
  btn.closest('.inner-tabs-wrap').querySelectorAll('.itab').forEach(t=>t.classList.remove('on'));
  const spPre = btn.closest('.mpanel')?.id === 'mp-testgen' ? 'sp-' : 'rsp-';
  document.querySelectorAll('[id^="'+spPre+'"]').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById(spPre+id).classList.add('on');
}
function rSwitch(id,btn) {
  document.querySelectorAll('#mp-refactor .inner-tabs-wrap .itab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('[id^="rsp-"]').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById('rsp-'+id).classList.add('on');
}

/* ══════════════════════════════════════════════
   Approach selector (single-file)
══════════════════════════════════════════════ */
function selectApproach(ap) {
  sgApproach = ap;
  ['pynguin','llm','hybrid'].forEach(a => {
    const card = document.getElementById('ac-'+a);
    const cfg  = document.getElementById('cfg-'+a);
    const radio = card.querySelector('input[type=radio]');
    card.classList.toggle('on', a===ap);
    ['pynguin','llm','hybrid'].forEach(c=>card.classList.remove(c));
    if(a===ap){ card.classList.add(ap); }
    cfg.classList.toggle('on', a===ap);
    radio.checked = (a===ap);
  });
  updateRunBtn();
}

/* ── Pynguin algorithm toggles ── */
function toggleAlgo(algo, rowEl) {
  const cb = rowEl.querySelector('input[type=checkbox]');
  if(sgAlgos.has(algo)){
    if(sgAlgos.size === 1) return; // keep at least 1
    sgAlgos.delete(algo); rowEl.classList.remove('checked'); cb.checked=false;
  } else {
    sgAlgos.add(algo); rowEl.classList.add('checked'); cb.checked=true;
  }
  updateRunBtn();
}

/* ── LLM model toggles ── */
function toggleLlm(model, rowEl) {
  const cb = rowEl.querySelector('input[type=checkbox]');
  if(sgLlms.has(model)){
    if(sgLlms.size === 1) return;
    sgLlms.delete(model); rowEl.classList.remove('checked'); cb.checked=false;
  } else {
    sgLlms.add(model); rowEl.classList.add('checked'); cb.checked=true;
  }
  updateRunBtn();
}

/* ── Hybrid radio selectors ── */
function selectHybridAlgo(algo, rowEl) {
  sgHybridAlgo = algo;
  document.querySelectorAll('#cfg-hybrid .sel-row.hybrid-a').forEach(r=>{
    r.classList.remove('checked'); r.querySelector('input').checked=false;
  });
  rowEl.classList.add('checked'); rowEl.querySelector('input').checked=true;
}
function selectHybridLlm(model, rowEl) {
  sgHybridLlm = model;
  document.querySelectorAll('#cfg-hybrid .sel-row.hybrid-l').forEach(r=>{
    r.classList.remove('checked'); r.querySelector('input').checked=false;
  });
  rowEl.classList.add('checked'); rowEl.querySelector('input').checked=true;
}

function updateRunBtn() {
  const btn = document.getElementById('btn-single');
  const hasFile = !!singleFilePath;
  let valid = hasFile && !sgRunning;
  btn.disabled = !valid;

  // Button label / colour per approach
  btn.className = 'btn ' + (sgApproach==='hybrid' ? 'btn-teal' : sgApproach==='llm' ? 'btn-amber' : 'btn-violet');
  const labels = { pynguin:'⬡ Generate Tests (Pynguin)', llm:'◈ Generate Tests (LLM)', hybrid:'⟳ Generate Tests (Hybrid)' };
  btn.textContent = labels[sgApproach] || '⬡ Generate Tests';

  // Ring colour
  const ring = document.getElementById('single-ring');
  ring.className = 'ring ' + (sgApproach==='hybrid' ? 'teal' : sgApproach==='llm' ? 'amber' : '');

  // Progress bar colour
  const bar = document.getElementById('single-prog-bar');
  bar.className = 'progress-bar ' + (sgApproach==='hybrid' ? 'teal' : sgApproach==='llm' ? 'amber' : '');
}

/* ══════════════════════════════════════════════
   Analysis mode (test gen zip)
══════════════════════════════════════════════ */
function setMode(mode) {
  zipAnalysisMode = mode;
  document.getElementById('mtog-single').classList.toggle('on', mode==='single');
  document.getElementById('mtog-ensemble').classList.toggle('on', mode==='ensemble');
  const desc = document.getElementById('mode-desc');
  if(mode==='single')
    desc.innerHTML='<span class="hi">Single Model</span> — fast analysis using <span class="hi">deepseek-coder:1.3b</span>. Good for most codebases.';
  else
    desc.innerHTML='<span class="hi">Ensemble</span> — runs <span class="hi">deepseek-coder, starcoder &amp; codellama</span> in parallel, then merges the best tests. Slower but higher quality.';
}

/* ══════════════════════════════════════════════
   Test gen polling
══════════════════════════════════════════════ */
function startPolling(scope,jobId) {
  stopPolling(scope);
  pollTimers[scope] = setInterval(()=>vscode.postMessage({type:'pollJob',jobId,scope}),2000);
}
function stopPolling(scope) {
  if(pollTimers[scope]){ clearInterval(pollTimers[scope]); delete pollTimers[scope]; }
}

/* ══════════════════════════════════════════════
   Single-file: generate
══════════════════════════════════════════════ */
function genSingle() {
  if(!singleFilePath){ showPill('single','err','No file selected'); return; }
  if(!connApiOk){ showPill('single','err','API offline — start the backend first'); return; }

  sgRunning = true; sgResults = [];
  document.getElementById('btn-single').disabled = true;
  hidePill('single');
  resetSingleResults();

  setLoader('single', true, 'Submitting…');
  showProgress('single', 0, 'Starting…');

  // Dispatch based on approach
  if(sgApproach === 'pynguin') {
    _dispatchPynguin();
  } else if(sgApproach === 'llm') {
    _dispatchLlm();
  } else {
    _dispatchHybrid();
  }
}

/* ── Dispatch: pynguin ── */
function _dispatchPynguin() {
  // We re-use the existing /generate-tests endpoint which already runs pynguin algos
  // But we need to tell backend which algos. For now we pass all selected; 
  // the backend runs RANDOM/WHOLE_SUITE/DYNAMOSA based on PYNGUIN_ALGORITHMS constant.
  // We filter results client-side to only show selected algos.
  vscode.postMessage({
    type: 'generateSingle',
    filePath: singleFilePath,
    dirPath: singleDirPath,
    approach: 'pynguin',
    selectedAlgos: Array.from(sgAlgos),
  });
}

/* ── Dispatch: LLM ── */
function _dispatchLlm() {
  vscode.postMessage({
    type: 'generateSingle',
    filePath: singleFilePath,
    dirPath: singleDirPath,
    approach: 'llm',
    selectedModels: Array.from(sgLlms),
  });
}

/* ── Dispatch: Hybrid ── */
function _dispatchHybrid() {
  vscode.postMessage({
    type: 'generateSingle',
    filePath: singleFilePath,
    dirPath: singleDirPath,
    approach: 'hybrid',
    hybridAlgo: sgHybridAlgo,
    hybridLlm: sgHybridLlm,
  });
}

function resetSingleResults() {
  document.getElementById('single-results').classList.remove('on');
  document.getElementById('single-metrics-rows').innerHTML = '';
  document.getElementById('single-metrics-head').innerHTML = '';
  document.getElementById('single-file-cards-body').innerHTML = '';
  document.getElementById('single-file-cards').classList.remove('on');
  document.getElementById('single-dl').style.display = 'none';
}

/* ══════════════════════════════════════════════
   Single-file: job done handler
══════════════════════════════════════════════ */
function handleSingleJobComplete(jobData) {
  sgRunning = false;
  setLoader('single', false);
  hideProgress('single');
  document.getElementById('btn-single').disabled = false;
  updateRunBtn();

  if(jobData.status === 'error'){ showPill('single','err', jobData.error||'Job failed'); return; }

  const approach = sgApproach;

  if(approach === 'pynguin') {
    _renderPynguinResults(jobData);
  } else if(approach === 'llm') {
    _renderLlmResults(jobData);
  } else {
    _renderHybridResults(jobData);
  }

  document.getElementById('single-results').classList.add('on');

  if(jobData.download_url){
    const dl = document.getElementById('single-dl');
    dl.href = BACKEND_URL + jobData.download_url;
    dl.style.display = '';
  }
}

/* ── Render: pynguin results ── */
function _renderPynguinResults(jobData) {
  const results = (jobData.results || []).filter(r => sgAlgos.has(r.algorithm));
  const ok = results.filter(r=>r.status==='success').length;
  showPill('single','ok', ok+'/'+results.length+' algorithm'+(results.length!==1?'s':'')+' succeeded');

  // Header
  document.getElementById('single-metrics-head').innerHTML =
    '<div class="gt-row pynguin-row hd">' +
      '<div class="gt-cell">Algorithm</div>' +
      '<div class="gt-cell">Tests</div>' +
      '<div class="gt-cell right">Coverage</div>' +
      '<div class="gt-cell right">Mutation</div>' +
      '<div class="gt-cell right">Status</div>' +
    '</div>';

  // Rows
  const rowsEl = document.getElementById('single-metrics-rows');
  rowsEl.innerHTML = '';
  results.forEach(r => {
    const cov = r.metrics?.coverage_percent ?? Math.round((r.coverage||0)*100);
    const mut = r.metrics?.mutation_score!=null ? Math.round(r.metrics.mutation_score*100) : Math.round((r.mutation_score||0)*100);
    const algo = (r.algorithm||'').toLowerCase();
    const row = document.createElement('div');
    row.className = 'gt-row pynguin-row';
    row.innerHTML =
      '<div class="gt-cell"><span class="algo-badge '+algo+'">'+esc(r.algorithm||'—')+'</span></div>'+
      '<div class="gt-cell">'+(r.num_tests!=null?r.num_tests+' tests':'—')+'</div>'+
      '<div class="gt-cell right '+(r.status==='success'?scoreClass(cov):'score-d')+'">'+(r.status==='success'?cov+'%':'—')+'</div>'+
      '<div class="gt-cell right '+(r.status==='success'?scoreClass(mut):'score-d')+'">'+(r.status==='success'?mut+'%':'—')+'</div>'+
      '<div class="gt-cell right">'+(r.status==='success'?'<span class="tag ok">ok</span>':'<span class="tag err" title="'+esc(r.error||'')+'">error</span>')+'</div>';
    rowsEl.appendChild(row);
  });

  // File cards (one per algo)
  _renderFileCards(results.map(r => ({
    label: r.algorithm,
    labelClass: 'algo-badge '+(r.algorithm||'').toLowerCase(),
    code: r.content,
    suggestedName: 'test_'+singleModuleName+'_'+(r.algorithm||'algo').toLowerCase()+'.py',
    status: r.status,
  })));
}

/* ── Render: LLM results ── */
function _renderLlmResults(jobData) {
  // jobData.results is an array with one entry per model (backend runs sequentially)
  const results = jobData.results || [];
  const ok = results.filter(r=>r.status==='success').length;
  showPill('single','ok', ok+'/'+results.length+' model'+(results.length!==1?'s':'')+' succeeded');

  document.getElementById('single-metrics-head').innerHTML =
    '<div class="gt-row llm-row hd">' +
      '<div class="gt-cell">Model</div>' +
      '<div class="gt-cell right">Coverage</div>' +
      '<div class="gt-cell right">Mutation</div>' +
      '<div class="gt-cell right">Status</div>' +
    '</div>';

  const rowsEl = document.getElementById('single-metrics-rows');
  rowsEl.innerHTML = '';
  results.forEach(r => {
    const cov = r.metrics?.coverage_percent ?? Math.round((r.coverage||0)*100);
    const mut = r.metrics?.mutation_score!=null ? Math.round(r.metrics.mutation_score*100) : Math.round((r.mutation_score||0)*100);
    const modelCls = _modelCls(r.model||r.file||'');
    const row = document.createElement('div');
    row.className = 'gt-row llm-row';
    row.innerHTML =
      '<div class="gt-cell"><span class="model-badge '+modelCls+'">'+esc(_modelShort(r.model||r.file||'—'))+'</span></div>'+
      '<div class="gt-cell right '+(r.status==='success'?scoreClass(cov):'score-d')+'">'+(r.status==='success'?cov+'%':'—')+'</div>'+
      '<div class="gt-cell right '+(r.status==='success'?scoreClass(mut):'score-d')+'">'+(r.status==='success'?mut+'%':'—')+'</div>'+
      '<div class="gt-cell right">'+(r.status==='success'?'<span class="tag ok">ok</span>':'<span class="tag err" title="'+esc(r.error||'')+'">error</span>')+'</div>';
    rowsEl.appendChild(row);
  });

  _renderFileCards(results.map(r => ({
    label: _modelShort(r.model||r.file||'model'),
    labelClass: 'model-badge '+_modelCls(r.model||r.file||''),
    code: r.content,
    suggestedName: 'test_'+singleModuleName+'_'+_safeFileName(r.model||'llm')+'.py',
    status: r.status,
  })));
}

/* ── Render: Hybrid results ── */
function _renderHybridResults(jobData) {
  // Results: algo raw output + refined output
  // jobData.results = array of algo result(s), jobData.refinement = {status, refined_code}
  const algoResults = (jobData.results || []).filter(r => r.algorithm === sgHybridAlgo);
  const refinement  = jobData.refinement || null;

  const algoOk = algoResults.some(r=>r.status==='success');
  const refOk  = refinement?.status === 'success';
  showPill('single','ok', (algoOk?'✓ Algo':'✗ Algo')+' · '+(refOk?'✓ LLM refined':'✗ LLM failed'));

  document.getElementById('single-metrics-head').innerHTML =
    '<div class="gt-row hybrid-row hd">' +
      '<div class="gt-cell">Algorithm</div>' +
      '<div class="gt-cell">LLM</div>' +
      '<div class="gt-cell right">Coverage</div>' +
      '<div class="gt-cell right">Mutation</div>' +
      '<div class="gt-cell right">Status</div>' +
    '</div>';

  const rowsEl = document.getElementById('single-metrics-rows');
  rowsEl.innerHTML = '';

  // Algo raw row
  if(algoResults.length) {
    const r = algoResults[0];
    const cov = r.metrics?.coverage_percent ?? Math.round((r.coverage||0)*100);
    const mut = r.metrics?.mutation_score!=null ? Math.round(r.metrics.mutation_score*100) : Math.round((r.mutation_score||0)*100);
    const algoLow = (r.algorithm||'').toLowerCase();
    const rawRow = document.createElement('div');
    rawRow.className = 'gt-row hybrid-row';
    rawRow.innerHTML =
      '<div class="gt-cell"><span class="algo-badge '+algoLow+'">'+esc(r.algorithm||'—')+'</span></div>'+
      '<div class="gt-cell"><span class="tag skip">raw</span></div>'+
      '<div class="gt-cell right '+(r.status==='success'?scoreClass(cov):'score-d')+'">'+(r.status==='success'?cov+'%':'—')+'</div>'+
      '<div class="gt-cell right '+(r.status==='success'?scoreClass(mut):'score-d')+'">'+(r.status==='success'?mut+'%':'—')+'</div>'+
      '<div class="gt-cell right">'+(r.status==='success'?'<span class="tag ok">ok</span>':'<span class="tag err">error</span>')+'</div>';
    rowsEl.appendChild(rawRow);
  }

  // Refined row
  const refRow = document.createElement('div');
  refRow.className = 'gt-row hybrid-row';
  const algoLow = sgHybridAlgo.toLowerCase();
  const modelCls = _modelCls(sgHybridLlm);
  refRow.innerHTML =
    '<div class="gt-cell"><span class="algo-badge '+algoLow+'">'+esc(sgHybridAlgo)+'</span></div>'+
    '<div class="gt-cell"><span class="model-badge '+modelCls+'">'+esc(_modelShort(sgHybridLlm))+'</span></div>'+
    '<div class="gt-cell right score-d">—</div>'+
    '<div class="gt-cell right score-d">—</div>'+
    '<div class="gt-cell right">'+(refOk?'<span class="tag ok">refined</span>':'<span class="tag err">failed</span>')+'</div>';
  rowsEl.appendChild(refRow);

  // File cards: algo raw + refined
  const cards = [];
  if(algoResults.length && algoResults[0].content) {
    const r = algoResults[0];
    cards.push({
      label: r.algorithm+' (raw)',
      labelClass: 'algo-badge '+(r.algorithm||'').toLowerCase(),
      code: r.content,
      suggestedName: 'test_'+singleModuleName+'_'+algoLow+'_raw.py',
      status: r.status,
    });
  }
  if(refOk && refinement.refined_code) {
    cards.push({
      label: _modelShort(sgHybridLlm)+' (refined)',
      labelClass: 'model-badge '+_modelCls(sgHybridLlm),
      code: refinement.refined_code,
      suggestedName: 'test_'+singleModuleName+'_'+algoLow+'_refined.py',
      status: 'success',
    });
  }
  _renderFileCards(cards);
}

/* ── File card renderer ── */
function _renderFileCards(cards) {
  const body = document.getElementById('single-file-cards-body');
  body.innerHTML = '';
  if(!cards.length) return;

  cards.forEach((c, idx) => {
    const collapsed = idx > 0; // first card expanded, rest collapsed
    const cardEl = document.createElement('div');
    cardEl.className = 'test-file-card';
    cardEl.id = 'tfc-'+idx;

    const hasCode = !!(c.code && c.code.trim());
    const hdr = document.createElement('div');
    hdr.className = 'tfc-hdr';
    hdr.innerHTML =
      '<span class="tfc-icon">📄</span>'+
      '<span class="tfc-name">'+esc(c.suggestedName)+'</span>'+
      '<span class="'+c.labelClass+' tfc-tag">'+esc(c.label)+'</span>'+
      (collapsed ? '<button class="tfc-toggle" onclick="toggleCard('+idx+')">▶ show</button>' : '<button class="tfc-toggle" onclick="toggleCard('+idx+')">▼ hide</button>')+
      '<button class="tfc-save" id="tfc-save-'+idx+'" '+(hasCode&&c.status==='success'?'':'disabled')+
        ' onclick="saveCard('+idx+')">💾 Save</button>';
    cardEl.appendChild(hdr);

    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'tfc-body';
    bodyDiv.id = 'tfc-body-'+idx;
    bodyDiv.style.display = collapsed ? 'none' : 'block';
    if(hasCode && c.status==='success') {
      const pre = document.createElement('pre');
      pre.className = 'tfc-pre';
      pre.textContent = c.code;
      bodyDiv.appendChild(pre);
    } else {
      bodyDiv.innerHTML = '<div class="tfc-empty">'+(c.status==='error'?'Generation failed — no output':'No code available')+'</div>';
    }
    cardEl.appendChild(bodyDiv);
    body.appendChild(cardEl);
  });

  // Store card data for save handler
  window._sgCardData = cards;
  document.getElementById('single-file-cards').classList.add('on');
}

function toggleCard(idx) {
  const bodyDiv = document.getElementById('tfc-body-'+idx);
  const hdr = document.getElementById('tfc-'+idx).querySelector('.tfc-hdr');
  const toggleBtn = hdr.querySelector('.tfc-toggle');
  const hidden = bodyDiv.style.display === 'none';
  bodyDiv.style.display = hidden ? 'block' : 'none';
  toggleBtn.textContent = hidden ? '▼ hide' : '▶ show';
}

function saveCard(idx) {
  const cards = window._sgCardData || [];
  const c = cards[idx];
  if(!c || !c.code) return;
  vscode.postMessage({
    type: 'saveTestFile',
    filePath: singleFilePath,
    code: c.code,
    suggestedName: c.suggestedName,
  });
}

/* ══════════════════════════════════════════════
   Single-file polling callbacks
══════════════════════════════════════════════ */
function onSingleJobStatus(s) {
  if(s.status === 'queued' || s.status === 'processing') {
    const pct = s.progress || 0;
    const lbl = s.phase_label || 'Running…';
    setLoader('single', true, lbl);
    showProgress('single', pct, pct+'% — '+lbl);

    // Show partial pynguin results during processing
    if(sgApproach === 'pynguin' && s.algo_results && s.algo_results.length) {
      const partial = s.algo_results.filter(r => sgAlgos.has(r.algorithm));
      if(partial.length) {
        // Build partial table
        document.getElementById('single-metrics-head').innerHTML =
          '<div class="gt-row pynguin-row hd">' +
            '<div class="gt-cell">Algorithm</div>'+
            '<div class="gt-cell">Tests</div>'+
            '<div class="gt-cell right">Coverage</div>'+
            '<div class="gt-cell right">Mutation</div>'+
            '<div class="gt-cell right">Status</div>'+
          '</div>';
        const rowsEl = document.getElementById('single-metrics-rows');
        rowsEl.innerHTML = '';
        partial.forEach(r => {
          const row = document.createElement('div');
          row.className = 'gt-row pynguin-row';
          row.innerHTML =
            '<div class="gt-cell"><span class="algo-badge '+(r.algorithm||'').toLowerCase()+'">'+esc(r.algorithm||'—')+'</span></div>'+
            '<div class="gt-cell">'+(r.num_tests!=null?r.num_tests+' tests':'…')+'</div>'+
            '<div class="gt-cell right score-d">…</div>'+
            '<div class="gt-cell right score-d">…</div>'+
            '<div class="gt-cell right"><span class="tag run">…</span></div>';
          rowsEl.appendChild(row);
        });
        document.getElementById('single-results').classList.add('on');
      }
    }
  } else {
    handleSingleJobComplete(s);
  }
}

/* ══════════════════════════════════════════════
   Model helpers
══════════════════════════════════════════════ */
function _modelCls(model) {
  if(model.includes('deepseek')) return 'ds';
  if(model.includes('codellama')) return 'cl';
  return 'ds';
}
function _modelShort(model) {
  if(model.includes('deepseek-coder')) return 'deepseek';
  if(model.includes('codellama')) return 'codellama';
  return model.split(':')[0];
}
function _safeFileName(model) {
  return model.replace(/[^a-z0-9]/gi,'_').toLowerCase();
}

/* ══════════════════════════════════════════════
   PPO model selector (radio)
══════════════════════════════════════════════ */
function selectPpoModel(modelId, rowEl) {
  ppoSelectedModel = modelId;
  document.querySelectorAll('#rsp-ppo .mc-row').forEach(r=>{
    r.classList.remove('checked');
    r.querySelector('input[type=radio]').checked = false;
  });
  rowEl.classList.add('checked');
  rowEl.querySelector('input[type=radio]').checked = true;
  updatePpoBtn();
}
function updatePpoBtn() {
  const btn = document.getElementById('btn-ppo-run');
  btn.disabled = !refactorPath || ppoRunning;
}

/* ══════════════════════════════════════════════
   Multi-model run
══════════════════════════════════════════════ */
function runMultiModel() {
  if(!refactorPath){ showPill('mm','err','No Python file open'); return; }
  if(!connApiOk){ showPill('mm','err','API offline — start the backend first'); return; }

  mmRunning = true; mmResults = []; mmSelectedModel = null;
  document.getElementById('btn-mm-run').disabled = true;
  document.getElementById('mm-metrics-section').classList.remove('on');
  document.getElementById('mm-code-section').classList.remove('on');
  document.getElementById('mm-mrows').innerHTML = '';
  document.getElementById('mm-model-btns').innerHTML = '';
  document.getElementById('mm-code-pre').textContent = '';
  hidePill('mm');
  setLoader('mm', true, 'Running models one at a time (3-6 min)…');
  setRefProgress('mm', 0, 'Starting…');

  vscode.postMessage({ type:'refactorMultiModel', filePath:refactorPath });
}

function startMmPoll(jobId) {
  stopMmPoll();
  mmCurrentJobId = jobId;
  mmPollTimer = setInterval(()=>vscode.postMessage({type:'pollJob',jobId,scope:'mm_refactor'}),2000);
}
function stopMmPoll() {
  if(mmPollTimer){ clearInterval(mmPollTimer); mmPollTimer=null; }
}

function onMmJobStatus(s) {
  if(s.status === 'queued' || s.status === 'processing') {
    const pct = s.progress || 0;
    setRefProgress('mm', pct, pct+'% — running models…');
    setLoader('mm', true, 'Running models… '+pct+'%');
    if(s.partial_results) {
      s.partial_results.forEach(r => upsertMmRow(r));
    }
  } else {
    onMmJobDone(s);
  }
}

function onMmJobDone(s) {
  stopMmPoll();
  mmRunning = false;
  setLoader('mm', false);
  hideProgress('mm');
  document.getElementById('btn-mm-run').disabled = false;

  if(s.status === 'error'){ showPill('mm','err', s.error||'Job failed'); return; }

  const results = s.results || [];
  mmResults = results;
  const ok = results.filter(r=>r.status==='success').length;
  showPill('mm','ok', ok+'/'+results.length+' models succeeded');
  results.forEach(r => upsertMmRow(r));
  document.getElementById('mm-metrics-section').classList.add('on');

  const withReward = results.filter(r=>r.reward!=null);
  if(withReward.length) {
    const best = withReward.reduce((a,b)=>b.reward>a.reward?b:a);
    const el = document.getElementById('mm-mrow-'+safeId(best.model));
    if(el) el.classList.add('best-row');
  }

  results.forEach(r => {
    if(r.refactored_code) addMmCodeBtn(r.model, r.refactored_code);
  });
  if(mmSelectedModel) document.getElementById('mm-code-section').classList.add('on');
}

function upsertMmRow(r) {
  const rowId = 'mm-mrow-'+safeId(r.model);
  let row = document.getElementById(rowId);
  const mc = PPO_MODELS.find(x=>x.id===r.model);
  const isLoading = (r.status === 'pending' || r.status === 'processing');

  const d = r.delta || {};
  const after = r.after || {};

  const reward = r.reward;
  const passRate = reward != null ? Math.min(100, Math.max(0, Math.round((reward+1)/2*100))) : null;
  const passRateStr = passRate != null ? passRate+'%' : '—';
  const passRateCls = passRate == null ? 'delta-dim' : passRate >= 70 ? 'delta-pos' : passRate >= 40 ? 'delta-neu' : 'delta-neg';

  const ccDelta = d.cyclomatic_delta;
  const locDelta = d.loc_delta;

  let mi = null;
  if(after.cyclomatic != null && after.loc != null && after.halstead != null) {
    const raw = 171 - 5.2*Math.log(Math.max(after.halstead,1)) - 0.23*after.cyclomatic - 16.2*Math.log(Math.max(after.loc,1));
    mi = Math.min(100, Math.max(0, Math.round(raw / 1.71)));
  }
  const miStr = mi != null ? mi : '—';
  const miCls = mi == null ? 'delta-dim' : mi >= 65 ? 'delta-pos' : mi >= 40 ? 'delta-neu' : 'delta-neg';

  const pep8After = after.pep8 != null ? after.pep8 : null;
  let pylint = null;
  if(pep8After != null) {
    pylint = Math.max(0, Math.min(10, +(10 - pep8After * 0.1).toFixed(1)));
  }
  const pylintStr = pylint != null ? pylint.toFixed(1) : '—';
  const pylintCls = pylint == null ? 'delta-dim' : pylint >= 7 ? 'delta-pos' : pylint >= 5 ? 'delta-neu' : 'delta-neg';

  const fmtD = v => v==null ? '—' : (v>0?'+':'')+v.toFixed(1);
  const dcD  = v => v==null?'delta-dim':v>0?'delta-pos':v<0?'delta-neg':'delta-neu';

  const errorTitle = r.error ? esc(r.error).replace(/"/g, '&quot;') : '';
  const stateStr = isLoading ? '<span class="tag run sm">…</span>'
                : r.status === 'error' ? '<span class="tag err sm" title="'+errorTitle+'" style="cursor:help">err ⓘ</span>'
                : '';

  const html =
    '<span class="mc-badge '+(mc?.cls||'')+'">'+esc(r.model)+'</span>'+
    '<span class="'+passRateCls+'">'+passRateStr+'</span>'+
    '<span class="'+dcD(ccDelta)+'">'+fmtD(ccDelta)+'</span>'+
    '<span class="'+dcD(locDelta)+'">'+fmtD(locDelta)+'</span>'+
    '<span class="'+miCls+'">'+miStr+'</span>'+
    '<span class="'+pylintCls+'">'+pylintStr+stateStr+'</span>';

  document.getElementById('mm-metrics-section').classList.add('on');
  if(!row) {
    row = document.createElement('div');
    row.className = 'mm-mrow'+(isLoading?' loading-row':'');
    row.id = rowId;
    document.getElementById('mm-mrows').appendChild(row);
  } else {
    row.classList.toggle('loading-row', isLoading);
  }
  row.innerHTML = html;
}

function addMmCodeBtn(model, code) {
  const mc = PPO_MODELS.find(x=>x.id===model);
  if(document.getElementById('mmbtn-'+safeId(model))) return;
  const b = document.createElement('button');
  b.className = 'ref-mbtn '+(mc?.cls||'');
  b.id = 'mmbtn-'+safeId(model);
  b.textContent = model.split(':')[0];
  b.onclick = () => {
    document.querySelectorAll('.ref-mbtn').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    mmSelectedModel = model;
    document.getElementById('mm-code-pre').textContent = code;
    document.getElementById('mm-code-title').textContent = 'refactored by '+model;
  };
  document.getElementById('mm-model-btns').appendChild(b);
  if(!mmSelectedModel) {
    b.classList.add('on');
    mmSelectedModel = model;
    document.getElementById('mm-code-pre').textContent = code;
    document.getElementById('mm-code-title').textContent = 'refactored by '+model;
    document.getElementById('mm-code-section').classList.add('on');
  }
}

function saveMmChoice() {
  if(!mmSelectedModel){ showPill('mm','err','Select a model first'); return; }
  const r = mmResults.find(x=>x.model===mmSelectedModel);
  if(!r||!r.refactored_code){ showPill('mm','err','No code to save'); return; }
  vscode.postMessage({ type:'saveRefactored', filePath:refactorPath, code:r.refactored_code, model:mmSelectedModel });
}

/* ══════════════════════════════════════════════
   PPO run
══════════════════════════════════════════════ */
function runPpo() {
  if(!refactorPath){ showPill('ppo','err','No Python file open'); return; }
  if(!connApiOk){ showPill('ppo','err','API offline — start the backend first'); return; }

  ppoRunning = true; ppoResults = []; ppoBestCode = null; ppoBestReward = -99;
  document.getElementById('btn-ppo-run').disabled = true;
  document.getElementById('ppo-metrics-section').classList.remove('on');
  document.getElementById('ppo-code-section').classList.remove('on');
  document.getElementById('ppo-mrows').innerHTML = '';
  document.getElementById('ppo-code-pre').textContent = '';
  document.getElementById('ppo-steps').innerHTML = '';
  hidePill('ppo');
  setLoader('ppo', true, 'Submitting PPO job…');
  setRefProgress('ppo', 0, 'Starting…');

  vscode.postMessage({ type:'refactorSingleModel', filePath:refactorPath, model:ppoSelectedModel });
}

function startPpoPoll(jobId) {
  stopPpoPoll();
  ppoCurrentJobId = jobId;
  ppoPollTimer = setInterval(()=>vscode.postMessage({type:'pollJob',jobId,scope:'ppo_refactor'}),2000);
}
function stopPpoPoll() {
  if(ppoPollTimer){ clearInterval(ppoPollTimer); ppoPollTimer=null; }
}

function onPpoJobStatus(s) {
  if(s.status === 'queued' || s.status === 'processing') {
    const pct = s.progress || 0;
    const lbl = s.phase_label || 'Running PPO…';
    setRefProgress('ppo', pct, lbl);
    setLoader('ppo', true, lbl);
    if(s.iterations && s.iterations.length) {
      renderPpoIterations(s.iterations);
    }
  } else {
    onPpoJobDone(s);
  }
}

function renderPpoIterations(iterations) {
  const stepsEl = document.getElementById('ppo-steps');
  stepsEl.innerHTML = '';
  document.getElementById('ppo-stepper').classList.add('on');
  iterations.forEach((it) => {
    const div = document.createElement('div');
    div.className = 'ens-step done';
    div.innerHTML =
      '<div class="ens-step-top">' +
        '<span class="step-ico">✓</span>' +
        '<span class="step-name">Iteration '+it.iteration+'</span>' +
        '<span class="step-status">reward: '+(it.reward!=null?it.reward.toFixed(3):'—')+'</span>' +
      '</div>';
    stepsEl.appendChild(div);
  });

  document.getElementById('ppo-metrics-section').classList.add('on');
  document.getElementById('ppo-mrows').innerHTML = '';
  iterations.forEach(it => {
    upsertPpoRow(it.iteration, it.reward, it.delta || {}, 'ok');
  });
}

function onPpoJobDone(s) {
  stopPpoPoll();
  ppoRunning = false;
  setLoader('ppo', false);
  hideProgress('ppo');
  document.getElementById('btn-ppo-run').disabled = false;
  document.getElementById('ppo-stepper').classList.remove('on');

  if(s.status === 'error'){ showPill('ppo','err', s.error||'Job failed'); return; }

  const iters = s.iterations || [];
  const totalIter = s.total_iterations || iters.length;
  const bestReward = s.best_reward != null ? s.best_reward.toFixed(3) : '—';
  showPill('ppo','ok', totalIter+' iteration'+(totalIter!==1?'s':'')+' — best reward: '+bestReward);

  document.getElementById('ppo-mrows').innerHTML = '';
  iters.forEach(it => upsertPpoRow(it.iteration, it.reward, it.delta||{}, 'ok'));
  if(iters.length) document.getElementById('ppo-metrics-section').classList.add('on');

  if(iters.length) {
    const best = iters.reduce((a,b)=>b.reward>a.reward?b:a);
    const el = document.getElementById('ppo-iter-'+best.iteration);
    if(el) el.classList.add('best-row');
  }

  const bestCode = s.best_code || (iters.length ? iters[iters.length-1].code : null);
  if(bestCode) {
    document.getElementById('ppo-code-pre').textContent = bestCode;
    document.getElementById('ppo-code-title').textContent =
      'best refactoring (iter '+(iters.reduce((a,b)=>b.reward>a.reward?b:a, {iteration:'?',reward:-99}).iteration)+')';
    document.getElementById('ppo-code-section').classList.add('on');
    ppoBestCode = bestCode;
  }
}

function upsertPpoRow(iterNum, reward, delta, state) {
  const rowId = 'ppo-iter-'+iterNum;
  let row = document.getElementById(rowId);
  const d = delta || {};

  const fmt = v => v==null ? '—' : (v>0?'+':'')+v.toFixed(1);
  const dc = v => v==null?'delta-dim':v>0?'delta-pos':v<0?'delta-neg':'delta-neu';
  const rw = reward!=null ? reward.toFixed(3) : '—';
  const rwCls = reward==null?'delta-dim':reward>=0.3?'delta-pos':reward>=0?'delta-neu':'delta-neg';
  const stateTag = state==='run'?'<span class="tag run sm">…</span>':'';

  const html =
    '<span style="color:var(--muted)">iter '+iterNum+'</span>'+
    '<span class="'+dc(d.cyclomatic_delta)+'">'+fmt(d.cyclomatic_delta)+'</span>'+
    '<span class="'+dc(d.pep8_delta)+'">'+fmt(d.pep8_delta)+'</span>'+
    '<span class="'+dc(d.halstead_delta)+'">'+fmt(d.halstead_delta)+'</span>'+
    '<span class="'+dc(d.loc_delta)+'">'+fmt(d.loc_delta)+'</span>'+
    '<span class="reward-cell '+rwCls+'">'+rw+stateTag+'</span>';

  if(!row) {
    row = document.createElement('div');
    row.className = 'ppo-mrow';
    row.id = rowId;
    document.getElementById('ppo-mrows').appendChild(row);
  }
  row.innerHTML = html;
}

function savePpoChoice() {
  if(!ppoBestCode){ showPill('ppo','err','No code to save'); return; }
  vscode.postMessage({ type:'saveRefactored', filePath:refactorPath, code:ppoBestCode, model:ppoSelectedModel });
}

/* ══════════════════════════════════════════════
   Refactor file controls
══════════════════════════════════════════════ */
function clearRef() {
  refactorPath = '';
  const n = document.getElementById('ref-name');
  n.textContent = 'Open a Python file in the editor'; n.classList.add('empty');
  document.getElementById('ref-sub').textContent = '';
  document.getElementById('ref-dismiss').classList.remove('visible');
  document.getElementById('mm-metrics-section').classList.remove('on');
  document.getElementById('mm-code-section').classList.remove('on');
  hideProgress('mm'); setLoader('mm',false); hidePill('mm');
  document.getElementById('btn-mm-run').disabled = true;
  document.getElementById('ppo-metrics-section').classList.remove('on');
  document.getElementById('ppo-code-section').classList.remove('on');
  document.getElementById('ppo-stepper').classList.remove('on');
  hideProgress('ppo'); setLoader('ppo',false); hidePill('ppo');
  document.getElementById('btn-ppo-run').disabled = true;
}

/* ══════════════════════════════════════════════
   Test gen file helpers
══════════════════════════════════════════════ */
function pickSingle(){ vscode.postMessage({type:'pickSingleFile',rootFolder:singleDirPath}); }
function setSingleFile(fp,dir,name) {
  singleFilePath=fp; singleDirPath=dir||fp.replace(/[\\/][^\\/]+$/,'');
  singleModuleName = (name||fp.split(/[\\/]/).pop()).replace(/\.py$/, '');
  const nameEl=document.getElementById('sf-name');
  nameEl.textContent=name||fp.split(/[\\/]/).pop(); nameEl.classList.remove('empty');
  document.getElementById('sf-dir').textContent=singleDirPath;
  document.getElementById('sf-card').classList.add('active');
  document.getElementById('sf-dismiss').classList.add('visible');
  updateRunBtn();
}
function clearSingle() {
  singleFilePath=''; singleDirPath=''; singleModuleName='';
  const n=document.getElementById('sf-name');
  n.textContent='Open a .py file or browse below'; n.classList.add('empty');
  document.getElementById('sf-dir').textContent='';
  document.getElementById('sf-card').classList.remove('active');
  document.getElementById('sf-dismiss').classList.remove('visible');
  document.getElementById('sf-auto-badge').style.display='none';
  updateRunBtn();
  hidePill('single');
  resetSingleResults();
}

/* ══════════════════════════════════════════════
   Test gen ZIP
══════════════════════════════════════════════ */
function pickZip(){ vscode.postMessage({type:'pickZipFile'}); }
function clearZip() {
  zipFilePath='';
  const n=document.getElementById('zip-name');
  n.textContent='No archive selected'; n.classList.add('empty');
  document.getElementById('zip-sub').textContent='';
  document.getElementById('zip-card').classList.remove('active');
  document.getElementById('zip-dismiss').classList.remove('visible');
  document.getElementById('btn-zip').disabled=true;
  hidePill('zip');
  document.getElementById('zr-main').classList.remove('on');
}
function genZip() {
  if(!zipFilePath){ showPill('zip','err','No ZIP selected'); return; }
  if(!connApiOk){ showPill('zip','err','API offline — start the backend first'); return; }
  setLoader('zip',true,zipAnalysisMode==='ensemble'?'Uploading (ensemble)…':'Uploading ZIP…');
  setRunning('zip',true); hidePill('zip');
  document.getElementById('zr-main').classList.remove('on');
  document.getElementById('btn-zip').disabled=true;
  document.getElementById('zip-prog-wrap').style.display='none';
  document.getElementById('zip-prog-lbl').style.display='none';
  vscode.postMessage({type:'generateZip',zipPath:zipFilePath,analysisMode:zipAnalysisMode});
}

/* ══════════════════════════════════════════════
   Shared UI helpers
══════════════════════════════════════════════ */
function setLoader(scope,on,msg) {
  const el=document.getElementById('ld-'+scope); if(!el) return;
  el.classList.toggle('on',on);
  if(msg){const t=el.querySelector('.loader-txt');if(t)t.textContent=msg;}
}
function showPill(scope,type,msg) {
  const el=document.getElementById('pill-'+scope); if(!el) return;
  el.className='pill on '+type;
  const t=document.getElementById('pill-'+scope+'-txt'); if(t) t.textContent=msg;
}
function hidePill(scope){ const el=document.getElementById('pill-'+scope); if(el) el.classList.remove('on'); }
function showProgress(scope,pct,label) {
  const w=document.getElementById(scope+'-prog-wrap'); if(w) w.style.display='block';
  const l=document.getElementById(scope+'-prog-lbl'); if(l){ l.style.display='block'; l.textContent=label; }
  const b=document.getElementById(scope+'-prog-bar'); if(b) b.style.width=pct+'%';
}
function hideProgress(scope) {
  const w=document.getElementById(scope+'-prog-wrap'); if(w) w.style.display='none';
  const l=document.getElementById(scope+'-prog-lbl'); if(l) l.style.display='none';
}
function setRefProgress(scope,pct,label) {
  const w=document.getElementById(scope+'-prog-wrap'); if(w) w.style.display='block';
  const l=document.getElementById(scope+'-prog-lbl'); if(l){ l.style.display='block'; l.textContent=label; }
  const b=document.getElementById(scope+'-prog-bar'); if(b) b.style.width=pct+'%';
}
function setRunning(scope,running) {
  if(scope==='zip'){
    document.getElementById('btn-browse-zip').disabled=running;
    document.getElementById('zip-dismiss').disabled=running;
    document.getElementById('mtog-single').disabled=running;
    document.getElementById('mtog-ensemble').disabled=running;
  }
}
function scoreClass(pct){ return pct>=70?'score-g':pct>=40?'score-a':'score-r'; }
function esc(t){ const d=document.createElement('div');d.textContent=t;return d.innerHTML; }
function safeId(s){ return s.replace(/[^a-zA-Z0-9]/g,'_'); }

/* ══════════════════════════════════════════════
   ZIP result rendering
══════════════════════════════════════════════ */
function handleZipJobComplete(scope,jobData) {
  stopPolling(scope); setLoader(scope,false); hideProgress(scope); setRunning(scope,false);
  document.getElementById('btn-zip').disabled=false;
  if(jobData.status==='error'){ showPill(scope,'err',jobData.error||'Job failed'); return; }
  const results=jobData.results||[];
  const ok=results.filter(r=>r.status==='success').length;
  const mode=jobData.analysis_mode||zipAnalysisMode;
  showPill('zip','ok',ok+'/'+results.length+' files analysed ('+mode+')');
  renderZipRows(results,document.getElementById('zr-rows'));
  if(jobData.download_url){ const dl=document.getElementById('zr-dl'); dl.href=BACKEND_URL+jobData.download_url; dl.style.display=''; }
  document.getElementById('zr-main').classList.add('on');
}

function renderZipRows(results,container) {
  container.innerHTML='';
  results.forEach(r=>{
    const cov=r.metrics?.coverage_percent??(r.coverage!=null?Math.round(r.coverage*100):null);
    const mut=r.metrics?.mutation_score!=null?Math.round(r.metrics.mutation_score*100):r.mutation_score!=null?Math.round(r.mutation_score*100):null;
    const isEns=(r.generation_method||'')===('ensemble');
    const row=document.createElement('div'); row.className='zr-row';
    row.innerHTML=
      '<div class="mt-file" title="'+esc(r.file)+'">'+esc(r.file)+'</div>'+
      '<div class="mt-val '+(cov!=null?scoreClass(cov):'')+'">'+(cov!=null?cov+'%':'—')+'</div>'+
      '<div class="mt-val '+(mut!=null?scoreClass(mut):'')+'">'+(mut!=null?mut+'%':'—')+'</div>'+
      '<div class="mt-val"><span class="tag '+(isEns?'ens':'ok')+'">'+(isEns?'ensemble':'single')+'</span></div>'+
      '<div class="mt-val"><span class="tag '+(r.status==='success'?'ok':'err')+'">'+r.status+'</span></div>';
    container.appendChild(row);
  });
}

/* ══════════════════════════════════════════════
   Message handler
══════════════════════════════════════════════ */
window.addEventListener('message', ev=>{
  const m = ev.data;
  switch(m.type){

    case 'activeFileChanged': {
      const fp=m.filePath||'', name=fp.split(/[\\/]/).pop(), dir=fp.replace(/[\\/][^\\/]+$/,'');
      document.getElementById('sf-auto-badge').style.display='';
      setSingleFile(fp,dir,name);
      refactorPath = fp;
      const rn=document.getElementById('ref-name');
      rn.textContent=fp||'No Python file open'; rn.classList.toggle('empty',!fp);
      document.getElementById('ref-sub').textContent=fp?dir:'';
      const rd=document.getElementById('ref-dismiss');
      if(fp) rd.classList.add('visible'); else rd.classList.remove('visible');
      document.getElementById('btn-mm-run').disabled = !fp;
      updatePpoBtn();
      break;
    }

    case 'singleFilePicked':
      document.getElementById('sf-auto-badge').style.display='none';
      setSingleFile(m.filePath,m.dirPath,m.fileName);
      break;

    case 'zipFilePicked': {
      zipFilePath=m.zipPath;
      const zn=document.getElementById('zip-name');
      zn.textContent=m.zipName; zn.classList.remove('empty');
      document.getElementById('zip-sub').textContent=m.zipPath;
      document.getElementById('zip-card').classList.add('active');
      document.getElementById('zip-dismiss').classList.add('visible');
      document.getElementById('btn-zip').disabled=false;
      break;
    }

    case 'generationStarted': break;

    case 'jobStarted': {
      const scope=m.scope;
      if(scope==='single') {
        // sgPollTimer already handled by this branch
        setLoader('single', true, 'Running pipeline…');
        showProgress('single', 0, 'Starting…');
        startPolling(scope, m.jobId);
        sgJobId = m.jobId;
      } else if(scope==='zip'){
        setLoader(scope,true,'Running pipeline…');
        showProgress(scope,0,'Starting…');
        startPolling(scope,m.jobId);
      }
      break;
    }

    case 'jobStatus': {
      const scope=m.scope, s=m.status;

      if(scope==='ppo_refactor'){ onPpoJobStatus(s); break; }
      if(scope==='mm_refactor'){  onMmJobStatus(s);  break; }

      if(scope==='single') {
        onSingleJobStatus(s);
        if(s.status !== 'queued' && s.status !== 'processing') {
          stopPolling('single');
        }
        break;
      }

      // ZIP polling
      if(s.status==='queued'||s.status==='processing'){
        const pct=s.progress||0;
        const phaseLabel=s.phase_label||(s.phase==='pynguin'?'Running Pynguin algorithms…':s.phase==='refining'?'Refining with DeepSeek…':'Running pipeline…');
        const file=s.current_file?' — '+s.current_file:'';
        setLoader(scope,true,phaseLabel);
        showProgress(scope,pct,pct+'%'+file);
      } else {
        handleZipJobComplete(scope,s);
      }
      break;
    }

    case 'generationError': {
      const sc=m.scope||'single';
      if(sc==='single'){
        sgRunning=false; stopPolling('single');
        setLoader('single',false); hideProgress('single');
        updateRunBtn();
        showPill('single','err',m.error||'Error');
      } else {
        stopPolling(sc); setLoader(sc,false); hideProgress(sc); setRunning(sc,false);
        document.getElementById('btn-zip').disabled=false;
        showPill(sc,'err',m.error||'Error');
      }
      break;
    }

    case 'refactorJobStarted':
      startPpoPoll(m.jobId);
      break;

    case 'refactorJobError':
      stopPpoPoll();
      ppoRunning = false;
      setLoader('ppo', false);
      hideProgress('ppo');
      document.getElementById('btn-ppo-run').disabled = false;
      showPill('ppo','err', m.error||'PPO failed');
      break;

    case 'multiModelJobStarted':
      startMmPoll(m.jobId);
      break;

    case 'multiModelJobError':
      stopMmPoll();
      mmRunning = false;
      setLoader('mm', false);
      hideProgress('mm');
      document.getElementById('btn-mm-run').disabled = false;
      showPill('mm','err', m.error||'Multi-model refactor failed');
      break;

    case 'backendStatus':
      connApiOk=m.apiOk; connOllamaOk=m.ollamaOk;
      updateConnBar(
        m.apiOk?'ok':'err', m.apiDetail||(m.apiOk?'connected':'offline'),
        m.ollamaOk?'ok':'err', m.ollamaDetail||(m.ollamaOk?'ready':'offline')
      );
      if(refactorPath){
        document.getElementById('btn-mm-run').disabled = !m.apiOk;
        updatePpoBtn();
      }
      break;
  }
});

vscode.postMessage({type:'requestActiveFile'});
triggerCheck();
</script>
</body>
</html>`;
  }
}

export function deactivate() {}