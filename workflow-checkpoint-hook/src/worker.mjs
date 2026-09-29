import { sessionBoundary } from './boundary.mjs';
import { join } from 'node:path';
import { Registry } from './registry.mjs';
import { Store } from './store.mjs';
import { Coordinator } from './coordinator.mjs';
import { OpenClawAdapter } from './openclaw-adapter.mjs';
export async function executeJob(id, config, sdk, options = {}) {
  const registry = new Registry(config.stateDir);
  let store;
  try {
    if (!registry.claim(id))
      return { skipped: true };
    const job = registry.job(id);
    const deadline = Date.now() + (config.waitTimeoutMs || 900000);
    let binding;
    while (true) {
      binding = registry.binding(job.token);
      if (binding.run_status === 'ended')
        break;
      if (binding.run_status !== 'running')
        throw Error('SOURCE_RUN_FAILED_OR_UNKNOWN');
      if (Date.now() > deadline)
        throw Error('SOURCE_RUN_END_TIMEOUT');
      await new Promise(resolve => setTimeout(resolve, options.pollMs || 250));
    }
    const entry = sdk.getSessionEntry({ ...binding.identity, readConsistency: 'latest' });
    if (entry?.incognito === true || sdk.isIncognitoSessionKey?.(binding.identity.sessionKey))
      throw Error('INCOGNITO_SESSION_UNSUPPORTED');
    if (entry?.sessionId !== binding.identity.sessionId || sessionBoundary(entry) !== binding.revision)
      throw Error('SESSION_BOUNDARY_CHANGED');
    store = new Store(join(config.stateDir, 'state.sqlite'));
    if (registry.hasOtherRunning(binding.identity, binding.run_id))
      throw Error('ANOTHER_RUN_ACTIVE');
    const guardedSdk = { ...sdk, callGatewayFromCli(method, ...args) {
        if (method === 'sessions.reset' && registry.hasOtherRunning(binding.identity, binding.run_id))
          throw Error('ANOTHER_RUN_ACTIVE');
        return sdk.callGatewayFromCli(method, ...args);
      } };
    const adapter = options.adapter || new OpenClawAdapter(guardedSdk, config);
    const coordinator = new Coordinator(store, adapter, config.workflows, event => console.log(JSON.stringify(event)), config.workflowSkills);
    const run = { ...binding.identity, runId: binding.run_id };
    const result = await coordinator.checkpoint(run, job.input);
    if (!result.ok) {
      registry.finish(id, 'held', result.code);
      return result;
    }
    await coordinator.end(run, true);
    const delivery = store.list(binding.identity).find(d => d.checkpoint.checkpoint_id === result.checkpoint_id);
    const status = ['submitted', 'started', 'completed'].includes(delivery?.status) ? 'done' : 'held';
    registry.finish(id, status, status === 'held' ? 'CONTINUATION_REQUIRES_ATTENTION' : null, result.checkpoint_id);
    return { ...result, job_status: status };
  }
  catch (error) {
    // Do not replay a working/held job after a crash: reset may already have run.
    const code = /^[A-Z][A-Z0-9_]+$/.test(error.message) ? error.message : 'WORKER_FAILED';
    registry.finish(id, 'held', code);
    return { ok: false, code };
  }
  finally {
    store?.close();
    registry.close();
  }
}
