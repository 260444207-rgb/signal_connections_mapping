export class CheckpointError extends Error {
  code;
  retryable;
  constructor(code, retryable = false) {
    super(code);
    this.code = code;
    this.retryable = retryable;
  }
}
export const keyOf = (id, workflow) => JSON.stringify([id.agentId, id.sessionKey, id.sessionId, workflow]);
export function parseInput(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new CheckpointError('INVALID_INPUT');
  const p = value;
  const id = (x) => typeof x === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(x);
  if (Object.keys(p).some(k => !['workflow_id', 'stage_id', 'status', 'next_stage', 'reason', 'state_hint'].includes(k)) ||
    !id(p.workflow_id) || !id(p.stage_id) || !['completed', 'paused', 'failed'].includes(String(p.status)) ||
    (p.next_stage !== undefined && !id(p.next_stage)) ||
    (p.reason !== undefined && !['stage_boundary', 'context_pressure', 'manual', 'recovery'].includes(String(p.reason)))) {
    throw new CheckpointError('INVALID_INPUT');
  }
  if (p.status !== 'completed' && p.next_stage !== undefined)
    throw new CheckpointError('INVALID_TRANSITION');
  if (p.state_hint !== undefined) {
    if (!p.state_hint || typeof p.state_hint !== 'object' || Array.isArray(p.state_hint))
      throw new CheckpointError('INVALID_HINT');
    for (const [k, v] of Object.entries(p.state_hint)) {
      if (!['completed', 'decisions', 'artifacts', 'blockers', 'notes'].includes(k) || !Array.isArray(v) ||
        v.length > 50 || v.some(x => typeof x !== 'string' || x.length > 2000))
        throw new CheckpointError('INVALID_HINT');
    }
  }
  return p;
}
export function validateSummary(value) {
  const s = value;
  const strings = (v) => Array.isArray(v) && v.length <= 200 && v.every(x => typeof x === 'string' && x.length <= 8000);
  if (!s || !s.objective || typeof s.objective.primary !== 'string' || !s.objective.primary.trim() || s.objective.primary.length > 8000 ||
    !strings(s.objective.success_criteria) || !s.state ||
    !['facts', 'decisions', 'constraints', 'assumptions', 'open_questions', 'blockers'].every(k => strings(s.state[k])) ||
    !strings(s.next_stage_context) || !Array.isArray(s.artifacts) || s.artifacts.length > 200 ||
    s.artifacts.some(a => !a || !['type', 'path', 'purpose'].every(k => typeof a[k] === 'string' && a[k].length <= 8000))) {
    throw new CheckpointError('INVALID_SUMMARY', true);
  }
  // Explicit projection prevents the summarizer from controlling workflow/session fields.
  return { objective: s.objective, state: s.state, artifacts: s.artifacts, next_stage_context: s.next_stage_context };
}
