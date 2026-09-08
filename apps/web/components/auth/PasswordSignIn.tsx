"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export function PasswordSignIn({ onForgot, onUseOtp }: { onForgot: () => void; onUseOtp: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await api<User>("/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username, password, otp }),
      });
      queryClient.setQueryData(["me"], user);
      const requested = new URLSearchParams(window.location.search).get("next") ?? "/";
      const destination = requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
      router.replace(destination);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="login-form-kicker">Drona Logitech</div>
      <h2>Welcome back</h2>
      <p>Sign in to your transport operations workspace.</p>
      {error && <div className="notice error">{error}</div>}
      <div className="field">
        <label htmlFor="username">Username</label>
        <input id="username" className="input" value={username} autoComplete="username"
          onChange={(event) => setUsername(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="password">Password</label>
        <input id="password" type="password" className="input" value={password} autoComplete="current-password"
          onChange={(event) => setPassword(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="otp">Authenticator code (when enabled)</label>
        <input id="otp" inputMode="numeric" maxLength={6} className="input" value={otp}
          autoComplete="one-time-code" onChange={(event) => setOtp(event.target.value)} />
      </div>
      <button className="button primary" disabled={busy}>
        {busy ? "Signing in…" : "Sign in securely"}
      </button>
      <button type="button" className="button" onClick={onUseOtp}>
        Sign in with a code instead
      </button>
      <button type="button" className="button" onClick={onForgot}>
        Forgot password?
      </button>
      <p style={{ fontSize: 11, marginTop: 18 }}>Need an account? Contact your administrator.</p>
    </form>
  );
}
