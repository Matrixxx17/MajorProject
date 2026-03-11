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
        // Unified refactor: one message per model, webview sequences ensemble
        case "refactorSingleModel":
          await this.handleRefactorSingleModel(msg.filePath, msg.model);
          break;
        case "saveRefactored":
          await this.saveRefactoredFile(msg.filePath, msg.code, msg.model);
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

  // ── Unified single-model refactor job ──────────────────────────────────────
  // The webview drives ensemble sequencing: it fires one model at a time,
  // waits for the job to complete, then fires the next.
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
.btn-ghost{background:var(--surf);color:var(--muted);border:1px solid var(--bd);width:auto;padding:7px 11px;font-size:11px;}
.btn-ghost:hover{color:var(--text);border-color:var(--bd2)}

.row{display:flex;gap:8px;align-items:flex-end;margin-bottom:12px}
.mb{margin-bottom:12px}.fld{margin-bottom:12px}
.divider{height:1px;background:var(--bd);margin:12px 0}

.loader{display:none;flex-direction:column;align-items:center;gap:10px;padding:18px 0 8px;}
.loader.on{display:flex}
.ring{width:22px;height:22px;border-radius:50%;border:2px solid var(--bd2);border-top-color:var(--accent);animation:spin .7s linear infinite;}
.ring.green{border-top-color:var(--green)}.ring.amber{border-top-color:var(--amber)}
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
.progress-label{font-size:9.5px;color:var(--muted);text-align:center;margin-bottom:8px}

/* Test gen: algo table */
.algo-section{display:none;margin-top:16px;}
.algo-section.on{display:block;animation:fup .26s var(--ease) forwards}
.section-hdr{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.section-hdr::after{content:'';flex:1;height:1px;background:var(--bd);}
.algo-table{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.at-row{display:grid;grid-template-columns:90px 1fr 70px 70px 70px;gap:0;align-items:center;border-bottom:1px solid var(--bd);font-size:10.5px;}
.at-row:last-child{border-bottom:none}
.at-row.hd{background:var(--surf2);font-size:8.5px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;}
.at-cell{padding:7px 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.at-cell.right{text-align:right;}
.algo-badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;font-size:8.5px;letter-spacing:.05em;font-weight:600;}
.algo-badge.random{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.algo-badge.whole_suite{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd);}
.algo-badge.dynamosa{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd);}
.score-g{color:var(--green)}.score-a{color:var(--amber)}.score-r{color:var(--red)}.score-d{color:var(--muted)}
.tag{display:inline-flex;align-items:center;justify-content:center;font-size:8.5px;padding:2px 6px;border-radius:4px;letter-spacing:.04em;}
.tag.ok{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd)}
.tag.err{background:var(--redlo);color:var(--red);border:1px solid var(--redbd)}
.tag.ens{background:var(--amberlo);color:var(--amber);border:1px solid var(--amberbd)}
.tag.run{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd)}

.code-section{display:none;margin-top:16px;}
.code-section.on{display:block;animation:fup .26s var(--ease) forwards}
.code-panels{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.code-panel{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.cp-hdr{padding:7px 10px;border-bottom:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between;background:var(--surf2);}
.cp-title{font-size:8.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.cp-badge{font-size:8px;padding:1px 5px;border-radius:3px;}
.cp-badge.raw{background:var(--aclo);color:var(--accent2);border:1px solid var(--acbd);}
.cp-badge.refined{background:var(--greenlo);color:var(--green);border:1px solid var(--greenbd);}
.cp-body{padding:10px;max-height:260px;overflow-y:auto;}
.cp-body pre{font-size:9.5px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#bbbbd8}
.cp-empty{color:var(--muted);font-style:italic;font-size:10px;padding:14px 10px;text-align:center;}

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

/* ── Refactor panel ── */
.ref-file-card{background:var(--surf2);border:1px solid var(--bd);border-radius:var(--r);
  padding:11px 13px;margin-bottom:13px;display:flex;align-items:flex-start;gap:9px;}
.ref-body{flex:1;min-width:0}
.ref-name{font-size:11px;color:var(--text);word-break:break-all;line-height:1.4}
.ref-name.empty{color:var(--muted);font-style:italic}
.ref-sub{font-size:9.5px;color:var(--muted);margin-top:3px}

/* Model checkboxes */
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

/* Metrics comparison table */
.ref-metrics-section{display:none;margin-top:14px;}
.ref-metrics-section.on{display:block;animation:fup .24s var(--ease) forwards}
.ref-mtable{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.ref-mhdr{display:grid;grid-template-columns:1fr 46px 46px 46px 46px 56px;gap:4px;
  padding:6px 10px;font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;
  border-bottom:1px solid var(--bd);background:var(--surf2);}
.ref-mrow{display:grid;grid-template-columns:1fr 46px 46px 46px 46px 56px;gap:4px;
  padding:7px 10px;font-size:10px;border-bottom:1px solid var(--bd2);align-items:center;transition:background .15s;}
.ref-mrow:last-child{border-bottom:none}
.ref-mrow.best-row{background:#0d1f10;}
.ref-mrow.loading-row{opacity:.6;}
.delta-pos{color:#4ade80;}.delta-neg{color:#f87171;}.delta-neu{color:#fbbf24;}.delta-dim{color:var(--muted)}
.reward-cell{display:flex;align-items:center;gap:4px;}
.tag.sm{font-size:8px;padding:1px 5px;}

/* Diff viewer */
.ref-diff-section{display:none;margin-top:12px;padding-bottom:24px;}
.ref-diff-section.on{display:block;animation:fup .22s var(--ease) forwards}
.ref-diff-wrap{background:var(--surf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}
.ref-diff-hdr{padding:7px 10px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;background:var(--surf2);flex-wrap:wrap;row-gap:5px;}
.diff-title{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;flex:1;min-width:80px;}
.diff-model-btns{display:flex;gap:4px;flex-wrap:wrap;}
.diff-mbtn{font-size:9px;padding:2px 7px;border-radius:4px;border:1px solid;cursor:pointer;opacity:.55;background:transparent;font-family:var(--mono);transition:opacity .14s;}
.diff-mbtn.on{opacity:1;font-weight:700;}
.diff-mbtn.ds{border-color:#7c3aed;color:#c4b5fd;}
.diff-mbtn.sc{border-color:#059669;color:#6ee7b7;}
.diff-mbtn.cl{border-color:#b45309;color:#fcd34d;}
.diff-pre{margin:0;padding:10px;font-size:9.5px;line-height:1.6;overflow-x:auto;max-height:220px;white-space:pre;font-family:var(--mono);color:#c4c4e0;}
.btn-save-ref{font-size:9.5px;padding:3px 9px;background:var(--surf);border:1px solid var(--bd);border-radius:4px;color:var(--text);cursor:pointer;white-space:nowrap;font-family:var(--mono);}
.btn-save-ref:hover{background:var(--surf2);}

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

  <!-- Single File -->
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
    <div class="loader" id="ld-single"><div class="ring"></div><span class="loader-txt" id="ld-single-txt">Submitting…</span></div>
    <div class="progress-wrap" id="single-prog-wrap" style="display:none"><div class="progress-bar" id="single-prog-bar"></div></div>
    <div class="progress-label" id="single-prog-lbl" style="display:none"></div>
    <div class="pill" id="pill-single"><span class="pdot"></span><span id="pill-single-txt"></span></div>
    <div class="algo-section" id="algo-section">
      <div class="section-hdr">Pynguin Algorithm Results</div>
      <div class="algo-table">
        <div class="at-row hd">
          <div class="at-cell">Algorithm</div><div class="at-cell">Tests</div>
          <div class="at-cell right">Coverage</div><div class="at-cell right">Mutation</div><div class="at-cell right">Status</div>
        </div>
        <div id="algo-rows"></div>
      </div>
      <div style="margin-top:6px;text-align:right">
        <a class="dl-link" id="single-dl" href="#" style="display:none">↓ Download All Tests</a>
      </div>
    </div>
    <div class="code-section" id="code-section">
      <div class="section-hdr">Test Code</div>
      <div class="code-panels">
        <div class="code-panel">
          <div class="cp-hdr"><span class="cp-title">Best Raw Output</span><span class="cp-badge raw" id="raw-algo-label">—</span></div>
          <div class="cp-body"><pre id="raw-code-pre"><span class="cp-empty">Run generation to see output</span></pre></div>
        </div>
        <div class="code-panel">
          <div class="cp-hdr"><span class="cp-title">DeepSeek Refined</span><span class="cp-badge refined">✦ refined</span></div>
          <div class="cp-body"><pre id="refined-code-pre"><span class="cp-empty">Refinement pending…</span></pre></div>
        </div>
      </div>
    </div>
  </div><!-- /sp-single -->

  <!-- Codebase ZIP -->
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

  <div class="lbl">Active File <span class="lbl-badge" id="ref-auto-badge">auto</span></div>
  <div class="ref-file-card mb">
    <div style="font-size:16px;flex-shrink:0;line-height:1;padding-top:1px">🐍</div>
    <div class="ref-body">
      <div class="ref-name empty" id="ref-name">Open a Python file in the editor</div>
      <div class="ref-sub" id="ref-sub"></div>
    </div>
    <button class="fc-dismiss" id="ref-dismiss" title="Clear file" onclick="clearRef()">×</button>
  </div>

  <!-- Model picker -->
  <div class="model-pick-wrap">
    <div class="model-pick-title">Select Model(s) — pick multiple for ensemble (runs sequentially)</div>
    <div class="model-checks">
      <div class="mc-row checked" id="mc-ds" onclick="toggleModel('deepseek-coder:1.3b',this)">
        <input type="checkbox" id="chk-ds" checked>
        <span class="mc-badge ds">DS</span>
        <span class="mc-label">deepseek-coder:1.3b</span>
        <span class="mc-meta">1.3B · fast</span>
      </div>
      <div class="mc-row" id="mc-sc" onclick="toggleModel('starcoder',this)">
        <input type="checkbox" id="chk-sc">
        <span class="mc-badge sc">SC</span>
        <span class="mc-label">starcoder</span>
        <span class="mc-meta">15.5B</span>
      </div>
      <div class="mc-row" id="mc-cl" onclick="toggleModel('codellama:7b',this)">
        <input type="checkbox" id="chk-cl">
        <span class="mc-badge cl">CL</span>
        <span class="mc-label">codellama:7b</span>
        <span class="mc-meta">7B · quality</span>
      </div>
    </div>
  </div>

  <button class="btn btn-violet" id="btn-refactor-run" onclick="runRefactor()" disabled>⟳ Run Refactor</button>

  <!-- Loader + overall progress -->
  <div class="loader" id="ld-ref"><div class="ring" id="ref-ring"></div><span class="loader-txt" id="ld-ref-txt">Initialising…</span></div>
  <div class="progress-wrap" id="ref-prog-wrap" style="display:none;margin-top:10px;"><div class="progress-bar" id="ref-prog-bar"></div></div>
  <div class="progress-label" id="ref-prog-lbl" style="display:none"></div>

  <!-- Ensemble stepper -->
  <div class="ens-stepper" id="ens-stepper">
    <div class="ens-step-hdr">Ensemble Progress</div>
    <div class="ens-steps" id="ens-steps"></div>
  </div>

  <div class="pill" id="pill-ref"><span class="pdot"></span><span id="pill-ref-txt"></span></div>

  <!-- Metrics table (appears as each model finishes) -->
  <div class="ref-metrics-section" id="ref-metrics-section">
    <div class="section-hdr">Metrics</div>
    <div class="ref-mtable">
      <div class="ref-mhdr">
        <span>Model</span><span>CC Δ</span><span>PEP8 Δ</span><span>HD Δ</span><span>LOC Δ</span><span>Reward</span>
      </div>
      <div id="ref-mrows"></div>
    </div>
  </div>

  <!-- Diff viewer -->
  <div class="ref-diff-section" id="ref-diff-section">
    <div class="section-hdr">Diff</div>
    <div class="ref-diff-wrap">
      <div class="ref-diff-hdr">
        <span class="diff-title" id="ref-diff-title">original → refactored</span>
        <div class="diff-model-btns" id="ref-diff-btns"></div>
        <button class="btn-save-ref" onclick="saveRefactorChoice()">💾 Save</button>
      </div>
      <pre class="diff-pre" id="ref-diff-pre"></pre>
    </div>
  </div>

</div><!-- /mp-refactor -->

<script>
const vscode = acquireVsCodeApi();
const BACKEND_URL = 'http://localhost:8000';

const MODELS = [
  { id:'deepseek-coder:1.3b', chkId:'chk-ds', rowId:'mc-ds', cls:'ds' },
  { id:'starcoder',           chkId:'chk-sc', rowId:'mc-sc', cls:'sc' },
  { id:'codellama:7b',        chkId:'chk-cl', rowId:'mc-cl', cls:'cl' },
];

/* ── State ─────────────────────────────────── */
let singleFilePath = '', singleDirPath = '';
let zipFilePath = '', refactorPath = '';
let zipAnalysisMode = 'single';
const pollTimers = {};
let connApiOk = false, connOllamaOk = false;

// Refactor state
let refRunning = false;
let refResults = [];        // { model, status, reward, delta, diff, refactored_code, error }
let refSelectedModel = null;
let ensQueue = [];          // ordered list of model ids for this run
let ensIndex = 0;           // which model in ensQueue we are currently running
let refPollTimer = null;

/* ── Connection bar ──────────────────────────── */
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

/* ── Tab switching ───────────────────────────── */
function oSwitch(id,btn) {
  document.querySelectorAll('.otab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('.mpanel').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById('mp-'+id).classList.add('on');
}
function iSwitch(id,btn) {
  document.querySelectorAll('.itab').forEach(t=>t.classList.remove('on'));
  document.querySelectorAll('.spanel').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on'); document.getElementById('sp-'+id).classList.add('on');
}

/* ── Analysis mode (test gen zip) ────────────── */
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

/* ── Test gen polling ────────────────────────── */
function startPolling(scope,jobId) {
  stopPolling(scope);
  pollTimers[scope] = setInterval(()=>vscode.postMessage({type:'pollJob',jobId,scope}),2000);
}
function stopPolling(scope) {
  if(pollTimers[scope]){ clearInterval(pollTimers[scope]); delete pollTimers[scope]; }
}

/* ── Model picker ────────────────────────────── */
function toggleModel(modelId, rowEl) {
  const m = MODELS.find(x=>x.id===modelId);
  if(!m) return;
  const chk = document.getElementById(m.chkId);
  chk.checked = !chk.checked;
  rowEl.classList.toggle('checked', chk.checked);
  updateRunBtn();
}

function selectedModels() {
  return MODELS.filter(m=>document.getElementById(m.chkId).checked).map(m=>m.id);
}

function updateRunBtn() {
  const sel = selectedModels();
  const btn = document.getElementById('btn-refactor-run');
  if(!sel.length || !refactorPath || refRunning){ btn.disabled=true; return; }
  btn.disabled = false;
  if(sel.length === 1) {
    const short = sel[0].split(':')[0];
    btn.className = 'btn btn-violet';
    btn.textContent = '⟳ Refactor with '+short;
  } else {
    btn.className = 'btn btn-amber';
    btn.textContent = '◈ Ensemble Refactor ('+sel.length+' models, sequential)';
  }
}

/* ── Start refactor ──────────────────────────── */
function runRefactor() {
  if(!refactorPath){ showPill('ref','err','No Python file open'); return; }
  if(!connApiOk){ showPill('ref','err','API offline — start the backend first'); return; }
  const sel = selectedModels();
  if(!sel.length){ showPill('ref','err','Select at least one model'); return; }

  // Reset state
  refRunning = true; refResults = []; refSelectedModel = null;
  ensQueue = [...sel]; ensIndex = 0;

  document.getElementById('btn-refactor-run').disabled = true;
  document.getElementById('ref-dismiss').disabled = true;
  document.getElementById('ref-metrics-section').classList.remove('on');
  document.getElementById('ref-diff-section').classList.remove('on');
  document.getElementById('ref-mrows').innerHTML = '';
  document.getElementById('ref-diff-btns').innerHTML = '';
  document.getElementById('ref-diff-pre').textContent = '';
  hidePill('ref');

  const isEnsemble = sel.length > 1;

  if(isEnsemble) {
    buildStepper(sel);
    document.getElementById('ens-stepper').classList.add('on');
    document.getElementById('ref-ring').className = 'ring amber';
    setRefProgress(0, 'Preparing ensemble…');
  } else {
    document.getElementById('ens-stepper').classList.remove('on');
    document.getElementById('ref-ring').className = 'ring';
    setRefProgress(0, 'Starting…');
  }
  setLoader('ref', true, isEnsemble ? 'Ensemble: model 1 of '+sel.length+'…' : 'Submitting…');
  kickNextModel();
}

/* ── Build ensemble stepper UI ───────────────── */
function buildStepper(models) {
  const wrap = document.getElementById('ens-steps');
  wrap.innerHTML = '';
  models.forEach((m,i) => {
    const mc = MODELS.find(x=>x.id===m);
    const div = document.createElement('div');
    div.className = 'ens-step' + (i===0 ? ' active' : '');
    div.id = 'ens-step-'+i;
    div.innerHTML =
      '<div class="ens-step-top">' +
        '<span class="step-ico">'+(i===0?'⟳':'·')+'</span>' +
        '<span class="step-name"><span class="mc-badge '+(mc?.cls||'')+'" style="margin-right:4px">'+(mc?.cls?.toUpperCase()||'')+'</span>'+esc(m)+'</span>' +
        '<span class="step-status" id="step-st-'+i+'">'+(i===0?'running…':'queued')+'</span>' +
      '</div>' +
      '<div class="ens-step-prog'+(i===0?' on':'')+'" id="step-prog-'+i+'">' +
        '<div class="ens-step-prog-bar" id="step-prog-bar-'+i+'"></div>' +
      '</div>';
    wrap.appendChild(div);
  });
}

/* ── Fire the next model in queue ────────────── */
function kickNextModel() {
  if(ensIndex >= ensQueue.length){ finishAllRefactors(); return; }
  vscode.postMessage({ type:'refactorSingleModel', filePath:refactorPath, model:ensQueue[ensIndex] });
}

/* ── Refactor-specific poll ──────────────────── */
function startRefPoll(jobId) {
  stopRefPoll();
  refPollTimer = setInterval(()=>vscode.postMessage({type:'pollJob',jobId,scope:'refactor'}),2000);
}
function stopRefPoll() {
  if(refPollTimer){ clearInterval(refPollTimer); refPollTimer=null; }
}

/* ── In-progress update for current model ────── */
function onRefactorProgress(s) {
  const pct = s.progress || 0;
  const lbl = s.phase_label || 'Working…';
  const total = ensQueue.length;
  const base = Math.round((ensIndex/total)*100);
  const slice = Math.round((1/total)*pct);
  setRefProgress(base+slice, lbl+(total>1?' (model '+(ensIndex+1)+'/'+total+')':''));

  // Update stepper bar
  const barEl = document.getElementById('step-prog-bar-'+ensIndex);
  if(barEl) barEl.style.width = pct+'%';

  // Live preview of latest iteration metrics
  if(s.iterations && s.iterations.length) {
    const last = s.iterations[s.iterations.length-1];
    upsertMetricRow(ensQueue[ensIndex], last.reward, last.delta, 'run');
  }

  setLoader('ref', true, lbl+(total>1?' — model '+(ensIndex+1)+'/'+total:''));
}

/* ── One model finished ──────────────────────── */
function onRefactorModelDone(s) {
  stopRefPoll();
  const model = ensQueue[ensIndex];

  if(s.status === 'error') {
    refResults.push({ model, status:'error', error:s.error||'Error' });
    upsertMetricRow(model, null, {}, 'err');
    markStepFail(ensIndex, s.error||'error');
  } else {
    const iters = s.iterations || [];
    const best = iters.length ? iters.reduce((a,b)=>b.reward>a.reward?b:a) : null;
    const result = {
      model,
      status: 'ok',
      reward: s.best_reward ?? best?.reward ?? null,
      delta: best?.delta || {},
      diff: s.final_diff || '',
      refactored_code: s.best_code || '',
    };
    refResults.push(result);
    upsertMetricRow(model, result.reward, result.delta, 'ok');
    markStepDone(ensIndex);
    if(result.refactored_code) addDiffBtn(model, result.diff, result.refactored_code);
  }

  ensIndex++;
  const total = ensQueue.length;
  setRefProgress(Math.round((ensIndex/total)*100), ensIndex+'/'+total+' model'+(total>1?'s':'')+' done');

  if(ensIndex < total) {
    // Mark next step active
    const next = document.getElementById('ens-step-'+ensIndex);
    if(next) {
      next.classList.add('active');
      const ico = next.querySelector('.step-ico'); if(ico) ico.textContent='⟳';
      const st = document.getElementById('step-st-'+ensIndex); if(st) st.textContent='running…';
      const prog = document.getElementById('step-prog-'+ensIndex); if(prog) prog.classList.add('on');
    }
    setLoader('ref', true, 'Ensemble: model '+(ensIndex+1)+' of '+total+'…');
    kickNextModel();
  } else {
    finishAllRefactors();
  }
}

/* ── All models done ─────────────────────────── */
function finishAllRefactors() {
  stopRefPoll();
  refRunning = false;
  setLoader('ref', false);
  hideProgress('ref');
  document.getElementById('ens-stepper').classList.remove('on');
  document.getElementById('ref-dismiss').disabled = false;
  updateRunBtn();

  const ok = refResults.filter(r=>r.status==='ok').length;
  const total = refResults.length;
  if(!ok){ showPill('ref','err','All models failed'); return; }

  showPill('ref','ok', ok+'/'+total+' model'+(total>1?'s':'')+' succeeded');
  document.getElementById('ref-metrics-section').classList.add('on');
  if(refResults.some(r=>r.diff)) document.getElementById('ref-diff-section').classList.add('on');

  // Highlight best reward row
  const withReward = refResults.filter(r=>r.reward!=null);
  if(withReward.length) {
    const best = withReward.reduce((a,b)=>b.reward>a.reward?b:a);
    const el = document.getElementById('mrow-'+safeId(best.model));
    if(el) el.classList.add('best-row');
  }
}

/* ── Metric row upsert ───────────────────────── */
function upsertMetricRow(model, reward, delta, state) {
  const rowId = 'mrow-'+safeId(model);
  let row = document.getElementById(rowId);
  const mc = MODELS.find(x=>x.id===model);
  const d = delta || {};

  // For refactor metrics: lower CC/PEP8/HD/LOC is better, so negative delta = good (green)
  const fmt = v => v==null ? '—' : (v>0?'+':'')+v.toFixed(1);
  const dc = v => v==null?'delta-dim':v<0?'delta-pos':v>0?'delta-neg':'delta-neu';
  const rw = reward!=null ? reward.toFixed(3) : '—';
  const rwCls = reward==null?'delta-dim':reward>=0.3?'delta-pos':reward>=0?'delta-neu':'delta-neg';
  const stateTag = state==='run'  ? '<span class="tag run sm">…</span>'
                 : state==='ok'   ? '<span class="tag ok sm">ok</span>'
                 : state==='err'  ? '<span class="tag err sm">err</span>' : '';

  const html =
    '<span class="mc-badge '+(mc?.cls||'')+' sm">'+esc(model)+'</span>'+
    '<span class="'+dc(d.cyclomatic_delta)+'">'+fmt(d.cyclomatic_delta)+'</span>'+
    '<span class="'+dc(d.pep8_delta)+'">'+fmt(d.pep8_delta)+'</span>'+
    '<span class="'+dc(d.halstead_delta)+'">'+fmt(d.halstead_delta)+'</span>'+
    '<span class="'+dc(d.loc_delta)+'">'+fmt(d.loc_delta)+'</span>'+
    '<span class="reward-cell '+rwCls+'">'+rw+stateTag+'</span>';

  document.getElementById('ref-metrics-section').classList.add('on');
  if(!row) {
    row = document.createElement('div');
    row.className = 'ref-mrow'+(state==='run'?' loading-row':'');
    row.id = rowId;
    document.getElementById('ref-mrows').appendChild(row);
  } else {
    row.classList.toggle('loading-row', state==='run');
  }
  row.innerHTML = html;
}

/* ── Diff button ─────────────────────────────── */
function addDiffBtn(model, diff, code) {
  const mc = MODELS.find(x=>x.id===model);
  if(document.getElementById('diffbtn-'+safeId(model))) return;
  const b = document.createElement('button');
  b.className = 'diff-mbtn '+(mc?.cls||'');
  b.id = 'diffbtn-'+safeId(model);
  b.textContent = model.split(':')[0];
  b.onclick = () => {
    document.querySelectorAll('.diff-mbtn').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    refSelectedModel = model;
    document.getElementById('ref-diff-pre').textContent = diff || '(no diff available)';
    document.getElementById('ref-diff-title').textContent = 'original → '+model;
  };
  document.getElementById('ref-diff-btns').appendChild(b);
  if(!refSelectedModel) {
    b.classList.add('on');
    refSelectedModel = model;
    document.getElementById('ref-diff-pre').textContent = diff || '(no diff available)';
    document.getElementById('ref-diff-title').textContent = 'original → '+model;
    document.getElementById('ref-diff-section').classList.add('on');
  }
}

/* ── Stepper helpers ─────────────────────────── */
function markStepDone(i) {
  const el = document.getElementById('ens-step-'+i); if(!el) return;
  el.classList.remove('active'); el.classList.add('done');
  const ico = el.querySelector('.step-ico'); if(ico) ico.textContent = '✓';
  const st = document.getElementById('step-st-'+i); if(st) st.textContent = 'done';
  const bar = document.getElementById('step-prog-bar-'+i); if(bar) bar.style.width='100%';
}
function markStepFail(i, msg) {
  const el = document.getElementById('ens-step-'+i); if(!el) return;
  el.classList.remove('active'); el.classList.add('fail');
  const ico = el.querySelector('.step-ico'); if(ico) ico.textContent = '✗';
  const st = document.getElementById('step-st-'+i); if(st){ st.textContent='failed'; st.title=msg||''; }
}

/* ── Save ────────────────────────────────────── */
function saveRefactorChoice() {
  if(!refSelectedModel){ showPill('ref','err','Select a model first'); return; }
  const r = refResults.find(x=>x.model===refSelectedModel);
  if(!r||!r.refactored_code){ showPill('ref','err','No code to save'); return; }
  vscode.postMessage({ type:'saveRefactored', filePath:refactorPath, code:r.refactored_code, model:refSelectedModel });
}

function clearRef() {
  refactorPath = '';
  const n = document.getElementById('ref-name');
  n.textContent = 'Open a Python file in the editor'; n.classList.add('empty');
  document.getElementById('ref-sub').textContent = '';
  document.getElementById('ref-dismiss').classList.remove('visible');
  document.getElementById('ref-metrics-section').classList.remove('on');
  document.getElementById('ref-diff-section').classList.remove('on');
  document.getElementById('ens-stepper').classList.remove('on');
  hideProgress('ref');
  setLoader('ref',false);
  hidePill('ref');
  updateRunBtn();
}

/* ── Test gen file helpers ───────────────────── */
function pickSingle(){ vscode.postMessage({type:'pickSingleFile',rootFolder:singleDirPath}); }
function setSingleFile(fp,dir,name) {
  singleFilePath=fp; singleDirPath=dir||fp.replace(/[\\/][^\\/]+$/,'');
  const nameEl=document.getElementById('sf-name');
  nameEl.textContent=name||fp.split(/[\\/]/).pop(); nameEl.classList.remove('empty');
  document.getElementById('sf-dir').textContent=singleDirPath;
  document.getElementById('sf-card').classList.add('active');
  document.getElementById('btn-single').disabled=false;
  document.getElementById('sf-dismiss').classList.add('visible');
}
function clearSingle() {
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
function genSingle() {
  if(!singleFilePath){ showPill('single','err','No file selected'); return; }
  if(!connApiOk){ showPill('single','err','API offline — start the backend first'); return; }
  setLoader('single',true,'Submitting job…');
  setRunning('single',true); hidePill('single');
  document.getElementById('algo-section').classList.remove('on');
  document.getElementById('code-section').classList.remove('on');
  document.getElementById('btn-single').disabled=true;
  document.getElementById('single-prog-wrap').style.display='none';
  document.getElementById('single-prog-lbl').style.display='none';
  vscode.postMessage({type:'generateSingle',filePath:singleFilePath,dirPath:singleDirPath});
}

/* ── Test gen ZIP ────────────────────────────── */
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

/* ── Shared UI helpers ───────────────────────── */
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
  document.getElementById(scope+'-prog-wrap').style.display='block';
  document.getElementById(scope+'-prog-lbl').style.display='block';
  document.getElementById(scope+'-prog-bar').style.width=pct+'%';
  document.getElementById(scope+'-prog-lbl').textContent=label;
}
function hideProgress(scope) {
  const w=document.getElementById(scope+'-prog-wrap'); if(w) w.style.display='none';
  const l=document.getElementById(scope+'-prog-lbl'); if(l) l.style.display='none';
}
function setRefProgress(pct,label) {
  document.getElementById('ref-prog-wrap').style.display='block';
  document.getElementById('ref-prog-lbl').style.display='block';
  document.getElementById('ref-prog-bar').style.width=pct+'%';
  document.getElementById('ref-prog-lbl').textContent=label;
}
function setRunning(scope,running) {
  if(scope==='single'){
    document.getElementById('btn-browse-single').disabled=running;
    document.getElementById('sf-dismiss').disabled=running;
  } else if(scope==='zip'){
    document.getElementById('btn-browse-zip').disabled=running;
    document.getElementById('zip-dismiss').disabled=running;
    document.getElementById('mtog-single').disabled=running;
    document.getElementById('mtog-ensemble').disabled=running;
  }
}
function scoreClass(pct){ return pct>=70?'score-g':pct>=40?'score-a':'score-r'; }
function esc(t){ const d=document.createElement('div');d.textContent=t;return d.innerHTML; }
function safeId(s){ return s.replace(/[^a-zA-Z0-9]/g,'_'); }

/* ── Render algo table ───────────────────────── */
function renderAlgoRows(results) {
  const container=document.getElementById('algo-rows');
  container.innerHTML='';
  results.forEach(r=>{
    const cov=r.metrics?.coverage_percent??Math.round((r.coverage||0)*100);
    const mut=r.metrics?.mutation_score!=null?Math.round(r.metrics.mutation_score*100):Math.round((r.mutation_score||0)*100);
    const algo=(r.algorithm||'').toLowerCase();
    const row=document.createElement('div'); row.className='at-row';
    row.innerHTML=
      '<div class="at-cell"><span class="algo-badge '+algo+'">'+esc(r.algorithm||'—')+'</span></div>'+
      '<div class="at-cell">'+(r.num_tests!=null?r.num_tests+' tests':'—')+'</div>'+
      '<div class="at-cell right '+(r.status==='success'?scoreClass(cov):'score-d')+'">'+(r.status==='success'?cov+'%':'—')+'</div>'+
      '<div class="at-cell right '+(r.status==='success'?scoreClass(mut):'score-d')+'">'+(r.status==='success'?mut+'%':'—')+'</div>'+
      '<div class="at-cell right">'+(r.status==='success'?'<span class="tag ok">ok</span>':'<span class="tag err" title="'+esc(r.error||'')+'">error</span>')+'</div>';
    container.appendChild(row);
  });
}

function renderCodePanels(algoResults,refinement) {
  const successful=algoResults.filter(r=>r.status==='success'&&r.content);
  const best=successful.length?successful.reduce((a,b)=>(b.coverage||0)>(a.coverage||0)?b:a):null;
  const rawPre=document.getElementById('raw-code-pre');
  const rawLabel=document.getElementById('raw-algo-label');
  if(best){ rawPre.textContent=best.content; rawLabel.textContent=best.algorithm; }
  else { rawPre.innerHTML='<span class="cp-empty">No successful output</span>'; rawLabel.textContent='—'; }
  const refinedPre=document.getElementById('refined-code-pre');
  if(refinement&&refinement.status==='success'&&refinement.refined_code) refinedPre.textContent=refinement.refined_code;
  else if(refinement&&refinement.error) refinedPre.innerHTML='<span class="cp-empty">Refinement failed: '+esc(refinement.error)+'</span>';
  else refinedPre.innerHTML='<span class="cp-empty">No refined output</span>';
}

function handleJobComplete(scope,jobData) {
  stopPolling(scope); setLoader(scope,false); hideProgress(scope); setRunning(scope,false);
  const btnMap={single:'btn-single',zip:'btn-zip'};
  if(btnMap[scope]) document.getElementById(btnMap[scope]).disabled=false;
  if(jobData.status==='error'){ showPill(scope,'err',jobData.error||'Job failed'); return; }
  if(scope==='single'){
    const results=jobData.results||[];
    const refinement=jobData.refinement||null;
    const ok=results.filter(r=>r.status==='success').length;
    showPill('single','ok',ok+'/'+results.length+' algorithms succeeded'+(refinement?.status==='success'?' · Refined ✓':''));
    renderAlgoRows(results);
    document.getElementById('algo-section').classList.add('on');
    if(jobData.download_url){ const dl=document.getElementById('single-dl'); dl.href=BACKEND_URL+jobData.download_url; dl.style.display=''; }
    renderCodePanels(results,refinement);
    document.getElementById('code-section').classList.add('on');
  } else if(scope==='zip'){
    const results=jobData.results||[];
    const ok=results.filter(r=>r.status==='success').length;
    const mode=jobData.analysis_mode||zipAnalysisMode;
    showPill('zip','ok',ok+'/'+results.length+' files analysed ('+mode+')');
    renderZipRows(results,document.getElementById('zr-rows'));
    if(jobData.download_url){ const dl=document.getElementById('zr-dl'); dl.href=BACKEND_URL+jobData.download_url; dl.style.display=''; }
    document.getElementById('zr-main').classList.add('on');
  }
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

/* ── Message handler ──────────────────────────── */
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
      updateRunBtn();
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
      setLoader(scope,true,'Running pipeline…');
      showProgress(scope,0,'Starting…');
      startPolling(scope,m.jobId);
      break;
    }

    case 'jobStatus': {
      const scope=m.scope, s=m.status;

      // Refactor polling
      if(scope==='refactor'){
        if(s.status==='queued'||s.status==='processing') onRefactorProgress(s);
        else onRefactorModelDone(s);
        break;
      }

      // Test gen polling
      if(s.status==='queued'||s.status==='processing'){
        const pct=s.progress||0;
        const phaseLabel=s.phase_label||(s.phase==='pynguin'?'Running Pynguin algorithms…':s.phase==='refining'?'Refining with DeepSeek…':'Running pipeline…');
        const file=s.current_file?' — '+s.current_file:'';
        setLoader(scope,true,phaseLabel);
        showProgress(scope,pct,pct+'%'+file);
        if(scope==='single'&&s.algo_results&&s.algo_results.length){
          renderAlgoRows(s.algo_results); document.getElementById('algo-section').classList.add('on');
        }
      } else {
        handleJobComplete(scope,s);
      }
      break;
    }

    case 'generationError': {
      const sc=m.scope||'single';
      stopPolling(sc); setLoader(sc,false); hideProgress(sc); setRunning(sc,false);
      const btnId=sc==='single'?'btn-single':sc==='zip'?'btn-zip':null;
      if(btnId) document.getElementById(btnId).disabled=false;
      showPill(sc,'err',m.error||'Error');
      break;
    }

    // Backend accepted the refactor job — start polling it
    case 'refactorJobStarted':
      startRefPoll(m.jobId);
      break;

    // Backend rejected the refactor job submission
    case 'refactorJobError': {
      stopRefPoll();
      const model = m.model || ensQueue[ensIndex] || '?';
      markStepFail(ensIndex, m.error);
      refResults.push({ model, status:'error', error:m.error });
      upsertMetricRow(model, null, {}, 'err');
      ensIndex++;
      if(ensIndex < ensQueue.length) kickNextModel();
      else finishAllRefactors();
      break;
    }

    case 'backendStatus':
      connApiOk=m.apiOk; connOllamaOk=m.ollamaOk;
      updateConnBar(
        m.apiOk?'ok':'err', m.apiDetail||(m.apiOk?'connected':'offline'),
        m.ollamaOk?'ok':'err', m.ollamaDetail||(m.ollamaOk?'ready':'offline')
      );
      updateRunBtn();
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
