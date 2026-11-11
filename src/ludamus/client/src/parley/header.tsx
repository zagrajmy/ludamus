import type { ReactNode, Ref } from "react";

import { Icon, type IconName } from "./icons";

export const ICON_BUTTON =
  "grid size-10 shrink-0 place-items-center rounded-xl text-foreground-muted hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-border-focus";

export function IconButton({
  buttonRef,
  icon,
  label,
  onClick,
}: {
  buttonRef?: Ref<HTMLButtonElement>;
  icon: IconName;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className={ICON_BUTTON}
      onClick={onClick}
      ref={buttonRef}
      type="button"
    >
      <Icon className="size-5" name={icon} />
    </button>
  );
}

// A panel's own title bar: back to where it came from, its name, whatever
// it adds, and close.
export function PanelHeader({
  back,
  backRef,
  children,
  close,
  closeLabel,
  title,
}: {
  back: { label: string; run: () => void } | null;
  backRef?: Ref<HTMLButtonElement>;
  children?: ReactNode;
  close: () => void;
  closeLabel: string;
  title: string;
}) {
  return (
    <header
      className="flex items-center gap-1 p-[7px] pt-[max(7px,env(safe-area-inset-top))] sm:cursor-grab sm:pt-[7px]"
      data-parley-drag
    >
      {back !== null && (
        <IconButton buttonRef={backRef} icon="Back" label={back.label} onClick={back.run} />
      )}
      <h2 className={`min-w-0 flex-1 truncate text-lg font-bold ${back === null ? "pl-1.5" : ""}`}>
        {title}
      </h2>
      {children}
      <IconButton icon="Close" label={closeLabel} onClick={close} />
    </header>
  );
}
