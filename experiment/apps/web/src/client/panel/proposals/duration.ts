export const durationParts = (iso: string) => {
  const match = /^P(?:T)?(?:(?<hours>\d+)H)?(?:(?<minutes>\d+)M)?$/u.exec(iso);

  return {
    hours: Number(match?.groups?.hours ?? 0),
    minutes: Number(match?.groups?.minutes ?? 0),
  };
};

export const pickedDuration = (
  duration: string,
  offered: readonly string[]
) => {
  if (offered.length === 0 || duration === "") {
    return "";
  }

  return offered.includes(duration) ? duration : "custom";
};

export const durationLabel = (iso: string) => {
  const { hours, minutes } = durationParts(iso);

  if (hours > 0 && minutes > 0) {
    return `${hours}h ${minutes}min`;
  }

  if (hours > 0) {
    return `${hours}h`;
  }

  return minutes > 0 ? `${minutes}min` : "";
};
