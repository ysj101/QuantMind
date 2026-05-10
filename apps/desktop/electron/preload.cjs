const { contextBridge, ipcRenderer } = require("electron");

function invoke(channel, params) {
  return ipcRenderer.invoke(channel, params || {});
}

contextBridge.exposeInMainWorld("quantmind", {
  listRuns: (filters) => invoke("quantmind:listRuns", filters),
  getDailySummary: (date) => invoke("quantmind:getDailySummary", { date }),
  listExtractedSymbols: (date, filters) =>
    invoke("quantmind:listExtractedSymbols", { date, ...(filters || {}) }),
  getSymbolDetail: (date, code) => invoke("quantmind:getSymbolDetail", { date, code }),
  getDebateTranscript: (date, code) => invoke("quantmind:getDebateTranscript", { date, code }),
  searchHistory: (filters) => invoke("quantmind:searchHistory", filters),
  runDaily: (options) => invoke("quantmind:runDaily", options),
  getRunStatus: (runId) => invoke("quantmind:getRunStatus", { runId }),
});
