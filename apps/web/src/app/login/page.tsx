"use client";

import { Moon, SunMedium } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Logo } from "@/components/layout/logo";
import { HeroDrawing } from "@/components/studio/hero-drawing";
import { Button, Field, IconButton } from "@/components/ui/controls";
import { Select } from "@/components/ui/primitives";
import { useTheme } from "@/context/theme-context";
import { DEV_USERS, writeSession } from "@/lib/session";

/** Sign-in (Chronos layout). Local development uses seeded dev identities. */
export default function LoginPage() {
  const router = useRouter();
  const { isDark, toggleTheme } = useTheme();
  const [email, setEmail] = useState<string>(DEV_USERS[0].email);
  const [busy, setBusy] = useState(false);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    writeSession(email);
    router.replace("/projects");
  }

  const user = DEV_USERS.find((u) => u.email === email);

  return (
    <div className="flex h-full min-h-0 bg-page">
      <aside className="relative hidden min-w-0 flex-[1.4] overflow-hidden lg:block" style={{ background: "#101010" }}>
        <HeroDrawing className="absolute inset-0 size-full object-cover" />
        <div className="absolute inset-y-0 right-0 w-32 bg-gradient-to-r from-transparent to-page" />
        <div className="absolute inset-x-0 bottom-0 h-[42%] bg-gradient-to-t from-black/85 to-transparent" />
        <div className="absolute right-10 bottom-10 left-10 max-w-[36rem]">
          <p className="font-display text-display-2xl text-white sm:text-display-3xl">From request to solid.</p>
          <p className="mt-3 max-w-[44ch] text-body-md text-white/75">
            Describe a part or upload a drawing. Shilpa plans the features, builds the geometry and checks it against what you asked for.
          </p>
        </div>
      </aside>

      <section className="flex min-h-0 w-full shrink-0 flex-col border-muted bg-page lg:w-[min(28rem,42%)] lg:border-l">
        <div className="flex items-center justify-between px-8 pt-6">
          <Logo wordmark href={false} />
          <IconButton label={isDark ? "Switch to light" : "Switch to dark"} onClick={toggleTheme}>
            {isDark ? <SunMedium size={16} strokeWidth={1.75} aria-hidden /> : <Moon size={16} strokeWidth={1.75} aria-hidden />}
          </IconButton>
        </div>

        <div className="flex min-h-0 flex-1 flex-col justify-center px-8 py-10">
          <h1 className="font-display text-display-xl text-primary">Sign in</h1>
          <p className="mt-1.5 text-body-md text-tertiary">Local development uses seeded engineer identities.</p>

          <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4">
            <Field label="Engineer" hint={user ? user.role : undefined}>
              <Select
                name="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="h-11 w-full rounded-full border border-muted bg-action text-body-md text-primary outline-none focus-visible:border-default focus-visible:ring-2 focus-visible:ring-active"
              >
                {DEV_USERS.map((u) => (
                  <option key={u.email} value={u.email}>
                    {u.name} — {u.email}
                  </option>
                ))}
              </Select>
            </Field>
            <Button type="submit" variant="primary" disabled={busy} className="mt-1 h-11">
              {busy ? "Entering…" : "Enter studio"}
            </Button>
          </form>

          <p className="mt-6 text-body-sm text-quaternary">
            In Azure this page is replaced by Microsoft Entra ID sign-in. Generated models are geometry-validated, not approved for engineering release.
          </p>
        </div>
      </section>
    </div>
  );
}
