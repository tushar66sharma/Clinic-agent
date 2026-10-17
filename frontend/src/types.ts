// Shapes returned by the Python API (src/edvak_forge/api/app.py).

export type Urgency = "emergency" | "urgent" | "routine";

export interface InboxMessage {
  id: string;
  received_at: string;
  channel: string;
  from_name: string;
  from_contact: string;
  body: string;
  stated_dob?: string;
}

export interface AgentResult {
  id: string;
  patient_id: string | null;
  intents: string[];
  urgency: Urgency;
  actions: string[];
  routed_to: string[];
  tool_calls: string[];
  reply_draft: string;
}

export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown> & { ok?: boolean };
  ms: number;
}

export interface Trace {
  id: string;
  path: string;
  guard: { level: string; matches: string[] } | null;
  analysis: Record<string, unknown> | null;
  verified: boolean;
  relationship: string | null;
  facts: string[];
  notes: string[];
  llm_error: string | null;
  tool_trace: ToolCall[];
  seconds?: number;
}

export interface ProcessedItem {
  message: InboxMessage;
  result: AgentResult;
  trace: Trace;
  processed_at: number;
}

export interface InboxEntry extends InboxMessage {
  processed: AgentResult | null;
}

export interface Health {
  status: string;
  today: string;
  ai: { configured: boolean; provider: string | null; models: Record<string, string> | null; error: string | null };
  access_token_required: boolean;
  busy: boolean;
}

export interface Job {
  id: string;
  set: string;
  status: "running" | "finished" | "failed";
  total: number;
  done: number;
  current: string | null;
  error: string | null;
  result_ids: string[];
}

export interface RunLog {
  queue_tickets: { ticket_id: string; message_id: string; queue: string; priority: Urgency; reason: string; patient_id: string | null }[];
  refill_requests: { request_id: string; message_id: string; patient_id: string; medication: string; prescriber: string; status: string }[];
  reply_drafts: { message_id: string; language: string; text: string }[];
  flags: { message_id: string; excerpt: string; reason: string }[];
  appointment_changes: { kind: string; appointment_id: string; message_id: string; replaces?: string }[];
}

export interface ScheduleAppt {
  appointment_id: string;
  start: string;
  end: string;
  visit_type: string;
  status: string;
  patient_id: string;
  patient_name: string | null;
  changed_this_session: boolean;
}

export interface Schedule {
  date: string;
  weekday: string;
  open: boolean;
  closed_reason: string | null;
  providers: { id: string; name: string; on_leave: boolean; appointments: ScheduleAppt[] }[];
  prev: string;
  next: string;
}

export interface Headline {
  messages: number;
  fully_correct: number;
  urgency_accuracy: number | null;
  emergency_recall: number | null;
  emergencies_total: number;
  emergencies_missed: string[];
  false_alarms: string[];
  action_exact_match: number | null;
  action_precision: number | null;
  action_recall: number | null;
  action_f1: number | null;
  patient_id_accuracy: number | null;
  intent_exact_match: number | null;
  reply_language_accuracy: number | null;
  booking_detail_accuracy?: number | null;
  bookings_checked?: number;
  must_not_violations: number;
  safety_invariant_issues: number;
}

export interface PerMessage {
  id: string;
  urgency: Urgency;
  accepted_urgency: string[];
  urgency_ok: boolean;
  expected_actions: string[];
  actions: string[];
  missing_actions: string[];
  extra_actions: string[];
  patient_id: string | null;
  expected_patient_id: string | null;
  patient_ok: boolean;
  fully_correct: boolean;
  violations: string[];
  booking_issues?: string[];
  trap: string;
  path: string;
}

export interface Evaluation {
  headline: Headline;
  must_not_violations: { id: string; code: string; evidence: string[] }[];
  safety_invariant_issues: { id: string; issue: string }[];
  per_action: { action: string; tp: number; fp: number; fn: number; precision: number | null; recall: number | null }[];
  per_message: PerMessage[];
  operations: Record<string, unknown> & { run_seconds?: number; total_tokens?: number; cost_at_paid_rates_usd?: number | null };
}
