import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import MarketGauge from "../components/MarketGauge";
import SignalCard from "../components/SignalCard";
import StockTable from "../components/StockTable";

export default function Dashboard({ marketSignal, recommendations, screenerItems, history }) {
  const tableItems = screenerItems && screenerItems.length > 0 ? screenerItems : recommendations;
  return (
    <div className="grid">
      <MarketGauge marketSignal={marketSignal} />
      <SignalCard title="스크리닝 종목 수" value={tableItems.length} subtitle="시가총액·거래대금 필터 후" />
      <SignalCard title="기준일" value={marketSignal?.trading_date ?? "-"} />
      <div className="card" style={{ minHeight: 260 }}>
        <h3>최근 시장 점수 추이</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={[...history].reverse()}>
            <XAxis dataKey="trading_date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="score" stroke="#c22b2b" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ gridColumn: "1 / -1" }}>
        <StockTable items={tableItems} />
      </div>
    </div>
  );
}

