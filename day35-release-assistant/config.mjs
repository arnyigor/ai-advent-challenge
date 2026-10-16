import path from 'node:path';
import {fileURLToPath} from 'node:url';
export const DAY = path.dirname(fileURLToPath(import.meta.url));
export const PROFILE = Object.freeze({
  id: 'dns-hosts-generator', name: 'DnsHostsGenerator',
  url: 'https://github.com/arnyigor/DnsHostsGenerator',
  checks: [
    {id: 'shared-jvm-tests', task: ':shared:jvmTest', required: true},
    {id: 'android-debug', task: ':androidApp:assembleDebug', required: true},
    {id: 'desktop-package', task: ':desktopApp:createDistributable', required: true},
  ],
});
export function settings() {
  return {
    repo: path.resolve(process.env.DAY35_REPO || path.join(DAY, 'data', PROFILE.name)),
    base: process.env.DAY35_BASE || 'v1.4.0', head: process.env.DAY35_HEAD || 'v1.4.1',
    provider: process.env.DAY35_PROVIDER || 'gemini', model: process.env.DAY35_MODEL || '',
    localUrl: process.env.LOCAL_LLM_URL || 'http://127.0.0.1:8085/v1',
    port: Number(process.env.DAY35_WEB_PORT || 8835),
    runsDir: path.resolve(process.env.DAY35_RUNS_DIR || path.join(DAY, 'runs')),
    maxContext: Number(process.env.DAY35_MAX_CONTEXT || 260000),
    checkTimeout: Number(process.env.DAY35_CHECK_TIMEOUT_MS || 600000),
    modelTimeout: Number(process.env.DAY35_MODEL_TIMEOUT_MS || 180000),
  };
}
