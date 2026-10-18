import type { Metadata } from "next";
import { cookies } from "next/headers";
import { Geist, Michroma } from "next/font/google";

import { ShellGate } from "@/components/layout/app-shell";
import { ThemeProvider } from "@/context/theme-context";
import { THEME_STORAGE_KEY, type ThemeMode } from "@/lib/theme";

import "./globals.css";

/* Functional UI face: the default for the whole interface. */
const geist = Geist({ variable: "--font-geist", subsets: ["latin"], display: "swap" });

/* Display face: identity, page titles and telemetry figures only. */
const michroma = Michroma({ variable: "--font-michroma", subsets: ["latin"], weight: "400", display: "swap" });

export const metadata: Metadata = {
  title: "Shilpa — AI CAD Studio",
  description: "Engineering CAD from requests and drawings, with validated geometry.",
  icons: { icon: "/brand/shilpa-mark.svg", apple: "/brand/shilpa-mark.svg" },
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const cookieStore = await cookies();
  const theme: ThemeMode = cookieStore.get(THEME_STORAGE_KEY)?.value === "dark" ? "dark" : "light";

  return (
    <html
      lang="en"
      data-theme={theme}
      style={{ colorScheme: theme }}
      suppressHydrationWarning
      className={`${geist.variable} ${michroma.variable} h-full antialiased`}
    >
      <body className="h-full overflow-hidden">
        <ThemeProvider initialTheme={theme}>
          <ShellGate>{children}</ShellGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
