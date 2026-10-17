import { CalendarDays, ClipboardList, Gauge, Inbox, Menu, MessageSquarePlus, Settings2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import type { Health } from "../types";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "Inbox", icon: Inbox, end: true },
  { to: "/new", label: "New message", icon: MessageSquarePlus },
  { to: "/queues", label: "Staff queues", icon: ClipboardList },
  { to: "/schedule", label: "Schedule", icon: CalendarDays },
  { to: "/evaluation", label: "Evaluation", icon: Gauge },
  { to: "/system", label: "System", icon: Settings2 },
];

function AiStatus({ health, error }: { health: Health | null; error: boolean }) {
  if (error) return <span className="text-xs font-medium text-danger-fg">API unreachable</span>;
  if (!health) return <span className="text-xs text-ink-subtle">Connecting…</span>;
  const ok = health.ai.configured;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-muted">
      <span className={cx("size-2 rounded-full", ok ? "bg-success-fg" : "bg-urgent-fg")} aria-hidden />
      {ok ? `AI: ${health.ai.provider}` : "AI not configured"}
    </span>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    let alive = true;
    api.health().then((h) => alive && (setHealth(h), setHealthError(false))).catch(() => alive && setHealthError(true));
    return () => { alive = false; };
  }, []);

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-1 p-3">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}
          className={({ isActive }) => cx(
            "flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
            isActive ? "bg-brand-50 text-brand-800" : "text-ink-muted hover:bg-neutral-bg hover:text-ink")}>
          <Icon className="size-4" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );

  const brand = (
    <div className="flex items-center gap-2">
      <img src="/favicon.svg" alt="" className="size-7" />
      <div className="leading-tight">
        <p className="text-sm font-bold text-ink">Edvak Forge</p>
        <p className="text-xs text-ink-subtle">Maplewood Family Clinic</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-surface lg:flex">
        <div className="border-b border-line px-4 py-4">{brand}</div>
        <div className="flex-1 overflow-y-auto">{nav}</div>
        <div className="border-t border-line px-4 py-3">
          <AiStatus health={health} error={healthError} />
          {health && <p className="mt-1 text-xs text-ink-subtle">Clinic date: {health.today}</p>}
        </div>
      </aside>

      {/* Mobile top bar and drawer */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface px-4 py-3 lg:hidden">
        {brand}
        <div className="flex items-center gap-3">
          <AiStatus health={health} error={healthError} />
          <button aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open} aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)} className="rounded-lg p-2 text-ink hover:bg-neutral-bg">
            {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
          </button>
        </div>
      </header>
      {open && (
        <div id="mobile-nav" className="fixed inset-x-0 top-[61px] z-20 border-b border-line bg-surface shadow-lg lg:hidden">
          {nav}
        </div>
      )}

      <main id="main" className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {health && !health.ai.configured && (
          <div role="status" className="mb-4 rounded-lg border border-urgent-bg bg-urgent-bg/50 px-4 py-3 text-sm text-urgent-fg">
            The AI provider is not configured ({health.ai.error}). Emergencies are still detected and escalated, and
            everything else is handed to staff. Add a key on the server to enable full processing.
          </div>
        )}
        <Outlet context={{ health }} />
      </main>
    </div>
  );
}
