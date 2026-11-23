import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { useSession } from "../session";

export function AuthDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { signIn } = useSession();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await api.login(username.trim(), password)
          : await api.register(username.trim(), password, displayName.trim());
      signIn({ token: res.token, username: res.user.username, displayName: res.user.display_name });
      setPassword("");
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign you in. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={ref} className="auth-dialog" onClose={onClose} aria-labelledby="auth-title">
      <form onSubmit={submit}>
        <div className="auth-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
            Sign in
          </button>
          <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>
            Create account
          </button>
        </div>
        <h2 id="auth-title" className="sr-only">
          {mode === "login" ? "Sign in" : "Create account"}
        </h2>
        <p className="muted small-text">
          Your account keeps your orders, saved size and city, and past chats in one place.
        </p>
        {mode === "register" && (
          <label>
            Your name
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={100} autoComplete="name" />
          </label>
        )}
        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            minLength={mode === "register" ? 3 : 1}
            maxLength={32}
            pattern={mode === "register" ? "[a-zA-Z0-9_.\\-]+" : undefined}
            autoComplete="username"
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 6 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </div>
        {mode === "login" && <p className="muted small-text">Demo accounts: ali / demo1234 and sara / demo1234</p>}
      </form>
    </dialog>
  );
}
