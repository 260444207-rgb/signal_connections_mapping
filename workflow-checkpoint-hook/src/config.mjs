import { readFileSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
export const hookDirectory = dirname(dirname(fileURLToPath(import.meta.url)));
export function readConfig() {
  const config = JSON.parse(readFileSync(join(hookDirectory, 'config.json'), 'utf8'));
  for (const [id, stages] of Object.entries(config.workflows ?? {})) {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(id) || !Array.isArray(stages) || !stages.length || new Set(stages).size !== stages.length ||
      stages.some(s => typeof s !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(s)))
      throw Error('INVALID_WORKFLOW_CONFIG');
  }
  for (const [id, path] of Object.entries(config.workflowSkills ?? {})) {
    if (!config.workflows?.[id] || typeof path !== 'string' || !isAbsolute(path))
      throw Error('INVALID_WORKFLOW_SKILL_PATH');
  }
  const stateDir = config.stateDir || join(process.env.OPENCLAW_STATE_DIR || join(homedir(), '.openclaw'), 'workflow-checkpoint-hook');
  if (!isAbsolute(stateDir))
    throw Error('STATE_DIR_MUST_BE_ABSOLUTE');
  return { ...config, stateDir };
}
