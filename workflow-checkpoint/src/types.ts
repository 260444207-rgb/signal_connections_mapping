export type Identity = { sessionKey: string; sessionId: string; agentId: string };
export type Run = Identity & { runId: string };
export type Input = {
  workflow_id: string; stage_id: string; status: 'completed' | 'paused' | 'failed';
  next_stage?: string; reason?: 'stage_boundary' | 'context_pressure' | 'manual' | 'recovery';
  state_hint?: Record<string, string[]>;
};
export type Summary = {
  objective: { primary: string; success_criteria: string[] };
  state: {
    facts: string[]; decisions: string[]; constraints: string[]; assumptions: string[];
    open_questions: string[]; blockers: string[];
  };
  artifacts: { type: string; path: string; purpose: string }[];
  next_stage_context: string[];
};
export type Snapshot = { messages: unknown[]; events: unknown[]; lifecycle_revision?: string };
export type Checkpoint = Summary & {
  handoff?: { archive_path: string; prompt_path: string; archive_sha256: string; prompt_sha256: string; user_inputs: unknown[]; lifecycle_revision?: string };
  schema_version: 1; checkpoint_id: string; session: Identity;
  workflow: { id: string; status: 'running' | 'completed' | 'paused' | 'failed' };
  transition: { from: string; to?: string; reason: string; completion_version: 1 };
  progress: { completed_stages: string[]; remaining_stages: string[] };
  continuation: { next_stage?: string; instruction: string; must_not_repeat: string[] };
  source_run_id: string; created_at: string;
};
export type WorkflowState = {
  schema_version: 1; session: Identity; workflow_id: string; current_stage?: string;
  completed_stages: string[]; remaining_stages: string[];
  status: Checkpoint['workflow']['status']; checkpoint_id: string; updated_at: string;
};
export type DeliveryStatus = 'pending' | 'dispatching' | 'submitted' | 'started' | 'completed' | 'held' | 'superseded';
export type Delivery = {
  checkpoint: Checkpoint; status: DeliveryStatus; runId?: string;
};
export interface SessionContextAdapter {
  history(identity: Identity): Promise<unknown[]>;
  snapshot(identity: Identity): Promise<Snapshot>;
  summarize(history: unknown[], previous: Summary | undefined, input: Input, identity: Identity, signal?: AbortSignal): Promise<Summary>;
  isCurrent(identity: Identity): Promise<boolean>;
  requestContinuation(checkpoint: Checkpoint): Promise<string>;
}
export class CheckpointError extends Error {
  code: string;
  retryable: boolean;
  constructor(code: string, retryable = false) {
    super(code); this.code = code; this.retryable = retryable;
  }
}
export const keyOf = (id: Identity, workflow: string): string => JSON.stringify([id.agentId, id.sessionKey, id.sessionId, workflow]);
export function parseInput(value: unknown): Input {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new CheckpointError('INVALID_INPUT');
  const p = value as Record<string, unknown>;
  const id = (x: unknown) => typeof x === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(x);
  if (Object.keys(p).some(k => !['workflow_id', 'stage_id', 'status', 'next_stage', 'reason', 'state_hint'].includes(k)) ||
      !id(p.workflow_id) || !id(p.stage_id) || !['completed', 'paused', 'failed'].includes(String(p.status)) ||
      (p.next_stage !== undefined && !id(p.next_stage)) ||
      (p.reason !== undefined && !['stage_boundary', 'context_pressure', 'manual', 'recovery'].includes(String(p.reason)))) {
    throw new CheckpointError('INVALID_INPUT');
  }
  if (p.status !== 'completed' && p.next_stage !== undefined) throw new CheckpointError('INVALID_TRANSITION');
  if (p.state_hint !== undefined) {
    if (!p.state_hint || typeof p.state_hint !== 'object' || Array.isArray(p.state_hint)) throw new CheckpointError('INVALID_HINT');
    for (const [k, v] of Object.entries(p.state_hint)) {
      if (!['completed', 'decisions', 'artifacts', 'blockers', 'notes'].includes(k) || !Array.isArray(v) ||
          v.length > 50 || v.some(x => typeof x !== 'string' || x.length > 2000)) throw new CheckpointError('INVALID_HINT');
    }
  }
  return p as Input;
}
export function validateSummary(value: unknown): Summary {
  const s = value as Summary;
  const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 200 && v.every(x => typeof x === 'string' && x.length <= 8000);
  if (!s || !s.objective || typeof s.objective.primary !== 'string' || !s.objective.primary.trim() || s.objective.primary.length > 8000 ||
      !strings(s.objective.success_criteria) || !s.state ||
      !['facts', 'decisions', 'constraints', 'assumptions', 'open_questions', 'blockers'].every(k => strings(s.state[k as keyof Summary['state']])) ||
      !strings(s.next_stage_context) || !Array.isArray(s.artifacts) || s.artifacts.length > 200 ||
      s.artifacts.some(a => !a || !['type', 'path', 'purpose'].every(k => typeof a[k as keyof typeof a] === 'string' && a[k as keyof typeof a].length <= 8000))) {
    throw new CheckpointError('INVALID_SUMMARY', true);
  }
  // Explicit projection prevents the summarizer from controlling workflow/session fields.
  return { objective: s.objective, state: s.state, artifacts: s.artifacts, next_stage_context: s.next_stage_context };
}
