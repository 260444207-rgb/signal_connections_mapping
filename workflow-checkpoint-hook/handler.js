import { sessionBoundary } from './src/boundary.mjs';
import { join } from 'node:path';
import { readConfig, hookDirectory } from './src/config.mjs';
import { loadSdk } from './src/sdk.mjs';
import { Registry } from './src/registry.mjs';
const slot = Symbol.for('workflow-checkpoint.file-hook.runtime.v2');
export async function handle(event, sdk, config) {
  if (event.type === 'gateway' && ['shutdown', 'pre-restart'].includes(event.action)) {
    globalThis[slot]?.unsubscribe();
    globalThis[slot]?.registry.close();
    delete globalThis[slot];
    return;
  }
  let runtime = globalThis[slot];
  if (!runtime) {
    const registry = new Registry(config.stateDir);
    // A previous process cannot authenticate the active run of this process.
    registry.db.prepare("UPDATE runs SET status='unknown' WHERE status='running'").run();
    const unsubscribe = sdk.onAgentEvent(payload => {
      try {
        registry.observe(payload);
      }
      catch {
        console.error('[workflow-checkpoint-hook] run observation persistence failed');
      }
    });
    runtime = globalThis[slot] = { registry, unsubscribe };
  }
  if (event.type !== 'agent' || event.action !== 'bootstrap')
    return;
  const ctx = event.context;
  if (!ctx.agentId || !ctx.sessionId || !event.sessionKey || !ctx.workspaceDir || !Array.isArray(ctx.bootstrapFiles))
    return;
  const identity = { agentId: ctx.agentId, sessionKey: event.sessionKey, sessionId: ctx.sessionId };
  const entry = sdk.getSessionEntry({ ...identity, readConsistency: 'latest' });
  if (entry?.incognito === true || sdk.isIncognitoSessionKey?.(identity.sessionKey))
    return;
  if (entry?.sessionId !== identity.sessionId || !sessionBoundary(entry))
    return;
  const token = runtime.registry.bind(identity, sessionBoundary(entry));
  const guidance = [
    '',
    '## Workflow checkpoint handoff (file Hook)',
    'The current-run binding token is: ' + token,
    'At a Skill checkpoint use the existing shell/exec tool to run Node with these argv:',
    JSON.stringify([join(hookDirectory, 'checkpoint.mjs'), 'request', '--token', token, '--workflow', '<configured-workflow>', '--stage', '<current-stage>', '--next', '<next-stage>']),
    'Omit --next for the final stage. Replace stage placeholders with the configured Skill stages.',
    'After accepted=true, END THE CURRENT RUN. Do not call other tools, poll status, or begin the next stage.',
    'The background script waits for this run to end, archives local context, resets this same session, and submits the saved restart prompt.',
    'On accepted=false, stop at the boundary and report the code. Never reset sessions yourself.',
  ].join('\n');
  const agents = ctx.bootstrapFiles.find(file => file.name === 'AGENTS.md');
  if (agents) {
    agents.content = (agents.content || '') + guidance;
    agents.missing = false;
  }
  else
    ctx.bootstrapFiles.push({ name: 'AGENTS.md', path: join(ctx.workspaceDir, 'AGENTS.md'), content: guidance, missing: false });
}
export default async function handler(event) {
  // These are real internal Hook events, not plugin api.on event names.
  if (!((event.type === 'gateway' && ['startup', 'shutdown', 'pre-restart'].includes(event.action)) ||
    (event.type === 'agent' && event.action === 'bootstrap')))
    return;
  await handle(event, await loadSdk(), readConfig());
}
