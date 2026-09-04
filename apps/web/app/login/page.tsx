"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { BrandLogo } from "@/components/BrandLogo";

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("operations");
  const [password, setPassword] = useState("ChangeMe123!");
  const [otp, setOtp] = useState("");
  const [resetMode, setResetMode] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetCredentials, setResetCredentials] = useState({ uid: "", token: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("reset_uid") && params.get("reset_token")) {
      queueMicrotask(() => {
        setResetCredentials({ uid: params.get("reset_uid")!, token: params.get("reset_token")! });
        setResetMode(true);
        setPassword("");
      });
    }
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const user = await api<User>("/auth/login/", { method: "POST", body: JSON.stringify({ username, password, otp }) });
      queryClient.setQueryData(["me"], user);
      const requested = new URLSearchParams(window.location.search).get("next") ?? "/";
      const destination = requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
      router.replace(destination);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally { setBusy(false); }
  };

  const requestReset = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); try { const result = await api<{ status: string }>("/auth/password/reset/", { method: "POST", body: JSON.stringify({ email: resetEmail }) }); setError(result.status); } catch (reason) { setError(reason instanceof Error ? reason.message : "Reset request failed"); } finally { setBusy(false); } };
  const confirmReset = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); try { await api("/auth/password/reset/confirm/", { method: "POST", body: JSON.stringify({ ...resetCredentials, new_password: password }) }); window.history.replaceState({}, "", "/login"); setResetCredentials({ uid: "", token: "" }); setResetMode(false); setError("Password reset. You can now sign in."); } catch (reason) { setError(reason instanceof Error ? reason.message : "Password reset failed"); } finally { setBusy(false); } };

  return <div className="login-page">
    <section className="login-visual">
      <div className="login-brand"><BrandLogo priority /><span>Transport operations platform</span></div>
      <div><div className="eyebrow login-eyebrow">Operations command</div><h1>Every trip, approval and payment—traceable.</h1><p>Coordinate deployments, approve transporter advances, allocate payments trip by trip, and keep the complete audit trail in one controlled workspace.</p></div>
      <small className="login-footnote">Secure role-based access · INR financial controls · Asia/Kolkata</small>
    </section>
    <section className="login-form-wrap">{resetMode ? <form className="login-form" onSubmit={resetCredentials.token ? confirmReset : requestReset}><div className="login-form-kicker">Drona Logitech</div><h2>Reset password</h2><p>{resetCredentials.token ? "Choose a strong replacement password." : "Enter the email address on your account."}</p>{error && <div className="notice">{error}</div>}{resetCredentials.token ? <div className="field"><label>New password</label><input required minLength={12} type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} /></div> : <div className="field"><label>Email</label><input required type="email" className="input" value={resetEmail} onChange={(e) => setResetEmail(e.target.value)} /></div>}<button className="button primary" disabled={busy}>{busy ? "Working…" : resetCredentials.token ? "Reset password" : "Send reset link"}</button><button type="button" className="button" onClick={() => setResetMode(false)}>Back to sign in</button></form> : <form className="login-form" onSubmit={submit}><div className="login-form-kicker">Drona Logitech</div><h2>Welcome back</h2><p>Sign in to your transport operations workspace.</p>{error && <div className="notice error">{error}</div>}<div className="field"><label htmlFor="username">Username</label><input id="username" className="input" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></div><div className="field"><label htmlFor="password">Password</label><input id="password" type="password" className="input" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></div><div className="field"><label htmlFor="otp">Authenticator code (when enabled)</label><input id="otp" inputMode="numeric" maxLength={6} className="input" value={otp} onChange={(event) => setOtp(event.target.value)} autoComplete="one-time-code" /></div><button className="button primary" disabled={busy}>{busy ? "Signing in…" : "Sign in securely"}</button><button type="button" className="button" onClick={() => setResetMode(true)}>Forgot password?</button><p style={{ fontSize: 11, marginTop: 18 }}>Demo roles use the password <code>ChangeMe123!</code>. Change it before shared deployment.</p></form>}</section>
  </div>;
}
