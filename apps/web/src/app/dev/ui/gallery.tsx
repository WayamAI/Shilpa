"use client";

import { ArrowRight, Download, LogOut, MoreHorizontal, Settings, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Dot,
  Drawer,
  EmptyState,
  Field,
  IconButton,
  Menu,
  NumberInput,
  Popover,
  Progress,
  Radio,
  Segmented,
  Select,
  Skeleton,
  Spinner,
  Tabs,
  TextInput,
  Textarea,
  Tooltip,
  useToast,
} from "@/components/ui";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3.5">
      <h2 className="text-lg">{title}</h2>
      {children}
    </section>
  );
}

export function Gallery() {
  const toast = useToast();
  const [tab, setTab] = useState<"features" | "parameters" | "checks" | "versions" | "exports">("features");
  const [mode, setMode] = useState<"shaded" | "edges" | "ports">("shaded");
  const [dialog, setDialog] = useState(false);
  const [drawer, setDrawer] = useState(false);

  const menu = (placement: "bottom-start" | "bottom-end") => (
    <Menu
      label="Part actions"
      placement={placement}
      items={[
        { id: "open", label: "Open in composer", icon: <ArrowRight size={14} />, onSelect: () => toast({ title: "Opened" }) },
        { id: "export", label: "Export STEP", icon: <Download size={14} />, detail: "⌘E", onSelect: () => toast({ title: "Export queued", tone: "pass" }) },
        { id: "settings", label: "Settings", icon: <Settings size={14} />, disabled: true, onSelect: () => {} },
        { id: "deprecate", label: "Deprecate", icon: <Trash2 size={14} />, danger: true, onSelect: () => setDialog(true) },
      ]}
      trigger={(p) => (
        <IconButton {...p} label="More actions">
          <MoreHorizontal size={16} aria-hidden />
        </IconButton>
      )}
    />
  );

  return (
    <div className="min-h-0 flex-1 overflow-auto bg-bg">
      <div className="mx-auto flex max-w-[960px] flex-col gap-10 px-4 py-8 sm:px-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl">Primitives</h1>
            <p className="mt-1 text-prose text-body">Every state, against Paper · Foundations. Development only.</p>
          </div>
          {menu("bottom-end")}
        </header>

        <Section title="Buttons">
          <div className="flex flex-wrap items-center gap-2.5">
            <Button variant="primary" icon={<ArrowRight size={14} strokeWidth={2.2} aria-hidden />}>
              Apply step
            </Button>
            <Button>Secondary</Button>
            <Button variant="dark">Card action</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Deprecate</Button>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button variant="primary" loading>
              Applying
            </Button>
            <Button variant="primary" disabled>
              Disabled
            </Button>
            <Button disabled>Disabled</Button>
            <Button size="sm" variant="primary">
              Small
            </Button>
            <Button size="sm">Small</Button>
            <IconButton label="Sign out">
              <LogOut size={16} aria-hidden />
            </IconButton>
            <IconButton label="Shaded view" pressed>
              <Settings size={16} aria-hidden />
            </IconButton>
          </div>
        </Section>

        <Section title="Badges">
          <div className="flex flex-wrap gap-2">
            <Badge tone="basic">Basic</Badge>
            <Badge tone="complex">Complex</Badge>
            <Badge>Catalog</Badge>
            <Badge>Imported · STEP</Badge>
            <Badge>Native</Badge>
            <Badge tone="pass">Pass</Badge>
            <Badge tone="fail">Fail</Badge>
            <Badge tone="consent">assumed</Badge>
            <Badge tone="ai">Clarification</Badge>
            <Badge tone="consent">Planned</Badge>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="flex items-center gap-1.5 text-xs text-ink">
              <Dot tone="pass" /> Kernel · build123d 0.13 local
            </span>
            <span className="flex items-center gap-1.5 text-xs text-muted-text">
              <Dot /> FreeCAD adapter · not installed
            </span>
          </div>
        </Section>

        <Section title="Fields">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Part name" hint="Shown in the library and the @ picker.">
              <TextInput placeholder="bracket-l-80" />
            </Field>
            <Field label="Offset" error="10 m is 10000 mm. Did you mean 10 mm?">
              <TextInput defaultValue="10 m" />
            </Field>
            <Field label="Source">
              <Select defaultValue="native">
                <option value="native">Native</option>
                <option value="catalog">Catalog</option>
                <option value="imported">Imported</option>
              </Select>
            </Field>
            <Field label="Disabled">
              <TextInput disabled defaultValue="Read only for viewers" />
            </Field>
            <Field label="Prompt" className="sm:col-span-2">
              <Textarea placeholder="insert @ISO4032-M6 into every hole on @bracket" />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-6">
            <NumberInput defaultValue={6.4} aria-label="Diameter" />
            <Checkbox label="Pin child versions" detail="Rebuilds use the pinned version." defaultChecked />
            <Checkbox label="Disabled" disabled />
            <div role="radiogroup" aria-label="Units" className="flex gap-4">
              <Radio name="units" label="mm" defaultChecked />
              <Radio name="units" label="in" />
            </div>
          </div>
        </Section>

        <Section title="Tabs">
          <Card>
            <Tabs
              label="Inspector"
              value={tab}
              onChange={setTab}
              tabs={[
                { id: "features", label: "Features", count: 14 },
                { id: "parameters", label: "Parameters" },
                { id: "checks", label: "Checks" },
                { id: "versions", label: "Versions" },
                { id: "exports", label: "Exports" },
              ]}
            />
            <p className="p-5 text-sm text-body">Panel: {tab}</p>
          </Card>
          <Segmented
            label="Viewport mode"
            value={mode}
            onChange={setMode}
            options={[
              { id: "shaded", label: "Shaded" },
              { id: "edges", label: "Edges" },
              { id: "ports", label: "Ports" },
            ]}
          />
        </Section>

        <Section title="Overlays">
          <div className="flex flex-wrap items-center gap-2.5">
            <Popover label="Units" trigger={(p) => <Button {...p}>Popover</Button>}>
              <p className="w-[260px] text-prose text-body">Lengths are millimetres. 10 m is read as 10000 mm and flagged as a likely typo.</p>
            </Popover>
            {menu("bottom-start")}
            <Tooltip content="Fit the model to the viewport">
              <IconButton label="Fit">
                <ArrowRight size={16} aria-hidden />
              </IconButton>
            </Tooltip>
            <Button onClick={() => setDialog(true)}>Dialog</Button>
            <Button onClick={() => setDrawer(true)}>Drawer</Button>
            <Button onClick={() => toast({ title: "Step 4 applied", detail: "v4 · 6 checks passed", tone: "pass" })}>Toast</Button>
            <Button
              onClick={() =>
                toast({ title: "Build failed", detail: "Solver: @lid fixed twice", tone: "fail", action: { label: "Open step 6", onClick: () => {} } })
              }
            >
              Toast with action
            </Button>
          </div>
        </Section>

        <Section title="Loading">
          <div className="flex items-center gap-3 text-body">
            <Spinner label="Loading" /> <span className="text-xs">Building v4 · solve 2 of 3</span>
          </div>
          <Progress value={62} label="Build progress" />
          <div className="grid grid-cols-3 gap-3.5">
            {[70, 60, 75].map((w) => (
              <Card key={w} className="h-[140px]">
                <div className="flex-1 bg-surface" />
                <div className="flex flex-col gap-1.5 p-2.5">
                  <Skeleton className="h-3" />
                  <Skeleton className="h-2.5 w-2/5" />
                </div>
              </Card>
            ))}
          </div>
        </Section>

        <Section title="Empty state">
          <Card className="h-[360px]">
            <EmptyState
              title="Your library is empty"
              detail="Import the STEP files you already have, or start from about 100 catalog parts: fasteners, bearings, gears, rails."
              actions={
                <>
                  <Button variant="primary" icon={<Download size={14} strokeWidth={2} aria-hidden />}>
                    Import parts
                  </Button>
                  <Button>Browse catalog</Button>
                </>
              }
            />
          </Card>
        </Section>
      </div>

      {dialog ? (
        <Dialog
          title="Deprecate bracket-l-80?"
          description="It is used in 2 complex parts. They keep their pinned version and still rebuild. It disappears from the @ picker for new steps."
          onClose={() => setDialog(false)}
          actions={
            <>
              <Button onClick={() => setDialog(false)}>Cancel</Button>
              <Button variant="danger" onClick={() => setDialog(false)}>
                Deprecate
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-1.5 rounded-md bg-surface px-3 py-2.5 text-sm text-ink">
            <span>motor-mount-assy · pinned v3</span>
            <span>conveyor-idler-assy · pinned v2</span>
          </div>
        </Dialog>
      ) : null}

      {drawer ? (
        <Drawer label="Navigation" side="left" onClose={() => setDrawer(false)}>
          <div className="flex items-center justify-between border-b border-line p-3">
            <span className="text-brand font-semibold text-ink">Shilpa</span>
            <IconButton label="Close navigation" onClick={() => setDrawer(false)}>
              <ArrowRight size={16} aria-hidden />
            </IconButton>
          </div>
          <p className="p-4 text-sm text-body">Drawer content.</p>
        </Drawer>
      ) : null}
    </div>
  );
}
