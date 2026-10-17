import { ArrowLeft, Mail, MessageSquare, Monitor, Play, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ConfirmDialog, useToast } from "../components/feedback";
import { MessageDetail, formatTime } from "../components/MessageDetail";
import { Badge, Button, EmptyState, ErrorState, PageHeader, Spinner, UrgencyBadge, cx } from "../components/ui";
import { errorMessage, useApi } from "../hooks";
import type { InboxEntry, Job, ProcessedItem } from "../types";

type SetName = "sample" | "extra" | "custom";
const SETS: { id: SetName; label: string; hint: string }[] = [
  { id: "sample", label: "Sample (40)", hint: "The 40 messages from the brief" },
  { id: "extra", label: "Unseen (14)", hint: "New messages written to test generalisation" },
  { id: "custom", label: "Your messages", hint: "Messages you submitted on the New message page" },
];
const CHANNEL_ICON = { sms: MessageSquare, email: Mail, portal: Monitor } as Record<string, typeof Mail>;

export function InboxPage() {
  const [set, setSet] = useState<SetName>("sample");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProcessedItem | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [urgency, setUrgency] = useState("all");
  const [job, setJob] = useState<Job | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const notify = useToast();

  const inbox = useApi<InboxEntry[]>(async () => {
    if (set === "custom") {
      const { items } = await api.results();
      return items.filter((i) => i.message.id.startsWith("C")).map((i) => ({ ...i.message, processed: i.result }));
    }
    return (await api.inbox(set)).messages;
  }, [set]);

  // Load the detail of the selected message.
  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    const entry = inbox.data?.find((m) => m.id === selected);
    if (!selected || !entry?.processed) return;
    api.result(selected).then(setDetail).catch((e) => setDetailError(errorMessage(e)));
  }, [selected, inbox.data]);

  // Poll a running batch job.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const t = setInterval(async () => {
      try {
        const next = await api.run(job.id);
        setJob(next);
        if (next.status !== "running") {
          await inbox.reload(true);
          if (next.status === "finished") notify("success", `Processed ${next.done} message${next.done === 1 ? "" : "s"}.`);
          else notify("error", `Run failed: ${next.error}`);
        } else if (next.done !== job.done) {
          void inbox.reload(true);
        }
      } catch (e) {
        notify("error", errorMessage(e));
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job, inbox, notify]);

  const running = job?.status === "running";

  async function start(ids?: string[]) {
    if (set === "custom") return;
    try {
      setJob(await api.startRun(set, ids, !ids));
    } catch (e) {
      notify("error", errorMessage(e));
    }
  }

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (inbox.data ?? []).filter((m) =>
      (urgency === "all" || (urgency === "pending" ? !m.processed : m.processed?.urgency === urgency)) &&
      (!q || `${m.id} ${m.from_name} ${m.body}`.toLowerCase().includes(q)));
  }, [inbox.data, query, urgency]);

  const selectedEntry = inbox.data?.find((m) => m.id === selected) ?? null;
  const processedCount = (inbox.data ?? []).filter((m) => m.processed).length;

  return (
    <>
      <PageHeader
        title="Inbox"
        description="Incoming patient messages. Process them with the agent, then open one to see what it did and why."
        actions={set !== "custom" && (
          <Button onClick={() => setConfirmAll(true)} loading={running} icon={<Play className="size-4" aria-hidden />}>
            {running ? `Processing ${job!.done}/${job!.total}` : "Process all"}
          </Button>
        )}
      />

      <div role="tablist" aria-label="Message set" className="mb-4 flex flex-wrap gap-2">
        {SETS.map((s) => (
          <button key={s.id} role="tab" aria-selected={set === s.id} title={s.hint}
            onClick={() => { setSet(s.id); setSelected(null); }}
            className={cx("min-h-10 rounded-lg px-3 py-2 text-sm font-medium",
              set === s.id ? "bg-brand-700 text-white" : "bg-surface border border-line text-ink-muted hover:text-ink")}>
            {s.label}
          </button>
        ))}
      </div>

      {running && (
        <div className="mb-4" aria-live="polite">
          <div className="h-2 overflow-hidden rounded-full bg-neutral-bg">
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${(job!.done / job!.total) * 100}%` }} />
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            Working on {job!.current ?? "…"}. On the free AI tier this takes about 10 seconds per message, with short pauses to stay within rate limits.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section aria-label="Messages" className={cx("card flex min-h-0 flex-col lg:self-start", selected && "hidden lg:flex")}>
          <div className="flex flex-col gap-2 border-b border-line p-3 sm:flex-row">
            <label className="relative flex-1">
              <span className="sr-only">Search messages</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
              <input className="input pl-9" placeholder="Search name, text or id" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <label>
              <span className="sr-only">Filter by urgency</span>
              <select className="input sm:w-36" value={urgency} onChange={(e) => setUrgency(e.target.value)}>
                <option value="all">All</option>
                <option value="emergency">Emergency</option>
                <option value="urgent">Urgent</option>
                <option value="routine">Routine</option>
                <option value="pending">Not processed</option>
              </select>
            </label>
          </div>
          <p className="border-b border-line px-3 py-2 text-xs text-ink-subtle">{processedCount} of {inbox.data?.length ?? 0} processed</p>

          {inbox.loading && <Spinner />}
          {inbox.error && <div className="p-3"><ErrorState message={inbox.error} onRetry={() => inbox.reload()} /></div>}
          {!inbox.loading && !inbox.error && rows.length === 0 && (
            <EmptyState title={set === "custom" ? "No messages yet" : "No matching messages"}>
              {set === "custom" ? "Submit one on the New message page." : "Try a different search or filter."}
            </EmptyState>
          )}
          <ul className="max-h-[70vh] overflow-y-auto">
            {rows.map((m) => {
              const Icon = CHANNEL_ICON[m.channel] ?? MessageSquare;
              return (
                <li key={m.id}>
                  <button onClick={() => setSelected(m.id)} aria-current={selected === m.id || undefined}
                    className={cx("flex w-full flex-col gap-1 border-b border-line px-3 py-3 text-left hover:bg-neutral-bg",
                      selected === m.id && "bg-brand-50")}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-2 text-sm font-semibold text-ink">
                        <Icon className="size-4 shrink-0 text-ink-subtle" aria-label={m.channel} />
                        <span className="truncate">{m.from_name}</span>
                        <span className="text-xs font-normal text-ink-subtle">{m.id}</span>
                      </span>
                      {m.processed ? <UrgencyBadge urgency={m.processed.urgency} /> : <Badge>Not processed</Badge>}
                    </span>
                    <span className="line-clamp-2 text-sm text-ink-muted">{m.body}</span>
                    <span className="text-xs text-ink-subtle">{formatTime(m.received_at)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        <section aria-label="Message detail" className={cx("min-w-0", !selected && "hidden lg:block")}>
          {selected && (
            <Button variant="ghost" className="mb-3 lg:hidden" onClick={() => setSelected(null)} icon={<ArrowLeft className="size-4" aria-hidden />}>
              Back to messages
            </Button>
          )}
          {!selectedEntry && <div className="card"><EmptyState title="Select a message">Pick a message on the left to see the agent's result, reply and tool calls.</EmptyState></div>}
          {selectedEntry && !selectedEntry.processed && (
            <div className="card p-5">
              <p className="text-sm font-semibold">{selectedEntry.from_name} · {selectedEntry.id}</p>
              <blockquote className="mt-2 border-l-4 border-line pl-3 text-sm">{selectedEntry.body}</blockquote>
              <Button className="mt-4" onClick={() => start([selectedEntry.id])} loading={running} icon={<Play className="size-4" aria-hidden />}>
                Process this message
              </Button>
            </div>
          )}
          {selectedEntry?.processed && !detail && !detailError && <Spinner label="Loading result…" />}
          {detailError && <ErrorState message={detailError} />}
          {detail && <MessageDetail item={detail} />}
        </section>
      </div>

      <ConfirmDialog open={confirmAll} title="Process all messages?" confirmLabel="Start"
        onCancel={() => setConfirmAll(false)} onConfirm={() => { setConfirmAll(false); void start(); }}>
        This resets the clinic schedule and queues to their starting state, then processes every message in this set
        in order. It uses AI quota and can take several minutes on the free tier. Saved AI answers are reused when available.
      </ConfirmDialog>
    </>
  );
}
