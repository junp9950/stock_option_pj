import { signalClass } from "../utils/format";

export default function MarketGauge({ marketSignal }) {
  if (!marketSignal) {
    return <div className="card">시장 시그널 데이터가 없습니다.</div>;
  }

  return (
    <div className="card">
      <h3>시장 방향성</h3>
      <p className={signalClass(marketSignal.signal)}>{marketSignal.signal}</p>
      <p>점수: {marketSignal.score}</p>
    </div>
  );
}

