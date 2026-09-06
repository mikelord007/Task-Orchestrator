import { isIP } from "node:net";

const MAX_FORWARDED_FOR_CHARS = 256;

/** Read only the client-address header authored by Vercel's edge. */
export function trustedVercelClientIp(headers: Headers): string | null {
  const forwarded = headers.get("x-vercel-forwarded-for");
  if (!forwarded || forwarded.length > MAX_FORWARDED_FOR_CHARS || /[\r\n]/.test(forwarded)) {
    return null;
  }

  const candidate = forwarded.split(",", 1)[0].trim();
  return isIP(candidate) ? candidate : null;
}
