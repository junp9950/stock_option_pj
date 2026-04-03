export default function SignalCard({ title, value, subtitle }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0" }}>{value}</p>
      {subtitle ? <small>{subtitle}</small> : null}
    </div>
  );
}

