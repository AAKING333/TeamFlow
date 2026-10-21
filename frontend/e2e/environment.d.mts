export const RUNNER_ENVIRONMENT_ALLOWLIST: string[];
export const SERVER_ENVIRONMENT_ALLOWLIST: string[];
export const MAIL_ENVIRONMENT_NAMES: string[];
export function pickEnvironment(
  source: Record<string, string | undefined>,
  names: string[],
): Record<string, string>;
export function buildRunnerEnvironment(
  source: Record<string, string | undefined>,
): Record<string, string>;
export function buildFrontendServerEnvironment(
  source: Record<string, string | undefined>,
): Record<string, string>;
export function buildBackendServerEnvironment(
  source: Record<string, string | undefined>,
  databaseUrl: string,
): Record<string, string>;
