const start = document.getElementById("id_start_time") as HTMLInputElement | null;
const end = document.getElementById("id_end_time") as HTMLInputElement | null;

const DEFAULT_DURATION_HOURS = 3;

const pad = (n: number): string => String(n).padStart(2, "0");

const toLocalDatetimeValue = (d: Date): string =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
  `T${pad(d.getHours())}:${pad(d.getMinutes())}`;

if (start && end) {
  start.addEventListener("change", () => {
    if (end.value || !start.value) return;
    const d = new Date(start.value);
    if (Number.isNaN(d.getTime())) return;
    d.setHours(d.getHours() + DEFAULT_DURATION_HOURS);
    end.value = toLocalDatetimeValue(d);
  });
}
