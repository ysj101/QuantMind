const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const readline = require("node:readline");

class PythonRpcClient {
  constructor(repoRoot) {
    this.repoRoot = repoRoot;
    this.nextId = 1;
    this.pending = new Map();
    this.process = null;
  }

  start() {
    if (this.process) return;
    this.process = spawn("uv", ["run", "python", "-m", "quantmind.desktop"], {
      cwd: this.repoRoot,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
    });

    const lines = readline.createInterface({ input: this.process.stdout });
    lines.on("line", (line) => this.handleLine(line));
    this.process.stderr.on("data", (chunk) => {
      console.error(`[quantmind-rpc] ${chunk.toString()}`);
    });
    this.process.on("error", (error) => this.rejectAll(error));
    this.process.on("exit", (code) => {
      this.rejectAll(new Error(`Python RPC exited with code ${code}`));
      this.process = null;
    });
  }

  handleLine(line) {
    let response;
    try {
      response = JSON.parse(line);
    } catch (error) {
      console.error("[quantmind-rpc] invalid json", error);
      return;
    }
    const entry = this.pending.get(String(response.id));
    if (!entry) return;
    this.pending.delete(String(response.id));
    if (response.error) {
      const error = new Error(response.error.message || "rpc_error");
      error.data = response.error.data;
      error.code = response.error.code;
      entry.reject(error);
    } else {
      entry.resolve(response.result);
    }
  }

  rejectAll(error) {
    for (const entry of this.pending.values()) {
      entry.reject(error);
    }
    this.pending.clear();
  }

  call(method, params = {}) {
    this.start();
    const id = String(this.nextId++);
    const payload = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin.write(`${payload}\n`, (error) => {
        if (error) {
          this.pending.delete(id);
          reject(error);
        }
      });
    });
  }

  stop() {
    if (this.process) {
      this.process.kill();
      this.process = null;
    }
  }
}

const repoRoot = process.env.QUANTMIND_REPO_ROOT || path.resolve(app.getAppPath(), "..", "..");
const rpc = new PythonRpcClient(repoRoot);

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1080,
    minHeight: 720,
    title: "QuantMind",
    backgroundColor: "#f5f1e8",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  const rendererUrl = process.env.ELECTRON_RENDERER_URL;
  if (rendererUrl) {
    mainWindow.loadURL(rendererUrl);
  } else {
    mainWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  ipcMain.handle("quantmind:listRuns", (_event, params) => rpc.call("desktop.list_runs", params));
  ipcMain.handle("quantmind:getDailySummary", (_event, params) =>
    rpc.call("desktop.get_daily_summary", params),
  );
  ipcMain.handle("quantmind:listExtractedSymbols", (_event, params) =>
    rpc.call("desktop.list_extracted_symbols", params),
  );
  ipcMain.handle("quantmind:getSymbolDetail", (_event, params) =>
    rpc.call("desktop.get_symbol_detail", params),
  );
  ipcMain.handle("quantmind:getDebateTranscript", (_event, params) =>
    rpc.call("desktop.get_debate_transcript", params),
  );
  ipcMain.handle("quantmind:searchHistory", (_event, params) =>
    rpc.call("desktop.search_history", params),
  );
  ipcMain.handle("quantmind:runDaily", (_event, params) => rpc.call("desktop.run_daily", params));
  ipcMain.handle("quantmind:getRunStatus", (_event, params) =>
    rpc.call("desktop.get_run_status", params),
  );

  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => rpc.stop());
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
