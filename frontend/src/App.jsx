import { useEffect } from "react";
import Dashboard from "./pages/Dashboard";
import Derivatives from "./pages/Derivatives";
import StockDetail from "./pages/StockDetail";
import Performance from "./pages/Performance";
import DatePicker from "./components/DatePicker";
import LoadingState from "./components/LoadingState";
import DataSourcesBanner from "./components/DataSourcesBanner";
import { useAppStore } from "./stores/useAppStore";

export default function App() {
  const {
    selectedDate,
    marketSignal,
    recommendations,
    history,
    isLoading,
    error,
    setDate,
    fetchMarketSignal,
    fetchRecommendations,
    runDaily,
  } = useAppStore();

  useEffect(() => {
    fetchMarketSignal();
    fetchRecommendations();
  }, [selectedDate, fetchMarketSignal, fetchRecommendations]);

  return (
    <div className="app-shell">
      <section className="hero">
        <h1>선물·옵션 수급 기반 익일 종목 선별 시스템</h1>
        <p>로컬 PC에서 실행 가능한 MVP 대시보드입니다. 외부 데이터가 없을 때도 데모 데이터로 동작합니다.</p>
      </section>

      <div className="toolbar">
        <DatePicker value={selectedDate} onChange={setDate} />
        <button onClick={runDaily}>수동 파이프라인 실행</button>
      </div>

      <LoadingState loading={isLoading} error={error} />
      <DataSourcesBanner />
      <Dashboard marketSignal={marketSignal} recommendations={recommendations} history={history} />
      <div className="grid" style={{ marginTop: 16 }}>
        <Derivatives />
        <StockDetail />
        <Performance />
      </div>
    </div>
  );
}

