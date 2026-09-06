import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: { default: "Drona Logitech", template: "%s · Drona Logitech" },
  description: "Drona Logitech transport deployment, approval and vendor payment operations",
  applicationName: "Drona Logitech",
  icons: { icon: "/drona-logo.png" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
