// Reading Cloudflare's verdict on an email's DKIM signatures from its headers.
//
// Cloudflare Email Routing checks DKIM on arrival and prepends its result as an (ARC-)Authentication-Results
// header with the authserv-id mx.cloudflare.net. Only the topmost such header is trusted: anything further
// down came with the message, and a sender can write whatever it likes there.

export interface DkimResult {
  domain: string;
  result: string;
}

const AUTH_HEADERS = new Set(["arc-authentication-results", "authentication-results"]);
const HEADER_SCAN_BYTES = 256 * 1024;

/** The message's header fields in order, unfolded. Names are lower-cased. */
export function headerFields(raw: Uint8Array): [string, string][] {
  const text = new TextDecoder("latin1").decode(raw.subarray(0, HEADER_SCAN_BYTES));
  const end = text.search(/\r?\n\r?\n/);
  const block = (end < 0 ? text : text.slice(0, end)).replace(/\r?\n[ \t]+/g, " ");
  const fields: [string, string][] = [];
  for (const line of block.split(/\r?\n/)) {
    const colon = line.indexOf(":");
    if (colon > 0) fields.push([line.slice(0, colon).trim().toLowerCase(), line.slice(colon + 1).trim()]);
  }
  return fields;
}

/** DKIM results from the topmost authentication header, if Cloudflare wrote it; otherwise none. */
export function dkimResults(fields: [string, string][]): DkimResult[] {
  const top = fields.find(([name]) => AUTH_HEADERS.has(name));
  if (!top) return [];
  const parts = top[1].split(";").map((p) => p.trim());
  if (/^i=\d+$/.test(parts[0] ?? "")) parts.shift(); // ARC instance number
  const servId = (parts.shift() ?? "").split(/\s+/)[0]!.toLowerCase();
  if (servId !== "cloudflare.net" && !servId.endsWith(".cloudflare.net")) return [];

  const results: DkimResult[] = [];
  for (const part of parts) {
    const verdict = /^dkim=([a-z]+)/i.exec(part);
    if (!verdict) continue;
    const d = /header\.d=([^\s;]+)/i.exec(part)?.[1] ?? /header\.i=[^\s;@]*@([^\s;]+)/i.exec(part)?.[1];
    if (d) results.push({ domain: d.toLowerCase(), result: verdict[1]!.toLowerCase() });
  }
  return results;
}
