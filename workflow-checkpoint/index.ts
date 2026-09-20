import { join } from 'node:path';
import type { OpenClawPluginApi } from 'openclaw/plugin-sdk/core';
import { Store } from './src/store.ts';
import { Coordinator } from './src/coordinator.ts';
import { OpenClawAdapter } from './src/openclaw-adapter.ts';
import type { Run } from './src/types.ts';

const toolName = 'workflow_checkpoint';
const stringId = { type: 'string', pattern: '^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$' };
const parameters = { type: 'object', additionalProperties: false, required: ['workflow_id', 'stage_id', 'status'], properties: {
  workflow_id: stringId, stage_id: stringId, status: { type: 'string', enum: ['completed', 'paused', 'failed'] },
  next_stage: stringId, reason: { type: 'string', enum: ['stage_boundary', 'context_pressure', 'manual', 'recovery'] },
  state_hint: { type: 'object', additionalProperties: false, properties: Object.fromEntries(
    ['completed', 'decisions', 'artifacts', 'blockers', 'notes'].map(k => [k, { type: 'array', maxItems: 50, items: { type: 'string', maxLength: 2000 } }])) },
} };
function asRun(ctx: { sessionKey?: string; sessionId?: string; agentId?: string; runId?: string }): Run | undefined {
  return ctx.sessionKey && ctx.sessionId && ctx.agentId && ctx.runId ? ctx as Run : undefined;
}
export default {
  id: 'workflow-checkpoint', name: 'Workflow Checkpoint',
  description: 'Durable stage checkpoints and same-session continuation.',
  register(api: OpenClawPluginApi) {
    if (api.runtime.version.replace(/^v/, '') !== '2026.9.2') throw new Error('workflow-checkpoint requires verified OpenClaw 2026.9.2.');
    const workflows = (api.pluginConfig?.workflows ?? {}) as Record<string, string[]>;
    for (const [id, stages] of Object.entries(workflows)) {
      if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(id) || !Array.isArray(stages) || !stages.length || new Set(stages).size !== stages.length ||
          stages.some(s => typeof s !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(s))) throw new Error('Invalid workflow definition.');
    }
    let store: Store | undefined;
    let coordinator: Coordinator | undefined;
    const runs = new Map<string, Run>();
    const calls = new Map<string, Run>();
    const inFlight = new Set<Promise<unknown>>();
    const track = async <T>(promise: Promise<T>): Promise<T> => {
      inFlight.add(promise);
      try { return await promise; } finally { inFlight.delete(promise); }
    };
    api.registerService({ id: 'workflow-checkpoint',
      async start(ctx) {
        store = new Store(join(ctx.stateDir, 'workflow-checkpoint', 'state.sqlite'));
        coordinator = new Coordinator(store, new OpenClawAdapter(api), workflows, event => api.logger.info(JSON.stringify(event)));
        await coordinator.recover();
      },
      async stop() {
        coordinator = undefined;
        await Promise.allSettled([...inFlight]);
        store?.close(); store = undefined; runs.clear(); calls.clear();
      },
    });
    api.on('agent_turn_prepare', (event, ctx) => {
      const run = asRun(ctx);
      if (!run) return;
      runs.set(run.runId, run);
      const prependContext = coordinator?.prepare(run, event.prompt);
      if (prependContext) return { prependContext };
    });
    api.on('before_tool_call', (event, ctx) => {
      const runId = event.runId ?? ctx.runId;
      const run = asRun({ ...ctx, runId }) ?? (runId ? runs.get(runId) : undefined);
      const callId = event.toolCallId ?? ctx.toolCallId;
      if (event.toolName === toolName && callId && run) calls.set(callId, run);
      if (run && coordinator?.blocked(run) && event.toolName !== toolName) return { block: true, blockReason: 'Checkpoint persisted. End this run; the next stage requires a new run in the same session.' };
    });
    api.on('before_agent_finalize', (_event, ctx) => {
      const run = asRun(ctx);
      if (run && coordinator?.blocked(run)) return { action: 'finalize' as const, reason: 'Workflow checkpoint boundary.' };
    });
    api.on('agent_end', (event, ctx) => {
      const run = asRun({ ...ctx, runId: event.runId ?? ctx.runId });
      if (!run) return;
      const active = coordinator;
      if (active) {
        const work = new Promise<void>(resolve => setImmediate(resolve)).then(() => active.end(run, event.success));
        void track(work).catch(() => api.logger.error('workflow-checkpoint: continuation worker failed; durable state retained.'));
      }
      runs.delete(run.runId);
      for (const [id, call] of calls) if (call.runId === run.runId) calls.delete(id);
    });
    api.registerTool(ctx => {
      if (!ctx.sessionKey || !ctx.sessionId || !ctx.agentId) return null;
      return {
        name: toolName, label: 'Workflow Checkpoint', catalogMode: 'direct-only' as const,
        description: 'Persist a declared workflow stage boundary. Call alone after all stage tools finish. On success end the run immediately; the coordinator resumes the same session. Never supply session identity or a prose summary.',
        parameters,
        async execute(callId: string, input: unknown, signal?: AbortSignal) {
          const run = calls.get(callId); calls.delete(callId);
          const result = run && coordinator && run.sessionKey === ctx.sessionKey && run.sessionId === ctx.sessionId && run.agentId === ctx.agentId
            ? await track(coordinator.checkpoint(run, input, signal))
            : { ok: false, code: 'RUNTIME_CONTEXT_UNAVAILABLE', retryable: true };
          return { content: [{ type: 'text' as const, text: JSON.stringify(result) }], details: result, isError: result.ok !== true };
        },
      };
    }, { name: toolName });
  },
};
