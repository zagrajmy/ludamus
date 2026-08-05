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
