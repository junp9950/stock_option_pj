import { formatNumber } from "../utils/format";

export default function StockTable({ items }) {
  return (
    <div className="card">
      <h3>추천 종목</h3>
      <table>
        <thead>
          <tr>
            <th>순위</th>
            <th>종목</th>
            <th>총점</th>
            <th>종가</th>
            <th>등락률</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.code}>
              <td>{item.rank}</td>
              <td>{item.name}</td>
              <td>{item.total_score}</td>
              <td>{formatNumber(item.close_price)}</td>
              <td>{item.change_pct}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

