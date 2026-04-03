import { formatOk } from "../utils/format";

const TAG_STYLES = {
  "기관+외국인 동시매수": { bg: "#1e3a5f", color: "#93c5fd" },
  동시매수: { bg: "#14532d", color: "#86efac" },
  기관: { bg: "#1e3a8a", color: "#bfdbfe" },
  외국인: { bg: "#164e63", color: "#a5f3fc" },
  대규모: { bg: "#713f12", color: "#fde68a" },
  개인: { bg: "#7f1d1d", color: "#fca5a5" },
};

function tagStyle(tag) {
  for (const [key, style] of Object.entries(TAG_STYLES)) {
    if (tag.startsWith(key)) return style;
  }
  return { bg: "#374151", color: "#e5e7eb" };
}

function MarketBadge({ market }) {
  const isKosdaq = market === "KOSDAQ";
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 700,
        padding: "2px 6px",
        borderRadius: 4,
        background: isKosdaq ? "#4c1d95" : "#14532d",
        color: isKosdaq ? "#ddd6fe" : "#86efac",
        letterSpacing: 0.5,
      }}
    >
      {market}
    </span>
  );
}

function NetBuyCell({ value }) {
  const text = formatOk(value);
  const color = value > 0 ? "#f87171" : value < 0 ? "#60a5fa" : "#6b7280";
  return <span style={{ color, fontVariantNumeric: "tabular-nums" }}>{text}</span>;
}

export default function StockTable({ items }) {
  if (!items || items.length === 0) {
    return (
      <div style={{ background: "#0d1117", borderRadius: 12, padding: "32px 24px", textAlign: "center", color: "#6b7280" }}>
        추천 종목 데이터가 없습니다. 일일 집계를 실행해 주세요.
      </div>
    );
  }

  return (
    <div style={{ background: "#0d1117", borderRadius: 12, overflow: "hidden" }}>
      <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #21262d" }}>
        <span style={{ color: "#e6edf3", fontWeight: 700, fontSize: 15 }}>추천 종목</span>
        <span style={{ color: "#6b7280", fontSize: 13, marginLeft: 10 }}>{items.length}개</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", color: "#c9d1d9", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#161b22" }}>
              {["점수", "코드", "종목명", "시장", "기관 순매수", "외국인 순매수", "개인", "연속일", "태그"].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: "10px 12px",
                    textAlign: "left",
                    color: "#8b949e",
                    fontWeight: 600,
                    fontSize: 12,
                    borderBottom: "1px solid #30363d",
                    whiteSpace: "nowrap",
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr
                key={item.code}
                style={{
                  borderBottom: "1px solid #21262d",
                  background: idx % 2 === 0 ? "transparent" : "#0d1117",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#161b22")}
                onMouseLeave={(e) => (e.currentTarget.style.background = idx % 2 === 0 ? "transparent" : "#0d1117")}
              >
                {/* 점수 */}
                <td style={{ padding: "10px 12px", fontWeight: 700, fontSize: 18, color: "#58a6ff", minWidth: 48 }}>
                  {Math.round(item.total_score)}
                </td>
                {/* 코드 */}
                <td style={{ padding: "10px 12px", color: "#79c0ff", fontFamily: "monospace", whiteSpace: "nowrap" }}>
                  {item.code}
                </td>
                {/* 종목명 */}
                <td style={{ padding: "10px 12px", fontWeight: 600, color: "#e6edf3", whiteSpace: "nowrap" }}>
                  {item.name}
                </td>
                {/* 시장 */}
                <td style={{ padding: "10px 12px" }}>
                  <MarketBadge market={item.market ?? "KOSPI"} />
                </td>
                {/* 기관 순매수 */}
                <td style={{ padding: "10px 12px", textAlign: "right" }}>
                  <NetBuyCell value={item.institution_net_buy ?? 0} />
                </td>
                {/* 외국인 순매수 */}
                <td style={{ padding: "10px 12px", textAlign: "right" }}>
                  <NetBuyCell value={item.foreign_net_buy ?? 0} />
                </td>
                {/* 개인 */}
                <td style={{ padding: "10px 12px", textAlign: "right" }}>
                  <NetBuyCell value={item.individual_net_buy ?? 0} />
                </td>
                {/* 연속일 */}
                <td style={{ padding: "10px 12px", textAlign: "center" }}>
                  {item.consecutive_days >= 1 ? (
                    <span
                      style={{
                        background: "#7c3aed",
                        color: "#ddd6fe",
                        borderRadius: 999,
                        padding: "2px 10px",
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {item.consecutive_days}일
                    </span>
                  ) : (
                    <span style={{ color: "#484f58" }}>-</span>
                  )}
                </td>
                {/* 태그 */}
                <td style={{ padding: "8px 12px", minWidth: 200 }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {(item.tags ?? []).map((tag) => {
                      const { bg, color } = tagStyle(tag);
                      return (
                        <span
                          key={tag}
                          style={{
                            background: bg,
                            color,
                            borderRadius: 4,
                            padding: "2px 7px",
                            fontSize: 11,
                            fontWeight: 600,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {tag}
                        </span>
                      );
                    })}
                    {(item.tags ?? []).length === 0 && <span style={{ color: "#484f58" }}>-</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
