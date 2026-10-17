// Reusable building blocks of the design system.

import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Urgency } from "../types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "danger" | "ghost";
const variants: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800 disabled:bg-brand-700/60",
  secondary: "bg-surface text-ink border border-line hover:bg-neutral-bg",
  danger: "bg-emergency-solid text-white hover:bg-emergency-fg",
  ghost: "text-ink-muted hover:bg-neutral-bg hover:text-ink",
};

export function Button({
  variant = "primary", loading = false, icon, children, className, disabled, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-70",
        variants[variant], className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- badges

type Tone = "emergency" | "urgent" | "routine" | "success" | "danger" | "neutral" | "info" | "brand";
const tones: Record<Tone, string> = {
  emergency: "bg-emergency-bg text-emergency-fg",
  urgent: "bg-urgent-bg text-urgent-fg",
  routine: "bg-routine-bg text-routine-fg",
  success: "bg-success-bg text-success-fg",
  danger: "bg-danger-bg text-danger-fg",
  neutral: "bg-neutral-bg text-neutral-fg",
  info: "bg-info-bg text-info-fg",
  brand: "bg-brand-100 text-brand-900",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap", tones[tone], className)}>
      {children}
    </span>
  );
}

export function UrgencyBadge({ urgency }: { urgency: Urgency }) {
  return (
    <Badge tone={urgency}>
      {urgency === "emergency" && <AlertTriangle className="size-3" aria-hidden />}
      {urgency.charAt(0).toUpperCase() + urgency.slice(1)}
    </Badge>
  );
}

const ACTION_TONES: Record<string, Tone> = {
  escalate_emergency: "emergency",
  route_to_clinician: "urgent",
  flag_suspicious_instruction: "danger",
  decline_disclosure: "danger",
  request_verification: "info",
  prepare_refill_for_approval: "success",
  book_appointment: "success",
  reschedule_appointment: "success",
  cancel_appointment: "success",
};

export function humanize(code: string): string {
  return code.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function ActionChip({ action }: { action: string }) {
  return <Badge tone={ACTION_TONES[action] ?? "neutral"}>{humanize(action)}</Badge>;
}

export function QueueChip({ queue }: { queue: string }) {
  return <Badge tone={queue === "clinician_urgent" ? "emergency" : "brand"}>{humanize(queue)}</Badge>;
}

// ---------------------------------------------------------------- layout pieces

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {actions}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "bad" | "neutral" }) {
  return (
    <div className="card p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{label}</p>
      <p className={cx("mt-1 text-2xl font-bold",
        tone === "good" && "text-success-fg", tone === "bad" && "text-danger-fg")}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-subtle">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- states

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-ink-muted">
      <Loader2 className="size-5 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <div className="text-ink-subtle">{icon ?? <Inbox className="size-8" aria-hidden />}</div>
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-ink-muted">{children}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-xl border border-danger-bg bg-danger-bg/40 p-4 text-sm text-danger-fg sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>{message}</span>
      </div>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry} icon={<RefreshCw className="size-4" aria-hidden />}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "n/a" : `${(x * 100).toFixed(1)}%`;
}
