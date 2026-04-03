import { useEffect, useState } from "react";
import { api } from "../services/api";

const STATUS_LABEL = {
  real: { text: "실제", color: "#2e7d32" },
  real_with_fallback: { text: "실제(fallback가능)", color: "#f57c00" },
  fallback: { text: "fallback", color: "#c62828" },
};

export default function DataSourcesBanner() {
  const [sources, setSources] = useState(null);

  useEffect(() => {
    api.getDataSources().then(setSources).catch(() => {});
  }, []);

  if (!sources) return null;

  return (
    <details style={{ margin: "8px 0", fontSize: 12 }}>
      <summary style={{ cursor: "pointer", color: "#888" }}>데이터 소스 현황</summary>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 6 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #333" }}>
            <th style={{ padding: "2px 8px" }}>항목</th>
            <th style={{ padding: "2px 8px" }}>소스</th>
            <th style={{ padding: "2px 8px" }}>상태</th>
            <th style={{ padding: "2px 8px" }}>비고</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(sources).map(([key, val]) => {
            const statusInfo = STATUS_LABEL[val.status] ?? { text: val.status, color: "#888" };
            return (
              <tr key={key} style={{ borderBottom: "1px solid #222" }}>
                <td style={{ padding: "2px 8px" }}>{key}</td>
                <td style={{ padding: "2px 8px" }}>{val.source}</td>
                <td style={{ padding: "2px 8px", color: statusInfo.color }}>{statusInfo.text}</td>
                <td style={{ padding: "2px 8px", color: "#888" }}>{val.note ?? ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
