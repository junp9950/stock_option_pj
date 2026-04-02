export function formatNumber(value) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

export function signalClass(signal) {
  if (signal === "상방") return "badge-up";
  if (signal === "하방") return "badge-down";
  return "badge-neutral";
}

