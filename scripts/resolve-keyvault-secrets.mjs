/**
 * Azure Key Vault runtime secret injector for Langfuse.
 *
 * Modes:
 *   1. spawn mode (default): node resolve-keyvault-secrets.mjs -- <command> [args...]
 *   2. shell export mode:      node resolve-keyvault-secrets.mjs --export-shell
 */

import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'dotenv';

const envPath = resolve(import.meta.dirname, '..', '.env');
let fileEnv = {};
if (existsSync(envPath)) {
  fileEnv = parse(readFileSync(envPath, 'utf-8'));
}

const baseEnv = process.env;
const mergedEnv = {
  ...fileEnv,
  ...baseEnv,
};

const SECRET_MAPPINGS = {
  DIRECT_URL: 'langfuse-db-url',
  DATABASE_URL: 'langfuse-db-url',
  CLICKHOUSE_PASSWORD: 'langfuse-clickhouse-password',
  NEXTAUTH_SECRET: 'langfuse-nextauthsecret',
  SALT: 'langfuse-salt',
  LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY: 'langfuse-blobstorage-api-key',
  LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: 'langfuse-blobstorage-api-key',
  LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY: 'langfuse-blobstorage-api-key',
  // REDIS_AUTH: 'agentcore-redis-password',
  REDIS_AUTH: 'agentcore-redis-password-local',
  ENCRYPTION_KEY: 'langfuse-encryption-key',
};

async function resolveKeyVaultSecrets(env) {
  const vaultUrl = (env.LANGFUSE_KEY_VAULT_URL ?? '').trim();
  if (!vaultUrl) {
    return env;
  }

  const { SecretClient } = await import('@azure/keyvault-secrets');
  const { DefaultAzureCredential } = await import('@azure/identity');

  const credential = new DefaultAzureCredential({
    excludeEnvironmentCredential: true,
    excludeInteractiveBrowserCredential: true,
  });

  const secretClient = new SecretClient(vaultUrl, credential);
  console.error(`[keyvault] Fetching secrets from ${vaultUrl} ...`);

  const resolved = [];
  const failed = [];

  for (const [envName, kvSecretName] of Object.entries(SECRET_MAPPINGS)) {
    try {
      const secret = await secretClient.getSecret(kvSecretName);
      if (!secret.value) {
        failed.push(`${envName}: secret '${kvSecretName}' is empty`);
        continue;
      }
      env[envName] = secret.value;
      resolved.push(envName);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failed.push(`${envName} (${kvSecretName}): ${message}`);
    }
  }

  console.error(
    `[keyvault] Injected ${resolved.length} secret(s) into runtime environment: ${resolved.join(', ')}`,
  );

  if (failed.length > 0) {
    console.error(`[keyvault] Failed to resolve ${failed.length} secret(s):`);
    for (const failure of failed) {
      console.error(`  - ${failure}`);
    }
    process.exit(1);
  }

  return env;
}

function shellEscape(value) {
  return `'${String(value).replace(/'/g, `'"'"'`)}'`;
}

function exportShell(env) {
  const exportKeys = new Set([
    ...Object.keys(fileEnv),
    ...Object.keys(SECRET_MAPPINGS),
    'LANGFUSE_KEY_VAULT_URL',
  ]);

  const lines = [];
  for (const key of exportKeys) {
    const value = env[key];
    if (typeof value === 'string') {
      lines.push(`export ${key}=${shellEscape(value)}`);
    }
  }
  return `${lines.join('\n')}\n`;
}

async function main() {
  const exportMode = process.argv.includes('--export-shell');
  const enrichedEnv = await resolveKeyVaultSecrets({ ...mergedEnv });

  if (exportMode) {
    process.stdout.write(exportShell(enrichedEnv));
    return;
  }

  const separatorIndex = process.argv.indexOf('--');
  if (separatorIndex === -1 || separatorIndex === process.argv.length - 1) {
    console.error('Usage: node resolve-keyvault-secrets.mjs -- <command> [args...]');
    process.exit(1);
  }

  const [command, ...args] = process.argv.slice(separatorIndex + 1);
  const child = spawn(command, args, {
    env: enrichedEnv,
    stdio: 'inherit',
  });

  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(signal, () => child.kill(signal));
  }

  child.on('exit', (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 1);
    }
  });
}

main().catch((error) => {
  console.error('[keyvault] Fatal error:', error);
  process.exit(1);
});
