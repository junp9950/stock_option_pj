export default function LoadingState({ loading, error }) {
  if (loading) return <div className="card">데이터를 불러오는 중입니다...</div>;
  if (error) return <div className="card">{error}</div>;
  return null;
}

