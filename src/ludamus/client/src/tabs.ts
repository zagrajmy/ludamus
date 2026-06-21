/**
 * Generic tabs — driven by `aria-controls` on triggers and `id` on panels.
 *
 * Usage:
 *   <div class="tab-list" role="tablist">
 *     <button class="tab-trigger" role="tab" aria-selected="true"  aria-controls="panel-a">A</button>
 *     <button class="tab-trigger" role="tab" aria-selected="false" aria-controls="panel-b">B</button>
 *   </div>
 *   <div class="tab-content">
 *     <div class="tab-panel" role="tabpanel" id="panel-a" data-active>…</div>
 *     <div class="tab-panel" role="tabpanel" id="panel-b" inert>…</div>
 *   </div>
 */

function activateTab(trigger: Element): void {
  const tablist = trigger.closest(".tab-list");
  if (!tablist) return;

  const panelId = trigger.getAttribute("aria-controls");
  if (!panelId) return;

  for (const t of tablist.querySelectorAll(".tab-trigger")) {
    t.setAttribute("aria-selected", "false");
    t.setAttribute("tabindex", "-1");
    const id = t.getAttribute("aria-controls");
    const panel = id && document.getElementById(id);
    if (panel) {
      delete panel.dataset.active;
      panel.setAttribute("inert", "");
    }
  }

  trigger.setAttribute("aria-selected", "true");
  trigger.setAttribute("tabindex", "0");
  const active = document.getElementById(panelId);
  if (active) {
    active.dataset.active = "";
    active.removeAttribute("inert");
  }
  (trigger as HTMLElement).focus();
}

document.addEventListener("click", (e) => {
  const trigger = (e.target as Element | null)?.closest(".tab-trigger");
  if (trigger) activateTab(trigger);
});

document.addEventListener("keydown", (e) => {
  const trigger = (e.target as Element | null)?.closest(".tab-trigger");
  if (!trigger) return;

  const tablist = trigger.closest(".tab-list");
  if (!tablist) return;

  const tabs = [...tablist.querySelectorAll(".tab-trigger")] as HTMLElement[];
  const idx = tabs.indexOf(trigger as HTMLElement);

  let next = -1;
  switch (e.key) {
    case "ArrowLeft": {
      next = (idx - 1 + tabs.length) % tabs.length;
      break;
    }
    case "ArrowRight": {
      next = (idx + 1) % tabs.length;
      break;
    }
    case "End": {
      next = tabs.length - 1;
      break;
    }
    case "Home": {
      next = 0;
      break;
    }
    default:
      return;
  }

  e.preventDefault();
  activateTab(tabs[next]);
});
