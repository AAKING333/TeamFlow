import { afterEach, describe, expect, it, vi } from "vitest";

import { projectApi } from "./projects";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("project API client", () => {
  it("loads projects for the workspace in the request path", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return jsonResponse({
          projects: [
            {
              id: 1,
              workspace_id: 4,
              name: "Roadmap",
              description: null,
              created_at: "2026-10-11T00:00:00+00:00",
              updated_at: "2026-10-11T00:00:00+00:00",
            },
          ],
        });
      }),
    );

    const response = await projectApi.list(4);

    expect(response.projects[0].workspace_id).toBe(4);
    expect(calls[0].url).toMatch(/\/workspaces\/4\/projects$/);
    expect(calls[0].init?.credentials).toBe("include");
  });

  it("obtains a CSRF token before creating a project", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url.endsWith("/auth/csrf")) {
          return jsonResponse({ csrf_token: "project-csrf" });
        }
        return jsonResponse({
          project: {
            id: 2,
            workspace_id: 9,
            name: "Launch",
            description: null,
            created_at: "2026-10-11T00:00:00+00:00",
            updated_at: "2026-10-11T00:00:00+00:00",
          },
        });
      }),
    );

    const response = await projectApi.create(9, { name: "Launch" });

    expect(response.project.workspace_id).toBe(9);
    expect(calls[0].url).toMatch(/\/auth\/csrf$/);
    expect(calls[1].url).toMatch(/\/workspaces\/9\/projects$/);
    expect(calls[1].init?.method).toBe("POST");
    expect(new Headers(calls[1].init?.headers).get("X-CSRF-Token")).toBe(
      "project-csrf",
    );
  });
});
