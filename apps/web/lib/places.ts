/** "Bengaluru, Remote ; pune" → ["Bengaluru", "Remote", "pune"]: places typed in one box, blanks and repeats dropped. */
export function splitPlaces(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[,;\n]/)) {
    const place = raw.trim().replace(/\s+/g, " ");
    if (place && !seen.has(place.toLowerCase())) {
      seen.add(place.toLowerCase());
      out.push(place);
    }
  }
  return out;
}
