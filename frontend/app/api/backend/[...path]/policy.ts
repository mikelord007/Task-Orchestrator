const SAFE_SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

type RouteRule = {
  method: "GET" | "POST";
  path: RegExp;
  query?: readonly string[];
  requiredQuery?: readonly string[];
  requiresModel?: boolean;
};

const ROUTES: readonly RouteRule[] = [
  { method: "GET", path: /^agents$/ },
  { method: "POST", path: /^agents$/, requiresModel: true },
  { method: "GET", path: /^agents\/[^/]+$/ },
  { method: "GET", path: /^agents\/[^/]+\/versions\/\d+$/ },
  { method: "POST", path: /^agents\/[^/]+\/(?:run|improve)$/, requiresModel: true },
  { method: "GET", path: /^agents\/[^/]+\/(?:runs|fixes)$/ },
  {
    method: "GET",
    path: /^agents\/[^/]+\/compare$/,
    query: ["case_id"],
    requiredQuery: ["case_id"],
  },
  { method: "GET", path: /^agents\/[^/]+\/fixes\/\d+\/diff$/ },
  { method: "GET", path: /^jobs\/[^/]+$/ },
  { method: "GET", path: /^insights\/compare$/ },
  { method: "GET", path: /^insights\/[^/]+$/ },
  { method: "GET", path: /^(?:playbook|evaluators)$/ },
  { method: "GET", path: /^events$/, query: ["agent_id", "kind", "since"] },
];

export type AllowedRequest = {
  pathname: string;
  search: string;
  requiresModel: boolean;
};

/** Validate and canonicalize the browser-controlled portion of an upstream URL. */
export function allowRequest(
  method: string,
  segments: readonly string[],
  searchParams: URLSearchParams,
): AllowedRequest | null {
  if (segments.length === 0 || segments.length > 6) return null;
  if (segments.some((segment) => !SAFE_SEGMENT.test(segment) || segment === "." || segment === "..")) {
    return null;
  }

  const pathname = segments.join("/");
  const rule = ROUTES.find((candidate) => candidate.method === method && candidate.path.test(pathname));
  if (!rule) return null;

  const allowedQuery = new Set(rule.query ?? []);
  const seen = new Set<string>();
  for (const [key, value] of searchParams) {
    if (!allowedQuery.has(key) || seen.has(key) || value.length === 0 || value.length > 256) {
      return null;
    }
    if (/[\u0000-\u001f\u007f]/.test(value)) return null;
    seen.add(key);
  }
  if ((rule.requiredQuery ?? []).some((key) => !seen.has(key))) return null;

  return {
    pathname,
    search: searchParams.toString(),
    requiresModel: rule.requiresModel === true,
  };
}
