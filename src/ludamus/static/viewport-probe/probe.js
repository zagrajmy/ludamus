// Reads every viewport number Safari exposes and prints them over the page;
// index.html says what each coloured edge means.
const readout = document.getElementById("readout");
const scroller = document.getElementById("app-scroll");
const footer = document.getElementById("footer");
const rows = document.getElementById("rows");
const ruler = document.getElementById("ruler");

for (let i = 1; i <= 60; i += 1) {
  const p = document.createElement("p");
  p.textContent = `row ${i}`;
  rows.append(p);
}

for (let y = 0; y <= 1400; y += 50) {
  const tick = document.createElement("span");
  tick.style.top = `${y}px`;
  tick.textContent = String(y);
  ruler.append(tick);
}

const round = (n) => Math.round(n * 10) / 10;
const rect = (el) => el.getBoundingClientRect();

const probes = () =>
  [...document.querySelectorAll("[data-probe]")]
    .map((el) => `${el.dataset.probe.padEnd(22)} ${round(rect(el).height)}`)
    .join("\n");

const iosVersion = () => {
  const m = /OS (\d+)_(\d+)(?:_(\d+))?/.exec(navigator.userAgent);
  return m ? `${m[1]}.${m[2]}${m[3] ? `.${m[3]}` : ""}` : "not iOS?";
};

const measure = () => {
  const vv = window.visualViewport;
  const shell = rect(scroller);
  const footerBottom = rect(footer).bottom;
  const standalone =
    window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  readout.textContent = [
    `iOS ${iosVersion()}  standalone=${standalone}  dpr=${window.devicePixelRatio}`,
    `screen ${screen.width}x${screen.height}  inner ${window.innerWidth}x${window.innerHeight}  outer ${window.outerHeight}`,
    `visualViewport h=${vv ? round(vv.height) : "n/a"} top=${vv ? round(vv.offsetTop) : "n/a"} scale=${vv ? vv.scale : "n/a"}`,
    `html.clientHeight ${document.documentElement.clientHeight}  body.clientHeight ${document.body.clientHeight}`,
    probes(),
    `shell top=${round(shell.top)} bottom=${round(shell.bottom)} h=${round(shell.height)}`,
    `#app-scroll clientH=${scroller.clientHeight} scrollH=${scroller.scrollHeight} scrollTop=${round(scroller.scrollTop)}`,
    `page end (footer bottom) at y=${round(footerBottom)}  vs innerHeight ${window.innerHeight}  → ${round(window.innerHeight - footerBottom)}px of room below it`,
    `document scrollY=${round(window.scrollY)}  html.scrollHeight=${document.documentElement.scrollHeight}`,
  ].join("\n");
};

measure();
window.addEventListener("resize", measure);
window.addEventListener("scroll", measure, { passive: true });
scroller.addEventListener("scroll", measure, { passive: true });
window.visualViewport?.addEventListener("resize", measure);
window.visualViewport?.addEventListener("scroll", measure);
window.addEventListener("load", measure);
setTimeout(measure, 1000);
