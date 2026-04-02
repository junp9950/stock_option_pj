export default function DatePicker({ value, onChange }) {
  return <input type="date" value={value} onChange={(event) => onChange(event.target.value)} />;
}

