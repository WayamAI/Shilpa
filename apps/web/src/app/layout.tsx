import type { Metadata } from "next";
import { Inter_Tight } from "next/font/google";

import { ShellGate } from "@/components/layout/app-shell";
import { ToastProvider } from "@/components/ui";

import "./globals.css";

/* The one UI face (Paper: Inter Tight, weights 400 and 600). SIL OFL 1.1. */
const interTight = Inter_Tight({ variable: "--font-inter-tight", subsets: ["latin"], weight: ["400", "600"], display: "swap" });

export const metadata: Metadata = {
  title: "Shilpa — AI CAD Studio",
  description: "Engineering CAD from requests and drawings, with validated geometry.",
  icons: { icon: "/brand/shilpa-mark-64.webp", apple: "/brand/shilpa-mark-128.webp" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${interTight.variable} h-full antialiased`}
    >
      <body className="h-full overflow-hidden">
        <ToastProvider>
          <ShellGate>{children}</ShellGate>
        </ToastProvider>
      </body>
    </html>
  );
}
