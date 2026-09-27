import type { Metadata } from "next";

import { AppShell } from "../components/AppShell";
import { AppProvider } from "../lib/store";
import "./globals.css";

export const metadata: Metadata = {
  title: "APEX — Multi-Agent Motorsport Safety Stress Tester",
  description:
    "Automated generation and surrogate-safety analysis of thousands of multi-driver " +
    "racing scenarios, searching for recurring safety-critical interactions.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AppProvider>
          <AppShell>{children}</AppShell>
        </AppProvider>
      </body>
    </html>
  );
}
