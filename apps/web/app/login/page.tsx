"use client";

import { useState } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import { ForgotPassword } from "@/components/auth/ForgotPassword";
import { OtpSignIn } from "@/components/auth/OtpSignIn";
import { PasswordSignIn } from "@/components/auth/PasswordSignIn";

type Mode = "password" | "otp" | "forgot";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("password");

  return (
    <div className="login-page">
      <section className="login-visual">
        <div className="login-brand">
          <BrandLogo priority />
          <span>Transport operations platform</span>
        </div>
        <div>
          <div className="eyebrow login-eyebrow">Operations command</div>
          <h1>Every trip, approval and payment—traceable.</h1>
          <p>
            Coordinate deployments, approve transporter advances, allocate payments trip by trip, and keep the complete
            audit trail in one controlled workspace.
          </p>
        </div>
        <small className="login-footnote">Secure role-based access · INR financial controls · Asia/Kolkata</small>
      </section>
      <section className="login-form-wrap">
        {mode === "password" && <PasswordSignIn onForgot={() => setMode("forgot")} onUseOtp={() => setMode("otp")} />}
        {mode === "otp" && <OtpSignIn onBack={() => setMode("password")} />}
        {mode === "forgot" && <ForgotPassword onBack={() => setMode("password")} />}
      </section>
    </div>
  );
}
