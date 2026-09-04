"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { GlobalSearch } from "@/components/GlobalSearch";
import { BrandLogo } from "@/components/BrandLogo";

const groups = [
  { label: "Operations", links: [["Dashboard", "/", "◫"], ["Indent register", "/indents", "▦"], ["Trip register", "/trips", "↗"], ["New trip", "/trips/new", "+"], ["Vendors", "/vendors", "◇"], ["Fleet & drivers", "/fleet", "▱"]] },
  { label: "Approvals", links: [["Approval inbox", "/approvals", "✓"], ["Build approval", "/approvals/new", "+"]] },
  { label: "Finance", links: [["Pending payments", "/finance", "₹"], ["Payment register", "/payments", "▤"], ["Vendor ledger", "/ledgers/vendor", "≋"], ["TDS register", "/tds", "%"]] },
  { label: "Control", links: [["MIS records", "/mis", "▦"], ["Reports & exports", "/reports", "▥"], ["Notifications", "/notifications", "◉"], ["Excel import", "/imports", "⇧"], ["Integrations", "/integrations", "◎"], ["Settings & matrix", "/settings", "⚙"]] },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const loginPage = pathname === "/login";
  const [logoutError, setLogoutError] = useState("");
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/"), enabled: !loginPage, retry: false });

  useEffect(() => {
    if (!loginPage && me.error instanceof ApiError && me.error.status === 403) {
      const target = `${window.location.pathname}${window.location.search}`;
      router.replace(`/login?next=${encodeURIComponent(target)}`);
    }
  }, [loginPage, me.error, router]);

  if (loginPage) return children;
  if (me.isPending) return <div className="empty">Loading secure workspace…</div>;

  const logout = async () => {
    setLogoutError("");
    try {
      await api("/auth/logout/", { method: "POST" });
      router.replace("/login");
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : "Sign out failed. Please try again.");
    }
  };
  const initials = `${me.data?.first_name?.[0] ?? ""}${me.data?.last_name?.[0] ?? ""}` || me.data?.username?.slice(0, 2).toUpperCase();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand brand-lockup"><BrandLogo priority /><small>Transport operations control</small></div>
        {groups.map((group) => <div key={group.label}><div className="nav-label">{group.label}</div>{group.links.map(([label, href, icon]) => <Link className={`nav-link ${pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)) ? "active" : ""}`} href={href} key={href}><span className="nav-icon">{icon}</span>{label}</Link>)}</div>)}
      </aside>
      <main className="main">
        <header className="topbar"><GlobalSearch /><div className="user-pill"><div className="avatar">{initials}</div><div><strong>{me.data?.first_name || me.data?.username}</strong><br /><small>{me.data?.role}</small></div><button className="button small" onClick={logout}>Sign out</button></div></header>
        <div className="content">{logoutError && <div className="notice error" role="alert">{logoutError}</div>}{children}</div>
      </main>
      <nav className="mobile-nav"><Link href="/">Home</Link><Link href="/trips">Trips</Link><Link href="/approvals">Approvals</Link><Link href="/finance">Finance</Link></nav>
    </div>
  );
}
