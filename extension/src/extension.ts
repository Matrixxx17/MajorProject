import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import axios from "axios";

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
          await this.handleSingleGeneration(
            msg.filePath,
            msg.dirPath,
            msg.backendUrl,
          );
          break;
        case "generateZip":
          await this.handleZipGeneration(
            msg.zipPath,
            msg.backendUrl,
            msg.analysisMode ?? "single",
          );
          break;
        case "pollJob":
          await this.pollJob(msg.jobId, msg.backendUrl, msg.scope);
          break;
        case "checkBackend":
          await this.checkBackend(msg.backendUrl);
          break;
        case "refactorCode":
          await this.handleRefactoring(msg.filePath, msg.backendUrl);
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

  // ── Generation handlers ─────────────────────────────────────────────────────

  private async handleSingleGeneration(
    filePath: string,
    dirPath: string,
    backendUrl: string,
  ) {
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
        `${backendUrl}/generate-tests`,
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
        backendUrl,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "generationError",
        scope: "single",
        error: this.extractError(err, backendUrl),
      });
    }
  }

  private async handleZipGeneration(
    zipPath: string,
    backendUrl: string,
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

      const { data } = await axios.post(`${backendUrl}/analyze_zip`, body, {
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
        backendUrl,
        analysisMode,
      });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "generationError",
        scope: "zip",
        error: this.extractError(err, backendUrl),
      });
    }
  }

  private async pollJob(jobId: string, backendUrl: string, scope: string) {
    try {
      const { data } = await axios.get(`${backendUrl}/status/${jobId}`, {
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

  private async checkBackend(backendUrl: string) {
    let apiOk = false;
    let apiDetail = "";
    try {
      const { data } = await axios.get(`${backendUrl}/health`, {
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
        const { data } = await axios.get(`${backendUrl}/ollama-status`, {
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

  private async handleRefactoring(filePath: string, backendUrl: string) {
    this._view?.webview.postMessage({ type: "refactorStarted" });
    try {
      const moduleName = path.basename(filePath, ".py");
      const code = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.file(filePath)),
      ).toString("utf8");

      const { data } = await axios.post(
        `${backendUrl}/refactor`,
        { code, module_name: moduleName, file_path: filePath },
        { timeout: 300000 },
      );

      this._view?.webview.postMessage({
        type: "refactorComplete",
        result: data,
      });

      if (data.refactored_code) {
        const answer = await vscode.window.showInformationMessage(
          `Overwrite ${path.basename(filePath)} with refactored version?`,
          "Yes",
          "Save as new file",
          "No",
        );
        if (answer === "Yes") {
          await vscode.workspace.fs.writeFile(
            vscode.Uri.file(filePath),
            Buffer.from(data.refactored_code, "utf8"),
          );
          vscode.window.showInformationMessage("File refactored successfully.");
        } else if (answer === "Save as new file") {
          const dir = path.dirname(filePath);
          const base = path.basename(filePath, ".py");
          const newPath = path.join(dir, `${base}_refactored.py`);
          await vscode.workspace.fs.writeFile(
            vscode.Uri.file(newPath),
            Buffer.from(data.refactored_code, "utf8"),
          );
          const doc = await vscode.workspace.openTextDocument(
            vscode.Uri.file(newPath),
          );
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

  // ── Helpers ─────────────────────────────────────────────────────────────────

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
  --text:#ddddf0;--muted:#5a5a7a;--muted2:#3a3a58;
  --mono:'Cascadia Code','Fira Code','Consolas','Courier New',monospace;
  --sans:var(--vscode-font-family,'Segoe UI',system-ui,sans-serif);
  --r:7px;--ease:cubic-bezier(.4,0,.2,1);
}

html,body{background:var(--bg);color:var(--text);font-family:var(--mono);
  font-size:11.5px;line-height:1.5;overflow-x:hidden;overflow-y:auto;min-height:100vh;}

/* Header */
.hdr{padding:15px 15px 0;opacity:0;animation:fdown .38s var(--ease) .04s forwards}
.wordmark{font-family:var(--sans);font-size:14px;font-weight:700;letter-spacing:.03em;
  display:flex;align-items:center;gap:8px;}
.pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 9px var(--accent);animation:pulse 2.6s ease-in-out infinite;flex-shrink:0;}
.tagline{font-size:9.5px;color:var(--muted);margin-top:3px;letter-spacing:.09em;text-transform:uppercase;}

/* Connection bar */
.conn-bar{display:flex;align-items:center;gap:6px;margin:10px 15px 0;padding:7px 10px;
  background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);
  opacity:0;animation:fdown .38s var(--ease) .16s forwards;}
.conn-item{display:flex;align-items:center;gap:5px;font-size:9.5px;color:var(--muted);flex:1;min-width:0;}
.conn-sep{width:1px;height:12px;background:var(--bd2);flex-shrink:0}
.conn-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;background:var(--muted2);
  transition:background .25s,box-shadow .25s;}
.conn-dot.ok {background:var(--green);box-shadow:0 0 6px rgba(62,207,110,.5)}
.conn-dot.err{background:var(--red);box-shadow:0 0 6px rgba(240,112,112,.4)}
.conn-dot.chk{background:var(--amber);animation:pulse .9s ease-in-out infinite}
.conn-lbl{letter-spacing:.06em;text-transform:uppercase;font-size:8.5px}
.conn-detail{font-size:8.5px;color:var(--muted2);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;flex:1}
.conn-recheck{margin-left:auto;padding:2px 6px;border:1px solid var(--bd2);border-radius:4px;
  background:transparent;color:var(--muted);font-family:var(--mono);font-size:8.5px;
  cursor:pointer;transition:color .14s,border-color .14s;flex-shrink:0;}
.conn-recheck:hover{color:var(--text);border-color:var(--accent)}

/* Outer tabs */
.outer-tabs{display:flex;gap:2px;margin:14px 15px 0;background:var(--surf);
  border:1px solid var(--bd);border-radius:var(--r);padding:3px;
  opacity:0;animation:fdown .38s var(--ease) .1s forwards;}
.otab{flex:1;padding:7px 4px;border:none;background:transparent;color:var(--muted);
  font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.04em;cursor:pointer;
  border-radius:5px;transition:all .18s var(--ease);}
.otab:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.otab.on{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}

/* Main panels */
.mpanel{display:none;padding:14px 15px 0}
.mpanel.on{display:block;animation:fup .22s var(--ease) forwards}

/* Inner sub-tabs */
.inner-tabs-wrap{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);
  padding:3px;display:flex;gap:2px;margin-bottom:14px;}
.itab{flex:1;padding:5px 2px;border:none;background:transparent;color:var(--muted);
  font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.05em;cursor:pointer;
  border-radius:4px;transition:all .17s var(--ease);white-space:nowrap;}
.itab:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.itab.on{background:rgba(255,255,255,.06);color:var(--text);border:1px solid var(--bd2);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.04);}

/* Sub-panels */
.spanel{display:none}
.spanel.on{display:block;animation:fup .2s var(--ease) forwards;padding-bottom:24px}

/* Labels */
.lbl{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  margin-bottom:5px;display:flex;align-items:center;gap:5px;}
.lbl-badge{font-size:8.5px;padding:1px 5px;border-radius:20px;background:var(--aclo);
  color:var(--accent2);border:1px solid var(--acbd);letter-spacing:.04em;}

/* Input */
input[type=text]{width:100%;padding:7px 9px;background:var(--surf);color:var(--text);
  border:1px solid var(--bd);border-radius:var(--r);font-family:var(--mono);font-size:11px;
  outline:none;transition:border-color .17s,box-shadow .17s;}
input[type=text]:focus{border-color:rgba(124,110,245,.45);box-shadow:0 0 0 3px rgba(124,110,245,.08);}
input[type=text]::placeholder{color:var(--muted2)}

/* File card */
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

/* Buttons */
.btn{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;
  padding:9px;border:none;border-radius:var(--r);font-family:var(--mono);font-size:11px;
  font-weight:600;letter-spacing:.04em;cursor:pointer;transition:all .18s var(--ease);
  position:relative;overflow:hidden;}
.btn::after{content:'';position:absolute;inset:0;background:#fff;opacity:0;transition:opacity .13s;}
.btn:active:not(:disabled)::after{opacity:.05}
.btn:disabled{opacity:.32;cursor:not-allowed;transform:none !important;box-shadow:none !important}
.btn-violet{background:linear-gradient(135deg,var(--accent),#9b8af8);color:#fff;
  box-shadow:0 3px 14px rgba(124,110,245,.3);}
.btn-violet:hover:not(:disabled){box-shadow:0 5px 20px rgba(124,110,245,.44);transform:translateY(-1px);}
.btn-green{background:linear-gradient(135deg,#16a34a,var(--green));color:#051a0e;
  box-shadow:0 3px 14px rgba(62,207,110,.22);}
.btn-green:hover:not(:disabled){box-shadow:0 5px 20px rgba(62,207,110,.36);transform:translateY(-1px);}
.btn-ghost{background:var(--surf);color:var(--muted);border:1px solid var(--bd);
  width:auto;padding:7px 11px;font-size:11px;}
.btn-ghost:hover{color:var(--text);border-color:var(--bd2)}

/* Helpers */
.row{display:flex;gap:8px;align-items:flex-end;margin-bottom:12px}
.mb{margin-bottom:12px}.fld{margin-bottom:12px}.divider{height:1px;background:var(--bd);margin:12px 0}
.backend-row{margin-bottom:12px}

/* Loader */
.loader{display:none;flex-direction:column;align-items:center;gap:10px;padding:18px 0 8px;}
.loader.on{display:flex}
.ring{width:22px;height:22px;border-radius:50%;border:2px solid var(--bd2);
  border-top-color:var(--accent);animation:spin .7s linear infinite;}
.ring.green{border-top-color:var(--green)}.ring.amber{border-top-color:var(--amber)}
.loader-txt{font-size:10px;color:var(--muted);letter-spacing:.06em}

/* Status pill */
.pill{display:none;align-items:center;gap:7px;padding:8px 11px;border-radius:var(--r);font-size:11px;}
.pill.on{display:flex;animation:fup .2s var(--ease) forwards}
.pdot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.pill.info{background:var(--aclo);border:1px solid var(--acbd);color:var(--accent2)}
.pill.info .pdot{background:var(--accent);box-shadow:0 0 6px var(--accent);animation:pulse 1.4s ease-in-out infinite}
.pill.ok{background:var(--greenlo);border:1px solid var(--greenbd);color:var(--green)}
.pill.ok .pdot{background:var(--green)}
.pill.err{background:var(--redlo);border:1px solid var(--redbd);color:var(--red)}
.pill.err .pdot{background:var(--red)}

/* Progress bar */
.progress-wrap{background:var(--surf2);border:1px solid var(--bd);border-radius:20px;height:5px;
  overflow:hidden;margin-bottom:6px;}
.progress-bar{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));
  border-radius:20px;transition:width .4s var(--ease);width:0%;}
.progress-label{font-size:9.5px;color:var(--muted);text-align:center;margin-bottom:8px}

/* ── Pynguin algo results table ───────────────────────────────── */
.algo-section{display:none;margin-top:16px;}
.algo-section.on{display:block;animation:fup .26s var(--ease) forwards}
.section-hdr{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.section-hdr::after{content:'';flex:1;height:1px;background:var(--bd);}

.algo-table{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.at-row{display:grid;grid-template-columns:90px 1fr 70px 70px 70px;gap:0;
  align-items:center;border-bottom:1px solid var(--bd);font-size:10.5px;}
.at-row:last-child{border-bottom:none}
.at-row.hd{background:var(--surf2);font-size:8.5px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;}
.at-cell{padding:7px 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.at-cell.right{text-align:right;}
.algo-badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;
  font-size:8.5px;letter-spacing:.05em;font-weight:600;}
.algo-badge.random{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.algo-badge.whole_suite{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd);}
.algo-badge.dynamosa{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd);}
.score-g{color:var(--green)}.score-a{color:var(--amber)}.score-r{color:var(--red)}.score-d{color:var(--muted)}
.tag{display:inline-flex;align-items:center;justify-content:center;font-size:8.5px;
  padding:2px 6px;border-radius:4px;letter-spacing:.04em;}
.tag.ok{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd)}
.tag.err{background:var(--redlo);color:var(--red);border:1px solid var(--redbd)}

/* ── Side-by-side code panels ─────────────────────────────────── */
.code-section{display:none;margin-top:16px;}
.code-section.on{display:block;animation:fup .26s var(--ease) forwards}
.code-panels{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.code-panel{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.cp-hdr{padding:7px 10px;border-bottom:1px solid var(--bd);display:flex;
  align-items:center;justify-content:space-between;background:var(--surf2);}
.cp-title{font-size:8.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.cp-badge{font-size:8px;padding:1px 5px;border-radius:3px;}
.cp-badge.raw{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.cp-badge.refined{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd);}
.cp-body{padding:10px;max-height:260px;overflow-y:auto;}
.cp-body pre{font-size:9.5px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#bbbbd8}
.cp-empty{color:var(--muted);font-style:italic;font-size:10px;padding:14px 10px;text-align:center;}

/* ── DL link ──────────────────────────────────────────────────── */
.dl-link{color:var(--accent2);text-decoration:none;font-size:9.5px;}
.dl-link:hover{color:var(--accent)}

/* ZIP result */
.zip-result{display:none;margin-top:16px;background:var(--surf);border:1px solid var(--bd);
  border-radius:var(--r);overflow:hidden;}
.zip-result.on{display:block;animation:fup .26s var(--ease) forwards}
.zr-hdr{padding:8px 12px;border-bottom:1px solid var(--bd);display:flex;
  align-items:center;justify-content:space-between}
.zr-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.zr-body{padding:10px 12px;max-height:220px;overflow-y:auto}
.zr-row{display:grid;grid-template-columns:1fr 46px 46px 52px 52px;gap:5px;
  align-items:center;padding:5px 0;border-bottom:1px solid var(--bd);font-size:10.5px;}
.zr-row:last-child{border-bottom:none}
.zr-row.hd{font-size:9px;color:var(--muted);letter-spacing:.07em;text-transform:uppercase}
.mt-val{text-align:right}.mt-file{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag.ens{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd)}

/* Mode toggle */
.mode-toggle{display:flex;gap:2px;margin-bottom:12px;background:var(--surf2);
  border:1px solid var(--bd);border-radius:var(--r);padding:3px;}
.mtog{flex:1;padding:6px 4px;border:none;background:transparent;color:var(--muted);
  font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.04em;cursor:pointer;
  border-radius:5px;transition:all .17s var(--ease);display:flex;align-items:center;
  justify-content:center;gap:5px;}
.mtog:hover:not(.on){background:rgba(255,255,255,.04);color:var(--text)}
.mtog.on.single{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.mtog.on.ensemble{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd);}
.mode-desc{font-size:9px;color:var(--muted);margin-bottom:10px;padding:6px 9px;
  background:var(--surf2);border:1px solid var(--bd);border-radius:5px;line-height:1.6;}
.mode-desc .hi{color:var(--text)}

/* Refactor panel */
.ref-file-card{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);
  padding:11px 13px;margin-bottom:13px;display:flex;align-items:flex-start;gap:9px;}
.ref-icon{font-size:16px;flex-shrink:0;line-height:1;padding-top:1px}
.ref-body{flex:1;min-width:0}
.ref-name{font-size:11px;color:var(--text);word-break:break-all;line-height:1.4}
.ref-name.empty{color:var(--muted);font-style:italic}
.ref-sub{font-size:9.5px;color:var(--muted);margin-top:3px}
.ref-result{display:none;margin-top:16px;background:var(--surf);border:1px solid var(--bd);
  border-radius:var(--r);overflow:hidden;}
.ref-result.on{display:block;animation:fup .26s var(--ease) forwards}
.rc-hdr{padding:8px 12px;border-bottom:1px solid var(--bd);display:flex;
  align-items:center;justify-content:space-between;}
.rc-title{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.ref-summary{padding:11px 12px;font-size:10.5px;line-height:1.7;color:#c4c4e0;
  border-bottom:1px solid var(--bd);white-space:pre-wrap}

/* Scrollbar / Animations */
::-webkit-scrollbar{width:3px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:3px}
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

<!-- Connection status bar -->
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

<!-- ══ Test Generation panel ══════════════════════════════════════ -->
<div class="mpanel on" id="mp-testgen">

  <div class="fld backend-row">
    <div class="lbl">Backend URL</div>
    <input type="text" id="backendUrl" value="http://localhost:8000"/>
  </div>

  <div class="inner-tabs-wrap">
    <button class="itab on" onclick="iSwitch('single',this)">Single File</button>
    <button class="itab"    onclick="iSwitch('zip',this)">Codebase</button>
  </div>

  <!-- ── Single File ─────────────────────────────────────────────── -->
  <div class="spanel on" id="sp-single">
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
    <button class="btn btn-violet" id="btn-single" onclick="genSingle()" disabled>⬡ Generate Tests</button>

    <!-- Phase loader -->
    <div class="loader" id="ld-single">
      <div class="ring"></div>
      <span class="loader-txt" id="ld-single-txt">Submitting…</span>
    </div>

    <!-- Progress -->
    <div class="progress-wrap" id="single-prog-wrap" style="display:none">
      <div class="progress-bar" id="single-prog-bar"></div>
    </div>
    <div class="progress-label" id="single-prog-lbl" style="display:none"></div>

    <!-- Status pill -->
    <div class="pill" id="pill-single"><span class="pdot"></span><span id="pill-single-txt"></span></div>

    <!-- ── Algo results table ──────────────────────────────────── -->
    <div class="algo-section" id="algo-section">
      <div class="section-hdr">Pynguin Algorithm Results</div>
      <div class="algo-table">
        <div class="at-row hd">
          <div class="at-cell">Algorithm</div>
          <div class="at-cell">Tests</div>
          <div class="at-cell right">Coverage</div>
          <div class="at-cell right">Mutation</div>
          <div class="at-cell right">Status</div>
        </div>
        <div id="algo-rows"></div>
      </div>
      <!-- Download link shown after completion -->
      <div style="margin-top:6px;text-align:right">
        <a class="dl-link" id="single-dl" href="#" style="display:none">↓ Download All Tests</a>
      </div>
    </div>

    <!-- ── Side-by-side code panels ───────────────────────────── -->
    <div class="code-section" id="code-section">
      <div class="section-hdr">Test Code</div>
      <div class="code-panels">
        <!-- Raw best -->
        <div class="code-panel">
          <div class="cp-hdr">
            <span class="cp-title">Best Raw Output</span>
            <span class="cp-badge raw" id="raw-algo-label">—</span>
          </div>
          <div class="cp-body">
            <pre id="raw-code-pre"><span class="cp-empty">Run generation to see output</span></pre>
          </div>
        </div>
        <!-- Refined -->
        <div class="code-panel">
          <div class="cp-hdr">
            <span class="cp-title">DeepSeek Refined</span>
            <span class="cp-badge refined">✦ refined</span>
          </div>
          <div class="cp-body">
            <pre id="refined-code-pre"><span class="cp-empty">Refinement pending…</span></pre>
          </div>
        </div>
      </div>
    </div>
  </div><!-- /sp-single -->

  <!-- ── Codebase ZIP ────────────────────────────────────────────── -->
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
      <span class="hi">Single Model</span> — fast analysis using <span class="hi">deepseek-coder:1.3b</span>.
      Good for most codebases.
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

<!-- ══ Refactor panel ══════════════════════════════════════════════ -->
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
    <button class="fc-dismiss" id="ref-dismiss" title="Clear file" onclick="clearRef()">×</button>
  </div>
  <button class="btn btn-green" id="btn-refactor" onclick="doRefactor()" disabled>⟳ Refactor Code</button>
  <div class="loader" id="ld-ref"><div class="ring green"></div><span class="loader-txt">Analysing &amp; refactoring…</span></div>
  <div class="pill" id="pill-ref"><span class="pdot"></span><span id="pill-ref-txt"></span></div>
  <div class="ref-result" id="ref-result">
    <div class="rc-hdr"><span class="rc-title">Refactor Summary</span></div>
    <div class="ref-summary" id="ref-summary"></div>
  </div>
</div>

<script>
const vscode = acquireVsCodeApi();

/* ── State ───────────────────────────────────── */
let singleFilePath = '', singleDirPath = '';
let zipFilePath    = '', refactorPath  = '';
let zipAnalysisMode = 'single';
const pollTimers = {};
let connApiOk = false, connOllamaOk = false, checkDebounce = null;

/* ── Connection bar ──────────────────────────── */
function triggerCheck() {
  const url = document.getElementById('backendUrl')?.value.trim() || 'http://localhost:8000';
  updateConnBar('chk','checking…','chk','checking…');
  vscode.postMessage({ type:'checkBackend', backendUrl:url });
}
function updateConnBar(as,at,os,ot) {
  document.getElementById('dot-api').className    = 'conn-dot '+as;
  document.getElementById('det-api').textContent  = at;
  document.getElementById('dot-ollama').className = 'conn-dot '+os;
  document.getElementById('det-ollama').textContent = ot;
}

/* ── Tab switching ───────────────────────────── */
function oSwitch(id,btn){
  document.querySelectorAll('.otab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('.mpanel').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById('mp-'+id).classList.add('on');
}
function iSwitch(id,btn){
  document.querySelectorAll('.itab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('.spanel').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById('sp-'+id).classList.add('on');
}

/* ── Analysis mode toggle ────────────────────── */
function setMode(mode){
  zipAnalysisMode = mode;
  document.getElementById('mtog-single').classList.toggle('on', mode==='single');
  document.getElementById('mtog-ensemble').classList.toggle('on', mode==='ensemble');
  const desc = document.getElementById('mode-desc');
  const bar  = document.getElementById('zip-prog-bar');
  const ring = document.getElementById('zip-ring');
  if(mode==='single'){
    desc.innerHTML='<span class="hi">Single Model</span> — fast analysis using <span class="hi">deepseek-coder:1.3b</span>. Good for most codebases.';
    bar.classList.remove('amber'); ring.classList.remove('amber');
  } else {
    desc.innerHTML='<span class="hi">Ensemble</span> — runs <span class="hi">deepseek-coder, starcoder &amp; codellama</span> in parallel, then merges the best tests. Slower but higher quality.';
    bar.classList.add('amber'); ring.classList.add('amber');
  }
}

/* ── Polling ─────────────────────────────────── */
function startPolling(scope,jobId,backendUrl){
  stopPolling(scope);
  pollTimers[scope]=setInterval(()=>vscode.postMessage({type:'pollJob',jobId,backendUrl,scope}),2000);
}
function stopPolling(scope){
  if(pollTimers[scope]){clearInterval(pollTimers[scope]);delete pollTimers[scope];}
}

/* ── Single file ─────────────────────────────── */
function pickSingle(){ vscode.postMessage({type:'pickSingleFile',rootFolder:singleDirPath}); }

function setSingleFile(fp,dir,name){
  singleFilePath=fp; singleDirPath=dir||fp.replace(/[\\/][^\\/]+$/,'');
  const nameEl=document.getElementById('sf-name');
  nameEl.textContent=name||fp.split(/[\\/]/).pop(); nameEl.classList.remove('empty');
  document.getElementById('sf-dir').textContent=singleDirPath;
  document.getElementById('sf-card').classList.add('active');
  document.getElementById('btn-single').disabled=false;
  document.getElementById('sf-dismiss').classList.add('visible');
}

function clearSingle(){
  singleFilePath=''; singleDirPath='';
  const n=document.getElementById('sf-name');
  n.textContent='Open a .py file or browse below'; n.classList.add('empty');
  document.getElementById('sf-dir').textContent='';
  document.getElementById('sf-card').classList.remove('active');
  document.getElementById('sf-dismiss').classList.remove('visible');
  document.getElementById('sf-auto-badge').style.display='none';
  document.getElementById('btn-single').disabled=true;
  hidePill('single');
  document.getElementById('algo-section').classList.remove('on');
  document.getElementById('code-section').classList.remove('on');
}

function genSingle(){
  if(!singleFilePath){ showPill('single','err','No file selected'); return; }
  if(!checkReady('single')) return;
  const backendUrl=document.getElementById('backendUrl').value.trim();
  setLoader('single',true,'Submitting job…');
  setRunning('single',true); hidePill('single');
  document.getElementById('algo-section').classList.remove('on');
  document.getElementById('code-section').classList.remove('on');
  document.getElementById('btn-single').disabled=true;
  document.getElementById('single-prog-wrap').style.display='none';
  document.getElementById('single-prog-lbl').style.display='none';
  vscode.postMessage({type:'generateSingle',filePath:singleFilePath,dirPath:singleDirPath,backendUrl});
}

/* ── ZIP ─────────────────────────────────────── */
function pickZip(){ vscode.postMessage({type:'pickZipFile'}); }
function clearZip(){
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

/* ── Refactor ────────────────────────────────── */
function clearRef(){
  refactorPath='';
  const n=document.getElementById('ref-name');
  n.textContent='Open a Python file in the editor'; n.classList.add('empty');
  document.getElementById('ref-sub').textContent='';
  document.getElementById('ref-dismiss').classList.remove('visible');
  document.getElementById('btn-refactor').disabled=true;
  hidePill('ref');
  document.getElementById('ref-result').classList.remove('on');
}

/* ── Pre-flight guard ────────────────────────── */
function checkReady(scope){
  if(!connApiOk){ showPill(scope,'err','API offline — start the backend first'); return false; }
  if(!connOllamaOk){ showPill(scope,'info','Ollama offline — generation may fail'); }
  return true;
}

function setRunning(scope,running){
  if(scope==='single'){
    document.getElementById('btn-browse-single').disabled=running;
    document.getElementById('sf-dismiss').disabled=running;
  } else if(scope==='zip'){
    document.getElementById('btn-browse-zip').disabled=running;
    document.getElementById('zip-dismiss').disabled=running;
    document.getElementById('mtog-single').disabled=running;
    document.getElementById('mtog-ensemble').disabled=running;
  } else if(scope==='ref'){
    document.getElementById('ref-dismiss').disabled=running;
  }
}

function genZip(){
  if(!zipFilePath){ showPill('zip','err','No ZIP selected'); return; }
  if(!checkReady('zip')) return;
  const backendUrl=document.getElementById('backendUrl').value.trim();
  setLoader('zip',true,zipAnalysisMode==='ensemble'?'Uploading (ensemble)…':'Uploading ZIP…');
  setRunning('zip',true); hidePill('zip');
  document.getElementById('zr-main').classList.remove('on');
  document.getElementById('btn-zip').disabled=true;
  document.getElementById('zip-prog-wrap').style.display='none';
  document.getElementById('zip-prog-lbl').style.display='none';
  vscode.postMessage({type:'generateZip',zipPath:zipFilePath,backendUrl,analysisMode:zipAnalysisMode});
}

function doRefactor(){
  if(!refactorPath){ showPill('ref','err','No Python file open'); return; }
  if(!checkReady('ref')) return;
  const backendUrl=document.getElementById('refBackendUrl').value.trim();
  setLoader('ref',true); setRunning('ref',true); hidePill('ref');
  document.getElementById('ref-result').classList.remove('on');
  document.getElementById('btn-refactor').disabled=true;
  vscode.postMessage({type:'refactorCode',filePath:refactorPath,backendUrl});
}

/* ── Shared UI helpers ───────────────────────── */
function setLoader(scope,on,msg){
  const el=document.getElementById('ld-'+scope); el.classList.toggle('on',on);
  if(msg) el.querySelector('.loader-txt').textContent=msg;
}
function showPill(scope,type,msg){
  const el=document.getElementById('pill-'+scope);
  el.className='pill on '+type;
  document.getElementById('pill-'+scope+'-txt').textContent=msg;
}
function hidePill(scope){ document.getElementById('pill-'+scope).classList.remove('on'); }
function showProgress(scope,pct,label){
  document.getElementById(scope+'-prog-wrap').style.display='block';
  document.getElementById(scope+'-prog-lbl').style.display='block';
  document.getElementById(scope+'-prog-bar').style.width=pct+'%';
  document.getElementById(scope+'-prog-lbl').textContent=label;
}
function hideProgress(scope){
  document.getElementById(scope+'-prog-wrap').style.display='none';
  document.getElementById(scope+'-prog-lbl').style.display='none';
}
function scoreClass(pct){ return pct>=70?'score-g':pct>=40?'score-a':'score-r'; }
function esc(t){ const d=document.createElement('div');d.textContent=t;return d.innerHTML; }

/* ── Render algo table rows ─────────────────── */
function renderAlgoRows(results){
  const container=document.getElementById('algo-rows');
  container.innerHTML='';
  results.forEach(r=>{
    const cov = r.metrics?.coverage_percent ?? Math.round((r.coverage||0)*100);
    const mut = r.metrics?.mutation_score   != null
               ? Math.round(r.metrics.mutation_score*100)
               : Math.round((r.mutation_score||0)*100);
    const algo = (r.algorithm||'').toLowerCase();
    const row=document.createElement('div');
    row.className='at-row';
    row.innerHTML=\`
      <div class="at-cell">
        <span class="algo-badge \${algo}">\${esc(r.algorithm||'—')}</span>
      </div>
      <div class="at-cell">\${r.num_tests!=null?r.num_tests+'  tests':'—'}</div>
      <div class="at-cell right \${r.status==='success'?scoreClass(cov):'score-d'}">
        \${r.status==='success'?cov+'%':'—'}
      </div>
      <div class="at-cell right \${r.status==='success'?scoreClass(mut):'score-d'}">
        \${r.status==='success'?mut+'%':'—'}
      </div>
      <div class="at-cell right">
        \${r.status==='success'
          ? '<span class="tag ok">ok</span>'
          : '<span class="tag err" title="'+esc(r.error||'')+'">error</span>'}
      </div>\`;
    container.appendChild(row);
  });
}

/* ── Render code panels ─────────────────────── */
function renderCodePanels(algoResults, refinement){
  // Pick best raw algo by coverage
  const successful = algoResults.filter(r=>r.status==='success' && r.content);
  let best = successful.length
    ? successful.reduce((a,b)=>(b.coverage||0)>(a.coverage||0)?b:a)
    : null;

  const rawPre = document.getElementById('raw-code-pre');
  const rawLabel = document.getElementById('raw-algo-label');
  if(best){
    rawPre.textContent = best.content;
    rawLabel.textContent = best.algorithm;
  } else {
    rawPre.innerHTML = '<span class="cp-empty">No successful output</span>';
    rawLabel.textContent = '—';
  }

  const refinedPre = document.getElementById('refined-code-pre');
  if(refinement && refinement.status==='success' && refinement.refined_code){
    refinedPre.textContent = refinement.refined_code;
  } else if(refinement && refinement.error){
    refinedPre.innerHTML = '<span class="cp-empty">Refinement failed: '+esc(refinement.error)+'</span>';
  } else {
    refinedPre.innerHTML = '<span class="cp-empty">No refined output</span>';
  }
}

/* ── Job completion ─────────────────────────── */
function handleJobComplete(scope, jobData){
  stopPolling(scope); setLoader(scope,false); hideProgress(scope); setRunning(scope,false);

  const btnMap={single:'btn-single',zip:'btn-zip'};
  if(btnMap[scope]) document.getElementById(btnMap[scope]).disabled=false;

  if(jobData.status==='error'){
    showPill(scope,'err',jobData.error||'Job failed'); return;
  }

  if(scope==='single'){
    const results  = jobData.results  || [];
    const refinement = jobData.refinement || null;
    const ok = results.filter(r=>r.status==='success').length;

    showPill('single','ok',
      \`\${ok}/\${results.length} algorithms succeeded\${refinement?.status==='success'?' · Refined ✓':''}\`);

    // Table
    renderAlgoRows(results);
    document.getElementById('algo-section').classList.add('on');

    // Download link
    if(jobData.download_url){
      const dl=document.getElementById('single-dl');
      dl.href=document.getElementById('backendUrl').value.trim()+jobData.download_url;
      dl.style.display='';
    }

    // Code panels
    renderCodePanels(results, refinement);
    document.getElementById('code-section').classList.add('on');

  } else if(scope==='zip'){
    const results = jobData.results || [];
    const ok = results.filter(r=>r.status==='success').length;
    const mode = jobData.analysis_mode || zipAnalysisMode;
    showPill('zip','ok',\`\${ok}/\${results.length} files analysed (\${mode})\`);
    renderZipRows(results, document.getElementById('zr-rows'));
    if(jobData.download_url){
      const dl=document.getElementById('zr-dl');
      dl.href=document.getElementById('backendUrl').value.trim()+jobData.download_url;
      dl.style.display='';
    }
    document.getElementById('zr-main').classList.add('on');
  }
}

/* ── ZIP rows ───────────────────────────────── */
function renderZipRows(results, container){
  container.innerHTML='';
  results.forEach(r=>{
    const cov = r.metrics?.coverage_percent ?? (r.coverage!=null?Math.round(r.coverage*100):null);
    const mut = r.metrics?.mutation_score   != null ? Math.round(r.metrics.mutation_score*100)
              : r.mutation_score            != null ? Math.round(r.mutation_score*100) : null;
    const method = r.generation_method||'—'; const isEns = method==='ensemble';
    const row=document.createElement('div'); row.className='zr-row';
    row.innerHTML=\`
      <div class="mt-file" title="\${esc(r.file)}">\${esc(r.file)}</div>
      <div class="mt-val \${cov!=null?scoreClass(cov):''}">\${cov!=null?cov+'%':'—'}</div>
      <div class="mt-val \${mut!=null?scoreClass(mut):''}">\${mut!=null?mut+'%':'—'}</div>
      <div class="mt-val"><span class="tag \${isEns?'ens':'ok'}">\${isEns?'ensemble':'single'}</span></div>
      <div class="mt-val"><span class="tag \${r.status==='success'?'ok':'err'}">\${r.status}</span></div>\`;
    container.appendChild(row);
  });
}

/* ── Message handler ────────────────────────── */
window.addEventListener('message', ev=>{
  const m=ev.data;
  switch(m.type){

    case 'activeFileChanged':{
      const fp=m.filePath||'', name=fp.split(/[\\/]/).pop(), dir=fp.replace(/[\\/][^\\/]+$/,'');
      document.getElementById('sf-auto-badge').style.display='';
      setSingleFile(fp,dir,name);
      refactorPath=fp;
      const rn=document.getElementById('ref-name');
      rn.textContent=fp||'No Python file open'; rn.classList.toggle('empty',!fp);
      document.getElementById('ref-sub').textContent=fp?dir:'';
      document.getElementById('btn-refactor').disabled=!fp;
      const rd=document.getElementById('ref-dismiss');
      if(fp) rd.classList.add('visible'); else rd.classList.remove('visible');
      break;
    }

    case 'singleFilePicked':
      document.getElementById('sf-auto-badge').style.display='none';
      setSingleFile(m.filePath,m.dirPath,m.fileName);
      break;

    case 'zipFilePicked':{
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

    case 'jobStarted':{
      const scope=m.scope;
      setLoader(scope,true,'Running pipeline…');
      showProgress(scope,0,'Starting…');
      startPolling(scope,m.jobId,m.backendUrl);
      break;
    }

    case 'jobStatus':{
      const scope=m.scope, s=m.status;
      if(s.status==='queued'||s.status==='processing'){
        const pct=s.progress||0;
        const phaseLabel = s.phase_label || (s.phase==='pynguin'?'Running Pynguin algorithms…'
                                           : s.phase==='refining'?'Refining with DeepSeek…'
                                           : 'Running pipeline…');
        const file=s.current_file?' — '+s.current_file:'';
        setLoader(scope,true,phaseLabel);
        showProgress(scope,pct,pct+'%'+file);

        // Show partial algo table while pynguin is running
        if(scope==='single' && s.algo_results && s.algo_results.length){
          renderAlgoRows(s.algo_results);
          document.getElementById('algo-section').classList.add('on');
        }
      } else {
        handleJobComplete(scope,s);
      }
      break;
    }

    case 'generationError':{
      const sc=m.scope||'single';
      stopPolling(sc); setLoader(sc,false); hideProgress(sc); setRunning(sc,false);
      const btnId=sc==='single'?'btn-single':sc==='zip'?'btn-zip':null;
      if(btnId) document.getElementById(btnId).disabled=false;
      showPill(sc,'err',m.error||'Error');
      break;
    }

    case 'refactorStarted': break;
    case 'refactorComplete':
      setLoader('ref',false); setRunning('ref',false);
      document.getElementById('btn-refactor').disabled=false;
      showPill('ref','ok','Refactoring complete');
      if(m.result?.summary){
        document.getElementById('ref-summary').textContent=m.result.summary;
        document.getElementById('ref-result').classList.add('on');
      }
      break;
    case 'refactorError':
      setLoader('ref',false); setRunning('ref',false);
      document.getElementById('btn-refactor').disabled=false;
      showPill('ref','err',m.error||'Error'); break;

    case 'backendStatus':
      connApiOk=m.apiOk; connOllamaOk=m.ollamaOk;
      updateConnBar(m.apiOk?'ok':'err', m.apiDetail||(m.apiOk?'connected':'offline'),
                   m.ollamaOk?'ok':'err', m.ollamaDetail||(m.ollamaOk?'ready':'offline'));
      break;
  }
});

/* ── Debounced re-check on URL change ────────── */
function scheduleCheck(){ clearTimeout(checkDebounce); checkDebounce=setTimeout(triggerCheck,800); }
document.getElementById('backendUrl').addEventListener('input',scheduleCheck);
document.getElementById('refBackendUrl').addEventListener('input',scheduleCheck);

vscode.postMessage({type:'requestActiveFile'});
triggerCheck();
</script>
</body>
</html>`;
  }
}

export function deactivate() {}
