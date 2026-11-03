import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { homedir } from 'node:os'

export function backendTarget(env = process.env) {
  let target = env.MATHLENS_BACKEND_URL
  if (!target) {
    try {
      const dataDir =
        env.MATHLENS_DATA_DIR ||
        resolve(
          env.LOCALAPPDATA || resolve(homedir(), '.local', 'share'),
          'ZuoTiLong',
          'workspaces',
          'default',
        )
      target = JSON.parse(readFileSync(resolve(dataDir, 'server.json'), 'utf8')).url
    } catch {
      /* Backend may not have started yet. */
    }
  }
  const url = new URL(target || 'http://127.0.0.1:8765')
  if (
    url.protocol !== 'http:' ||
    !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
    url.username ||
    url.password
  )
    throw new Error('MathLens development backend must use local HTTP')
  return url.origin
}
