export function validateSummaryConfig(config) {
  if (!config?.baseUrl && !config?.model) return 'agent';
  if (!config?.baseUrl || !config?.model) throw Error('SUMMARIZER_CONFIG_INCOMPLETE');
  const base = new URL(config.baseUrl);
  if (base.protocol !== 'https:' && !(base.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)))
    throw Error('SUMMARIZER_URL_REQUIRES_HTTPS');
  const key = process.env[config.apiKeyEnv || 'WORKFLOW_CHECKPOINT_API_KEY'];
  if (!key)
    throw Error('SUMMARIZER_API_KEY_MISSING');
  return 'external';
}
export async function completeSummary(config, request, sdk) {
  request.signal?.throwIfAborted();
  if (validateSummaryConfig(config) === 'agent') {
    const runtime = await sdk.loadAgentCompletionRuntime();
    const cfg = runtime.loadConfig();
    if (!runtime.listAgentIds(cfg).includes(request.agentId)) throw Error('SUMMARY_AGENT_NOT_REGISTERED');
    let prepared;
    try {
      prepared = await runtime.prepareSimpleCompletionModelForAgent({ cfg, agentId: request.agentId, useUtilityModel: false });
    } catch { throw Error('AGENT_MODEL_PREPARE_FAILED'); }
    if (!prepared?.model || prepared.error) throw Error('AGENT_MODEL_PREPARE_FAILED');
    let result;
    try {
      result = await runtime.completeWithPreparedSimpleCompletionModel({ cfg, model: prepared.model, auth: prepared.auth,
        context: { systemPrompt: request.systemPrompt, messages: request.messages.map(message => ({ ...message, timestamp: Date.now() })) },
        options: { signal: request.signal, maxTokens: request.maxTokens, temperature: request.temperature } });
    } catch { throw Error('AGENT_MODEL_COMPLETION_FAILED'); }
    request.signal?.throwIfAborted();
    const text = result?.content?.filter(part => part.type === 'text').map(part => part.text).join('\n');
    if (!text?.trim() || ['error', 'aborted', 'toolUse'].includes(result.stopReason)) throw Error('SUMMARIZER_INVALID_RESPONSE');
    return { text };
  }
  const key = process.env[config.apiKeyEnv || 'WORKFLOW_CHECKPOINT_API_KEY'];
  const response = await fetch(config.baseUrl.replace(/\/$/, '') + '/chat/completions', {
    method: 'POST', signal: request.signal,
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + key },
    body: JSON.stringify({ model: config.model, temperature: 0,
      messages: [{ role: 'system', content: request.systemPrompt }, ...request.messages] }),
  });
  if (!response.ok)
    throw Error('SUMMARIZER_HTTP_' + response.status);
  const result = await response.json();
  const text = result.choices?.[0]?.message?.content;
  if (typeof text !== 'string')
    throw Error('SUMMARIZER_INVALID_RESPONSE');
  return { text };
}
