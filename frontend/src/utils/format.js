export function formatNumber(value) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

export function formatOk(value) {
  if (value === null || value === undefined) return "-";
  const sign = value >= 0 ? "+" : "";
  const ok = value / 100_000_000;
  if (Math.abs(ok) >= 1) {
    return sign + Math.round(ok) + "억";
  }
  const man = value / 10_000;
  if (Math.abs(man) >= 1) {
    return sign + Math.round(man) + "만";
  }
  return sign + Math.round(value);
}

export function signalClass(signal) {
  if (signal === "상방") return "badge-up";
  if (signal === "하방") return "badge-down";
  return "badge-neutral";
}

