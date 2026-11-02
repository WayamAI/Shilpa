"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { MentionChip } from "@/components/compose/mention-chip";
import { Mark } from "@/components/layout/logo";
import { Badge, Button, Field, TextInput } from "@/components/ui";
import { DEV_USERS, writeSession } from "@/lib/session";

/**
 * Sign in (Paper · 00a Sign in). Left: statement, SH-AUTH-01 hero and an
 * example prompt. Right: work email, Continue, and Microsoft SSO (planned).
 * Locally only the seeded dev identities exist, so the email must be one.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string>(DEV_USERS[0].email);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const match = DEV_USERS.find((u) => u.email === email.trim().toLowerCase());
    if (!match) {
      setError(`No local account for that email. Use ${DEV_USERS.map((u) => u.email).join(", ")}.`);
      return;
    }
    setError(null);
    setBusy(true);
    writeSession(match.email);
    router.replace("/projects");
  }

  return (
    <div className="flex h-dvh min-h-0 overflow-y-auto bg-bg">
      <aside className="hidden w-[640px] shrink-0 flex-col justify-between gap-8 overflow-hidden border-r border-line bg-surface p-12 lg:flex">
        <Brand />
        {/* SH-AUTH-01. Decorative: the statement below carries the meaning. */}
        <picture className="block aspect-[543/340] w-full max-w-[543px] shrink overflow-hidden rounded-2xl">
          <source srcSet="/imagery/sh-auth-01-sign-in-hero-640.webp 640w, /imagery/sh-auth-01-sign-in-hero.webp 1240w" sizes="543px" type="image/webp" />
          <img src="/imagery/sh-auth-01-sign-in-hero.webp" alt="" width={543} height={340} className="size-full object-cover" draggable={false} />
        </picture>
        <div className="flex flex-col gap-5">
          <p className="text-display font-semibold text-ink">Build complex parts from the parts you already have.</p>
          <p className="text-lede text-body">
            Type @ to pick a part, a face or a set of holes. Shilpa shows how it read you before anything is built, then checks the geometry.
          </p>
          <ExamplePrompt />
        </div>
        <p className="text-xs text-muted-text">Runs on your machine. Outputs are geometry-validated, not reviewed for engineering release.</p>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        {/* Phone: SH-AUTH-02 band. [Assumption] a 16:9 crop of SH-AUTH-01 until its own recomposition exists. */}
        <div className="flex flex-col gap-4 px-4 pt-5 lg:hidden">
          <Brand />
          {/* eslint-disable-next-line @next/next/no-img-element -- decorative band */}
          <img
            src="/imagery/sh-auth-02-sign-in-band-640.webp"
            alt=""
            width={640}
            height={360}
            className="aspect-video w-full rounded-xl bg-surface object-cover"
            draggable={false}
          />
        </div>

        <div className="flex flex-1 items-start justify-center px-4 py-8 lg:items-center lg:py-12">
          <form onSubmit={onSubmit} noValidate className="flex w-full max-w-[380px] flex-col gap-4">
            <div className="flex flex-col gap-1">
              <h1 className="text-headline">Sign in</h1>
              <p className="text-md text-body">Use your work account.</p>
            </div>

            <Field label="Work email" error={error ?? undefined}>
              <TextInput
                size="lg"
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (error) setError(null);
                }}
                required
              />
            </Field>

            <Button type="submit" variant="primary" size="lg" loading={busy} icon={<ArrowRight size={14} strokeWidth={2.2} aria-hidden />} className="w-full">
              Continue
            </Button>

            <div className="flex items-center gap-2.5" aria-hidden>
              <span className="h-px flex-1 bg-line" />
              <span className="text-xs text-muted-text">or</span>
              <span className="h-px flex-1 bg-line" />
            </div>

            <Button size="lg" disabled className="w-full disabled:opacity-100" aria-describedby="sso-note">
              <MicrosoftMark />
              <span className="font-semibold text-ink">Sign in with Microsoft</span>
              <Badge tone="consent">Planned</Badge>
            </Button>

            <p id="sso-note" className="text-xs leading-[17px] text-muted-text">
              Today Shilpa uses local developer tokens. Workspace SSO arrives before client rollout.
            </p>
          </form>
        </div>

        <p className="px-4 pb-6 text-xs text-muted-text lg:hidden">Runs on your machine. Outputs are geometry-validated, not reviewed for engineering release.</p>
      </main>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <Mark size={32} />
      <span className="text-xl font-semibold text-ink">Shilpa</span>
      <span className="text-sm text-muted-text">by Wayam AI</span>
    </div>
  );
}

function ExamplePrompt() {
  return (
    <p className="flex flex-wrap items-center gap-1.5 rounded-lg border border-line bg-bg px-4 py-3.5 text-brand text-ink">
      put <MentionChip>ISO4032-M6</MentionChip> in every hole on <MentionChip>plate</MentionChip>
      <span className="text-sm text-muted-text">→ 4 nuts, 4 mates</span>
    </p>
  );
}

/** Microsoft's four-square mark, as drawn in Paper. */
function MicrosoftMark() {
  return (
    <span aria-hidden className="grid w-3.5 shrink-0 grid-cols-2 gap-px">
      <span className="size-1.5 bg-[#f25022]" />
      <span className="size-1.5 bg-[#7fba00]" />
      <span className="size-1.5 bg-[#00a4ef]" />
      <span className="size-1.5 bg-[#ffb900]" />
    </span>
  );
}
