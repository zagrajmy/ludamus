const org = document.getElementById("aud-org") as HTMLInputElement | null;
const gracz = document.getElementById("aud-gracz") as HTMLInputElement | null;

const landing = document.querySelector(".landing");
if (landing) {
  setTimeout(() => landing.classList.add("ld-done"), 1600);
}

if (org && gracz) {
  if (location.hash === "#gracze") gracz.checked = true;

  const sync = () => {
    history.replaceState(null, "", gracz.checked ? "#gracze" : location.pathname + location.search);
  };
  org.addEventListener("change", sync);
  gracz.addEventListener("change", sync);
  addEventListener("hashchange", () => {
    if (location.hash === "#gracze") gracz.checked = true;
    else if (location.hash === "" || location.hash === "#") org.checked = true;
  });
}

const steps = [...document.querySelectorAll<HTMLInputElement>('input[name="landing-krok"]')];
const scena = document.querySelector(".sc");
if (scena && steps.length > 1 && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  let timer = 0;
  const advance = () => {
    if (document.hidden) return;
    const current = steps.findIndex((step) => step.checked);
    steps[(current + 1) % steps.length].checked = true;
  };
  const observer = new IntersectionObserver(
    ([entry]) => {
      clearInterval(timer);
      if (entry.isIntersecting) timer = globalThis.setInterval(advance, 6000);
    },
    { threshold: 0.3 },
  );
  observer.observe(scena);
  const handOver = () => {
    clearInterval(timer);
    observer.disconnect();
  };
  for (const step of steps) step.addEventListener("change", handOver);
}
