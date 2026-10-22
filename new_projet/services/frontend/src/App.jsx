import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api.js";

const euros = (value) =>
  Number(value).toLocaleString("fr-FR", { style: "currency", currency: "EUR" });

function Banner({ kind, children }) {
  const styles = {
    error: "bg-red-50 text-red-800 border-red-200",
    success: "bg-emerald-50 text-emerald-800 border-emerald-200",
  };
  return <p className={`rounded-md border px-3 py-2 text-sm ${styles[kind]}`}>{children}</p>;
}

function Card({ title, children }) {
  return (
    <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

const inputClass =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";
const buttonClass =
  "rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50";

function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await api.login(username, password);
      onLogin({ username, token: access_token });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="mb-1 text-2xl font-bold text-slate-900">AlphaPay</h1>
      <p className="mb-6 text-sm text-slate-500">Plateforme de paiement fictive — démonstrateur Resilience-Alpha</p>
      <form onSubmit={submit} className="space-y-3 rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <label className="block text-sm font-medium text-slate-700">
          Identifiant
          <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)}
                 autoComplete="username" required />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Mot de passe
          <input className={inputClass} type="password" value={password}
                 onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <Banner kind="error">{error}</Banner>}
        <button className={`${buttonClass} w-full`} disabled={busy}>Se connecter</button>
      </form>
    </div>
  );
}

function TransferForm({ accounts, onSubmit }) {
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!source && accounts.length) setSource(String(accounts[0].id));
  }, [accounts, source]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const tx = await onSubmit({
        source_account_id: Number(source),
        destination_account_id: Number(destination),
        amount,
      });
      setMessage({ kind: "success", text: `Virement n°${tx.id} de ${euros(tx.amount)} effectué.` });
      setAmount("");
    } catch (e) {
      setMessage({ kind: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-sm font-medium text-slate-700">
        Compte à débiter
        <select className={inputClass} value={source} onChange={(e) => setSource(e.target.value)}>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>n°{a.id} — {a.label}</option>
          ))}
        </select>
      </label>
      <label className="block text-sm font-medium text-slate-700">
        N° du compte destinataire
        <input className={inputClass} type="number" min="1" value={destination}
               onChange={(e) => setDestination(e.target.value)} required />
      </label>
      <label className="block text-sm font-medium text-slate-700">
        Montant (€)
        <input className={inputClass} type="number" min="0.01" max="10000" step="0.01" value={amount}
               onChange={(e) => setAmount(e.target.value)} required />
      </label>
      {message && <Banner kind={message.kind}>{message.text}</Banner>}
      <button className={buttonClass} disabled={busy || !accounts.length}>Envoyer</button>
    </form>
  );
}

function Home({ session, onLogout }) {
  const [accounts, setAccounts] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [acc, txs] = await Promise.all([api.accounts(session.token), api.transactions(session.token)]);
      setAccounts(acc);
      setTransactions(txs);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onLogout();
      else setError(e.message);
    }
  }, [session.token, onLogout]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function transfer(payload) {
    const tx = await api.transfer(session.token, payload);
    await refresh();
    return tx;
  }

  const own = new Set(accounts.map((a) => a.id));

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">AlphaPay</h1>
          <p className="text-sm text-slate-500">Connecté en tant que <strong>{session.username}</strong> — données fictives</p>
        </div>
        <button onClick={onLogout} className="text-sm text-slate-600 hover:text-slate-900">Se déconnecter</button>
      </header>

      {error && <div className="mb-4"><Banner kind="error">{error}</Banner></div>}

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Mes comptes">
          <ul className="divide-y divide-slate-100">
            {accounts.map((a) => (
              <li key={a.id} className="flex justify-between py-2 text-sm">
                <span>n°{a.id} — {a.label}</span>
                <span className="font-semibold tabular-nums">{euros(a.balance)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Nouveau virement">
          <TransferForm accounts={accounts} onSubmit={transfer} />
        </Card>
      </div>

      <div className="mt-6">
        <Card title="Dernières opérations">
          {transactions.length === 0 ? (
            <p className="text-sm text-slate-500">Aucune opération.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-500">
                  <tr><th className="py-1">N°</th><th>Date</th><th>De</th><th>Vers</th><th className="text-right">Montant</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {transactions.map((t) => {
                    const outgoing = own.has(t.source_account_id);
                    return (
                      <tr key={t.id}>
                        <td className="py-1">{t.id}</td>
                        <td>{new Date(t.created_at).toLocaleString("fr-FR")}</td>
                        <td>{t.source_account_id}</td>
                        <td>{t.destination_account_id}</td>
                        <td className={`text-right tabular-nums ${outgoing ? "text-red-700" : "text-emerald-700"}`}>
                          {outgoing ? "−" : "+"}{euros(t.amount)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(null);
  const logout = useCallback(() => setSession(null), []);
  return session ? <Home session={session} onLogout={logout} /> : <Login onLogin={setSession} />;
}
