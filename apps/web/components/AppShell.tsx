"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { GlobalSearch } from "@/components/GlobalSearch";
import { BrandLogo } from "@/components/BrandLogo";

type NavLink = { label: string; href: string; icon: string; roles?: string[] };

const MOBILE_LABELS: Record<string, string> = { "/": "Home", "/trips": "Trips", "/approvals": "Approvals", "/finance": "Finance" };

const INTERNAL = ["OPERATIONS", "APPROVER", "FINANCE", "MANAGEMENT", "ADMIN"];
const FINANCE_VIEW = ["FINANCE", "MANAGEMENT", "ADMIN"];
const OPERATIONS_WRITE = ["OPERATIONS", "ADMIN"];

// Mirrors accounts/permissions.py ROLE_CAPABILITIES so each role only sees pages it can use.
const groups: Array<{ label: string; links: NavLink[] }> = [
  { label: "Operations", links: [
    { label: "Dashboard", href: "/", icon: "◫" },
    { label: "Indent register", href: "/indents", icon: "▦", roles: INTERNAL },
    { label: "Trip register", href: "/trips", icon: "↗" },
    { label: "New trip", href: "/trips/new", icon: "+", roles: OPERATIONS_WRITE },
    { label: "Vendors", href: "/vendors", icon: "◇", roles: INTERNAL },
    { label: "Fleet & drivers", href: "/fleet", icon: "▱" },
  ] },
  { label: "Approvals", links: [
    { label: "Approval inbox", href: "/approvals", icon: "✓" },
    { label: "Build approval", href: "/approvals/new", icon: "+", roles: OPERATIONS_WRITE },
  ] },
  { label: "Finance", links: [
    { label: "Pending payments", href: "/finance", icon: "₹", roles: ["OPERATIONS", ...FINANCE_VIEW] },
    { label: "Payment register", href: "/payments", icon: "▤", roles: ["OPERATIONS", "TRANSPORTER", ...FINANCE_VIEW] },
    { label: "Vendor ledger", href: "/ledgers/vendor", icon: "≋" },
    { label: "TDS register", href: "/tds", icon: "%", roles: FINANCE_VIEW },
  ] },
  { label: "Control", links: [
    { label: "MIS records", href: "/mis", icon: "▦" },
    { label: "Reports & exports", href: "/reports", icon: "▥", roles: FINANCE_VIEW },
    { label: "Notifications", href: "/notifications", icon: "◉" },
    { label: "Excel import", href: "/imports", icon: "⇧", roles: OPERATIONS_WRITE },
    { label: "Integrations", href: "/integrations", icon: "◎", roles: ["ADMIN"] },
    { label: "Settings & matrix", href: "/settings", icon: "⚙" },
  ] },
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
  const role = me.data?.role ?? "";
  const visibleGroups = groups
    .map((group) => ({ ...group, links: group.links.filter((link) => !link.roles || link.roles.includes(role)) }))
    .filter((group) => group.links.length > 0);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand brand-lockup"><BrandLogo priority /><small>Transport operations control</small></div>
        {visibleGroups.map((group) => <div key={group.label}><div className="nav-label">{group.label}</div>{group.links.map(({ label, href, icon }) => <Link className={`nav-link ${pathname === href || (href !== "/" && pathname.startsWith(`${href}/`)) ? "active" : ""}`} href={href} key={href}><span className="nav-icon">{icon}</span>{label}</Link>)}</div>)}
      </aside>
      <main className="main">
        <header className="topbar"><GlobalSearch /><div className="user-pill"><div className="avatar">{initials}</div><div><strong>{me.data?.first_name || me.data?.username}</strong><br /><small>{me.data?.role}</small></div><button className="button small" onClick={logout}>Sign out</button></div></header>
        <div className="content">{logoutError && <div className="notice error" role="alert">{logoutError}</div>}{children}</div>
      </main>
      <nav className="mobile-nav">{visibleGroups.flatMap((group) => group.links).filter((link) => link.href in MOBILE_LABELS).map((link) => <Link href={link.href} key={link.href}>{MOBILE_LABELS[link.href]}</Link>)}</nav>
    </div>
  );
}
