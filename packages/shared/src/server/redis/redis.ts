import Redis, { RedisOptions, Cluster, ClusterOptions } from "ioredis";
import * as fs from "node:fs";
import { DefaultAzureCredential } from "@azure/identity";
import { env } from "../../env";
import { logger } from "../logger";

const defaultRedisOptions: Partial<RedisOptions> = {
  enableReadyCheck: true,
  maxRetriesPerRequest: null,
  enableAutoPipelining: env.REDIS_ENABLE_AUTO_PIPELINING === "true",
  // keyPrefix removed - BullMQ uses its own prefix option
};

const REDIS_SCAN_COUNT = 1000;
const AZURE_MANAGED_REDIS_SCOPE = "https://redis.azure.com/.default";
const AZURE_MANAGED_REDIS_REFRESH_BUFFER_MS = 5 * 60 * 1000;
const AZURE_MANAGED_REDIS_MIN_REFRESH_MS = 60 * 1000;

type AzureRedisAccessToken = {
  token: string;
  expiresOnTimestamp: number;
};

const isAzureManagedRedisAuthEnabled =
  env.REDIS_USE_DEFAULT_AZURE_CREDENTIAL === "true";

const azureManagedIdentityClientId = process.env.AZURE_CLIENT_ID?.trim();

const azureManagedRedisCredential = isAzureManagedRedisAuthEnabled
  ? new DefaultAzureCredential(
      azureManagedIdentityClientId
        ? {
            managedIdentityClientId: azureManagedIdentityClientId,
            workloadIdentityClientId: azureManagedIdentityClientId,
          }
        : undefined,
    )
  : null;

const azureManagedRedisClients = new Set<Redis | Cluster>();
let azureManagedRedisToken: AzureRedisAccessToken | null = null;
let azureManagedRedisTokenPromise: Promise<AzureRedisAccessToken> | null = null;
let azureManagedRedisRefreshTimer: ReturnType<typeof setTimeout> | null = null;

export const redisQueueRetryOptions: Partial<RedisOptions> = {
  retryStrategy: (times: number) => {
    if (times >= 5) {
      // A few retries are expected and no cause for action.
      logger.warn(`Connection to redis lost. Retry attempt: ${times}`);
    }
    // Retries forever. Waits at least 1s and at most 20s between retries.
    return Math.max(Math.min(Math.exp(times), 20000), 1000);
  },
  reconnectOnError: (err) => {
    // MOVED/ASK are normal cluster redirections handled by ioredis — not real errors.
    if (err.message.includes("MOVED")) {
      logger.debug(`Redis cluster redirect: ${err.message}`);
      return false;
    }

    // Reconnects on READONLY errors and auto-retries the command.
    logger.warn(`Redis connection error: ${err.message}`);
    return err.message.includes("READONLY") ? 2 : false;
  },
};

/**
 * Parse Redis node definitions from environment variable
 * Format: "host1:port1,host2:port2,host3:port3"
 */
const parseRedisNodes = (
  nodesString: string,
): Array<{ host: string; port: number }> => {
  return nodesString.split(",").map((node) => {
    const [host, port] = node.trim().split(":");
    if (!host || !port) {
      throw new Error(
        `Invalid Redis node format: ${node}. Expected format: host:port`,
      );
    }
    return { host, port: parseInt(port, 10) };
  });
};
const parseClusterNodes = parseRedisNodes;
const parseSentinelNodes = parseRedisNodes;

/**
 * Build TLS options for Redis connections from environment variables
 * Returns an object with tls configuration if TLS is enabled, otherwise empty object
 */
const buildTlsOptions = (): Record<string, unknown> => {
  if (env.REDIS_TLS_ENABLED !== "true") {
    return {};
  }

  let defaultServername: string | undefined;
  if (env.REDIS_CONNECTION_STRING) {
    try {
      const url = new URL(env.REDIS_CONNECTION_STRING);
      defaultServername = url.hostname;
    } catch {
      // ignore parsing errors
    }
  } else if (env.REDIS_CLUSTER_NODES) {
    defaultServername = parseClusterNodes(env.REDIS_CLUSTER_NODES)[0]?.host;
  } else if (env.REDIS_HOST) {
    defaultServername = String(env.REDIS_HOST);
  }

  return {
    tls: {
      ca: env.REDIS_TLS_CA_PATH
        ? fs.readFileSync(env.REDIS_TLS_CA_PATH)
        : undefined,
      cert: env.REDIS_TLS_CERT_PATH
        ? fs.readFileSync(env.REDIS_TLS_CERT_PATH)
        : undefined,
      key: env.REDIS_TLS_KEY_PATH
        ? fs.readFileSync(env.REDIS_TLS_KEY_PATH)
        : undefined,
      ...(env.REDIS_TLS_REJECT_UNAUTHORIZED
        ? {
            rejectUnauthorized: env.REDIS_TLS_REJECT_UNAUTHORIZED !== "false",
          }
        : {}),
      ...(env.REDIS_TLS_SERVERNAME
        ? { servername: env.REDIS_TLS_SERVERNAME }
        : defaultServername
          ? { servername: defaultServername }
          : {}),
      ...(env.REDIS_TLS_CHECK_SERVER_IDENTITY === "false"
        ? { checkServerIdentity: () => undefined }
        : {}),
      ...(env.REDIS_TLS_SECURE_PROTOCOL
        ? { secureProtocol: env.REDIS_TLS_SECURE_PROTOCOL }
        : {}),
      ...(env.REDIS_TLS_CIPHERS ? { ciphers: env.REDIS_TLS_CIPHERS } : {}),
      ...(env.REDIS_TLS_HONOR_CIPHER_ORDER
        ? {
            honorCipherOrder: env.REDIS_TLS_HONOR_CIPHER_ORDER === "true",
          }
        : {}),
      ...(env.REDIS_TLS_KEY_PASSPHRASE
        ? { passphrase: env.REDIS_TLS_KEY_PASSPHRASE }
        : {}),
    },
  };
};

const getRedisUsername = (): string | undefined =>
  env.REDIS_USERNAME || undefined;

const getRedisPassword = (): string | undefined => env.REDIS_AUTH || undefined;

const validateAzureManagedRedisConfig = (): string | null => {
  if (!isAzureManagedRedisAuthEnabled) {
    return null;
  }

  if (env.REDIS_TLS_ENABLED !== "true") {
    return "REDIS_TLS_ENABLED must be true when REDIS_USE_DEFAULT_AZURE_CREDENTIAL is enabled";
  }

  if (!env.REDIS_USERNAME) {
    return "REDIS_USERNAME must be set to the Microsoft Entra object ID for Azure Managed Redis authentication";
  }

  if (!env.REDIS_AUTH) {
    return "REDIS_AUTH is missing. Start Langfuse through scripts/resolve-keyvault-secrets.mjs so the initial Azure Managed Redis token is injected before ioredis connects";
  }

  if (env.REDIS_SENTINEL_ENABLED === "true") {
    return "Azure Managed Redis authentication via DefaultAzureCredential is not supported with Redis Sentinel mode";
  }

  return null;
};

const scheduleAzureManagedRedisRefresh = (
  accessToken: AzureRedisAccessToken,
): void => {
  if (!isAzureManagedRedisAuthEnabled) return;

  if (azureManagedRedisRefreshTimer) {
    clearTimeout(azureManagedRedisRefreshTimer);
  }

  const refreshInMs = Math.max(
    accessToken.expiresOnTimestamp -
      Date.now() -
      AZURE_MANAGED_REDIS_REFRESH_BUFFER_MS,
    AZURE_MANAGED_REDIS_MIN_REFRESH_MS,
  );

  azureManagedRedisRefreshTimer = setTimeout(() => {
    void refreshAzureManagedRedisAccessToken(true).catch((error) => {
      logger.error("Failed to refresh Azure Managed Redis access token", error);
      azureManagedRedisRefreshTimer = setTimeout(() => {
        void refreshAzureManagedRedisAccessToken(true).catch((retryError) => {
          logger.error(
            "Retrying Azure Managed Redis access token refresh failed",
            retryError,
          );
        });
      }, AZURE_MANAGED_REDIS_MIN_REFRESH_MS);
      azureManagedRedisRefreshTimer.unref?.();
    });
  }, refreshInMs);

  azureManagedRedisRefreshTimer.unref?.();
};

const applyAzureManagedRedisTokenToClient = async (
  client: Redis | Cluster,
  accessToken: AzureRedisAccessToken,
): Promise<void> => {
  const username = getRedisUsername();

  if (client instanceof Cluster) {
    // Update the base redisOptions so every subsequently created node
    // connection (including those from cluster slot refresh) uses the
    // new token.
    client.options.redisOptions = client.options.redisOptions || {};
    client.options.redisOptions.username = username;
    client.options.redisOptions.password = accessToken.token;

    // Update each currently known node's options in place.
    for (const node of client.nodes("all")) {
      node.options.username = username;
      node.options.password = accessToken.token;
    }

    // Force a full cluster reconnect. ioredis has no native streaming
    // credential provider, so the most reliable way to re-authenticate
    // every existing connection (including the ephemeral ones created
    // during slot refresh) is to drop them and let ioredis reconnect
    // with the updated redisOptions. Commands are queued during
    // reconnect, so no data is lost.
    client.disconnect(true);
  } else {
    client.options.username = username;
    client.options.password = accessToken.token;
    client.disconnect(true);
  }
};

const refreshAzureManagedRedisAccessToken = async (
  forceRefresh = false,
): Promise<AzureRedisAccessToken> => {
  if (!isAzureManagedRedisAuthEnabled || !azureManagedRedisCredential) {
    throw new Error(
      "Azure Managed Redis token refresh requested while REDIS_USE_DEFAULT_AZURE_CREDENTIAL is disabled",
    );
  }

  if (
    azureManagedRedisToken &&
    !forceRefresh &&
    azureManagedRedisToken.expiresOnTimestamp - Date.now() >
      AZURE_MANAGED_REDIS_REFRESH_BUFFER_MS
  ) {
    return azureManagedRedisToken;
  }

  if (azureManagedRedisTokenPromise) {
    return azureManagedRedisTokenPromise;
  }

  azureManagedRedisTokenPromise = (async () => {
    const accessToken = await azureManagedRedisCredential.getToken(
      AZURE_MANAGED_REDIS_SCOPE,
    );

    if (!accessToken?.token) {
      throw new Error(
        "DefaultAzureCredential did not return an Azure Managed Redis access token",
      );
    }

    const resolvedToken: AzureRedisAccessToken = {
      token: accessToken.token,
      expiresOnTimestamp: accessToken.expiresOnTimestamp,
    };

    azureManagedRedisToken = resolvedToken;
    scheduleAzureManagedRedisRefresh(resolvedToken);

    await Promise.all(
      Array.from(azureManagedRedisClients).map(async (client) => {
        try {
          await applyAzureManagedRedisTokenToClient(client, resolvedToken);
        } catch (error) {
          logger.error(
            "Failed to apply refreshed Azure Managed Redis token to an active Redis client",
            error,
          );
        }
      }),
    );

    logger.debug("Azure Managed Redis access token refreshed");

    return resolvedToken;
  })().finally(() => {
    azureManagedRedisTokenPromise = null;
  });

  return azureManagedRedisTokenPromise;
};

const registerAzureManagedRedisClient = (client: Redis | Cluster): void => {
  if (!isAzureManagedRedisAuthEnabled) {
    return;
  }

  azureManagedRedisClients.add(client);

  client.on("ready", () => {
    void refreshAzureManagedRedisAccessToken().catch((error) => {
      logger.error(
        "Failed to refresh Azure Managed Redis token after Redis client became ready",
        error,
      );
    });
  });

  client.on("end", () => {
    azureManagedRedisClients.delete(client);
  });

  void refreshAzureManagedRedisAccessToken().catch((error) => {
    logger.error(
      "Failed to start Azure Managed Redis token refresh loop",
      error,
    );
  });
};

const createRedisClusterInstance = (
  additionalOptions: Partial<RedisOptions> = {},
): Cluster | null => {
  if (!env.REDIS_CLUSTER_NODES) {
    logger.error(
      "REDIS_CLUSTER_NODES is required when REDIS_CLUSTER_ENABLED is true",
    );
    return null;
  }

  const nodes = parseClusterNodes(env.REDIS_CLUSTER_NODES);
  const tlsOptions = buildTlsOptions();

  const clusterOptions: ClusterOptions = {
    // Return incoming addresses as-is - required for AWS ElastiCache Certificate resolution
    dnsLookup: (address, callback) => {
      callback(null, address);
    },
    slotsRefreshTimeout: env.REDIS_CLUSTER_SLOTS_REFRESH_TIMEOUT,
    redisOptions: {
      username: getRedisUsername(),
      password: getRedisPassword(),
      ...defaultRedisOptions,
      ...additionalOptions,
      ...tlsOptions,
    },
    // Retry configuration for cluster
    retryDelayOnFailover: 100,
  };

  const cluster = new Cluster(nodes, clusterOptions);

  cluster.on("error", (error) => {
    logger.error("Redis cluster error", error);
  });

  return cluster;
};

const createRedisSentinelInstance = (
  additionalOptions: Partial<RedisOptions> = {},
): Redis | null => {
  if (!env.REDIS_SENTINEL_MASTER_NAME) {
    logger.error(
      "REDIS_SENTINEL_MASTER_NAME is required when REDIS_SENTINEL_ENABLED is true",
    );
    return null;
  }

  if (!env.REDIS_SENTINEL_NODES) {
    logger.error(
      "REDIS_SENTINEL_NODES is required when REDIS_SENTINEL_ENABLED is true",
    );
    return null;
  }

  const sentinels = parseSentinelNodes(env.REDIS_SENTINEL_NODES);
  const tlsOptions = buildTlsOptions();

  const instance = new Redis({
    sentinels,
    name: env.REDIS_SENTINEL_MASTER_NAME,
    username: getRedisUsername(),
    password: getRedisPassword(),
    sentinelUsername: env.REDIS_SENTINEL_USERNAME || undefined,
    sentinelPassword: env.REDIS_SENTINEL_PASSWORD || undefined,
    ...defaultRedisOptions,
    ...additionalOptions,
    ...tlsOptions,
  });

  instance.on("error", (error) => {
    logger.error("Redis sentinel error", error);
  });

  return instance;
};

export const createNewRedisInstance = (
  additionalOptions: Partial<RedisOptions> = {},
): Redis | Cluster | null => {
  const azureManagedRedisConfigError = validateAzureManagedRedisConfig();
  if (azureManagedRedisConfigError) {
    logger.error(azureManagedRedisConfigError);
    return null;
  }

  if (
    env.REDIS_CLUSTER_ENABLED === "true" &&
    env.REDIS_SENTINEL_ENABLED === "true"
  ) {
    logger.error(
      "Invalid Redis configuration: REDIS_CLUSTER_ENABLED and REDIS_SENTINEL_ENABLED cannot both be true",
    );
    return null;
  }

  let instance: Redis | Cluster | null = null;

  if (env.REDIS_CLUSTER_ENABLED === "true") {
    instance = createRedisClusterInstance(additionalOptions);
  } else if (env.REDIS_SENTINEL_ENABLED === "true") {
    instance = createRedisSentinelInstance(additionalOptions);
  } else {
    const tlsOptions = buildTlsOptions();

    instance = env.REDIS_CONNECTION_STRING
      ? new Redis(env.REDIS_CONNECTION_STRING, {
          username: getRedisUsername(),
          password: getRedisPassword(),
          ...defaultRedisOptions,
          ...additionalOptions,
          ...tlsOptions,
        })
      : env.REDIS_HOST
        ? new Redis({
            host: String(env.REDIS_HOST),
            port: Number(env.REDIS_PORT),
            username: getRedisUsername(),
            password: getRedisPassword(),
            ...defaultRedisOptions,
            ...additionalOptions,
            ...tlsOptions,
          })
        : null;

    instance?.on("error", (error) => {
      logger.error("Redis error", error);
    });
  }

  if (instance && isAzureManagedRedisAuthEnabled) {
    registerAzureManagedRedisClient(instance);
  }

  return instance;
};

/**
 * Get the queue prefix for BullMQ cluster compatibility
 * In cluster mode, uses hash tags to ensure queue keys are on the same node
 * In single-node mode, returns the configured prefix or undefined
 */
export const getQueuePrefix = (queueName: string): string | undefined => {
  const redisKeyPrefix = env.REDIS_KEY_PREFIX;

  if (env.REDIS_CLUSTER_ENABLED === "true" || isAzureManagedRedisAuthEnabled) {
    // Use hash tags for Redis cluster compatibility
    // This ensures all keys for a queue are placed on the same hash slot
    // Format: {prefix:queueName} ensures all keys land on same slot
    return redisKeyPrefix
      ? `{${redisKeyPrefix}:${queueName}}`
      : `{${queueName}}`;
  }

  // Non-cluster mode: Return prefix or undefined
  return redisKeyPrefix ?? undefined;
};

/**
 * Execute multiple Redis DEL operations safely in cluster mode
 */
export const safeMultiDel = async (
  redis: Redis | Cluster | null,
  keys: string[],
): Promise<void> => {
  if (!redis || keys.length === 0) return;

  if (env.REDIS_CLUSTER_ENABLED === "true" || isAzureManagedRedisAuthEnabled) {
    // In cluster mode, delete keys in separate commands to avoid CROSSSLOT errors
    await Promise.all(keys.map(async (key: string) => redis.del(key)));
  } else {
    // In single-node mode, can delete all keys at once
    await redis.del(keys);
  }
};

const scanKeysForNode = async (
  client: Redis,
  pattern: string,
  collector: Set<string>,
) => {
  let cursor = "0";

  do {
    const [nextCursor, keys]: [string, string[]] = await client.scan(
      cursor,
      "MATCH",
      pattern,
      "COUNT",
      REDIS_SCAN_COUNT,
    );

    keys.forEach((key) => collector.add(key));
    cursor = nextCursor;
  } while (cursor !== "0");
};

export const scanKeys = async (
  redis: Redis | Cluster | null,
  pattern: string,
): Promise<string[]> => {
  if (!redis) return [];

  const collectedKeys = new Set<string>();

  if (env.REDIS_CLUSTER_ENABLED === "true") {
    await Promise.all(
      (redis as Cluster)
        .nodes("master")
        .map((node) => scanKeysForNode(node, pattern, collectedKeys)),
    );
  } else {
    await scanKeysForNode(redis as Redis, pattern, collectedKeys);
  }

  return Array.from(collectedKeys);
};

const createRedisClient = () => {
  try {
    return createNewRedisInstance({
      keyPrefix: env.REDIS_KEY_PREFIX ?? undefined,
    });
  } catch (e) {
    logger.error("Failed to connect to redis", e);
    return null;
  }
};

declare global {
  var redis: undefined | ReturnType<typeof createRedisClient>;
}

export const redis = globalThis.redis ?? createRedisClient();

if (env.NODE_ENV !== "production") globalThis.redis = redis;
