// Client HTTP. Le jeton reste en mémoire (pas de localStorage) : il disparaît à la fermeture de l'onglet.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function describe(detail, status) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(" ; ");
  return `erreur HTTP ${status}`;
}

async function request(path, { token, method = "GET", body, headers = {} } = {}) {
  const allHeaders = { "Content-Type": "application/json", ...headers };
  if (token) allHeaders.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: allHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "plateforme injoignable");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, describe(data.detail, response.status));
  return data;
}

export const api = {
  login: (username, password) =>
    request("/api/auth/login", { method: "POST", body: { username, password } }),
  accounts: (token) => request("/api/pay/accounts", { token }),
  transactions: (token) => request("/api/pay/transactions", { token }),
  transfer: (token, transfer) =>
    request("/api/pay/transactions", {
      token,
      method: "POST",
      body: transfer,
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
};
