import { useState } from "react";

// Mirrors avatar_tags.py's palette, so a name gets the same disc in Parley
// as on the rest of the site: the colour follows the name's length.
function palette(name: string): string {
  const { length } = name;
  if (length % 4 === 0) return "bg-coral-400 text-neutral-900";
  if (length % 3 === 0) return "bg-teal-400 text-neutral-900";
  if (length % 2 === 0) return "bg-teal-500 text-neutral-900";
  return "bg-warm-400 text-neutral-900 dark:bg-warm-800 dark:text-neutral-50";
}

export function Avatar({
  className = "size-8 text-xs",
  name,
  src = "",
}: {
  className?: string;
  name: string;
  src?: string;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      aria-hidden="true"
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full font-semibold select-none ${palette(name)} ${className}`}
    >
      {name.slice(0, 2).toUpperCase()}
      {src !== "" && !failed && (
        <img
          alt=""
          className="absolute inset-0 size-full object-cover"
          loading="lazy"
          onError={() => setFailed(true)}
          src={src}
        />
      )}
    </span>
  );
}
