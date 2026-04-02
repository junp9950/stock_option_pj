const API_BASE = "http://127.0.0.1:8000/api";

async function request(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API 요청 실패: ${path}`);
  }
  return response.json();
}

export const api = {
  getHealth: () => request("/health"),
  getMarketSignal: (date) => request(`/market-signal${date ? `?trading_date=${date}` : ""}`),
  getMarketSignalHistory: () => request("/market-signal/history"),
  getRecommendations: (date) => request(`/recommendations${date ? `?trading_date=${date}` : ""}`),
  runDaily: (date) =>
    fetch(`${API_BASE}/jobs/run-daily${date ? `?trading_date=${date}` : ""}`, { method: "POST" }).then((r) => r.json()),
  getDataSources: () => request("/data-sources"),
};

