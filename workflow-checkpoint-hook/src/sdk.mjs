import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readConfig } from './config.mjs';
let promise;
export function loadSdk() {
  return promise ??= (async () => {
    const config = readConfig();
    const require = createRequire(config.openclawPackageRoot ? join(config.openclawPackageRoot, 'package.json') : import.meta.url);
    const load = name => import(pathToFileURL(require.resolve('openclaw/plugin-sdk/' + name)).href);
    const [harness, sessions, transcript, gateway, keys] = await Promise.all([
      load('agent-harness-runtime'), load('session-store-runtime'), load('session-transcript-runtime'), load('gateway-runtime'), load('session-key-runtime'),
    ]);
    if (harness.OPENCLAW_VERSION?.replace(/^v/, '') !== '2026.7.1')
      throw Error('UNVERIFIED_OPENCLAW_VERSION');
    const core = await load('agent-core');
    return { ...sessions, ...transcript, ...gateway, ...keys, SessionManager: core.SessionManager,
      onAgentEvent: harness.onAgentEvent,
      loadAgentCompletionRuntime: async () => Object.assign({}, ...await Promise.all([load('agent-runtime'), load('config-runtime')])) };
  })();
}
