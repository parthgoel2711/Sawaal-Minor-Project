import { useState } from "react";
import { Loader2 } from "lucide-react";
import { api, errorMessage } from "../api";

export function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username.trim(), password);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit}>
        <img src="/favicon.svg" alt="" width={36} height={36} />
        <h1>Sign in to Sawaal</h1>
        <p className="muted">Your role decides what you can see and change.</p>
        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <button className="primary-btn" type="submit" disabled={busy || !username.trim() || !password}>
          {busy && <Loader2 size={14} className="spin" />} Sign in
        </button>
      </form>
    </main>
  );
}
