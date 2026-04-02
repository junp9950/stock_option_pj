import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import MarketGauge from "../components/MarketGauge";
import SignalCard from "../components/SignalCard";
import StockTable from "../components/StockTable";

export default function Dashboard({ marketSignal, recommendations, history }) {
  return (
    <div className="grid">
      <MarketGauge marketSignal={marketSignal} />
      <SignalCard title="추천 종목 수" value={recommendations.length} subtitle="상위 점수 기준" />
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
        <StockTable items={recommendations} />
      </div>
    </div>
  );
}

