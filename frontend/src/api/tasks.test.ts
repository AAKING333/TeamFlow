import { afterEach, describe, expect, it, vi } from "vitest";

import { taskApi } from "./tasks";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("task API client", () => {
  it("lists tasks under the selected workspace and project", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return jsonResponse({ tasks: [], assignees: [] });
      }),
    );

    const result = await taskApi.list(4, 9);

    expect(result.tasks).toEqual([]);
    expect(calls[0].url).toMatch(/\/workspaces\/4\/projects\/9\/tasks$/);
    expect(calls[0].init?.credentials).toBe("include");
  });

  it("fetches CSRF before creating a task", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        return url.endsWith("/auth/csrf")
          ? jsonResponse({ csrf_token: "task-csrf" })
          : jsonResponse({ task: { id: 1 } });
      }),
    );

    await taskApi.create(4, 9, { title: "Review" });

    expect(calls[0].url).toMatch(/\/auth\/csrf$/);
    expect(calls[1].init?.method).toBe("POST");
    expect(new Headers(calls[1].init?.headers).get("X-CSRF-Token")).toBe("task-csrf");
  });

  it("loads task comments and activity from the nested project routes", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init });
        return jsonResponse(
          String(input).includes("/comments")
            ? { comments: [] }
            : { activities: [], limit: 50, offset: 0 },
        );
      }),
    );

    await taskApi.listComments(4, 9, 12);
    await taskApi.listActivity(4, 9, 12);

    expect(calls[0].url).toMatch(/\/workspaces\/4\/projects\/9\/tasks\/12\/comments$/);
    expect(calls[1].url).toMatch(/\/workspaces\/4\/projects\/9\/activity\?task_id=12$/);
    expect(calls.every((call) => call.init?.credentials === "include")).toBe(true);
  });

  it("fetches CSRF and uses nested routes for comment mutations", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        return url.endsWith("/auth/csrf")
          ? jsonResponse({ csrf_token: "comment-csrf" })
          : jsonResponse({ comment: { id: 3 } });
      }),
    );

    await taskApi.createComment(4, 9, 12, "A note");
    await taskApi.updateComment(4, 9, 12, 3, "Updated note");
    await taskApi.deleteComment(4, 9, 12, 3);

    expect(calls.map(({ url }) => url)).toEqual([
      expect.stringMatching(/\/auth\/csrf$/),
      expect.stringMatching(/\/tasks\/12\/comments$/),
      expect.stringMatching(/\/auth\/csrf$/),
      expect.stringMatching(/\/tasks\/12\/comments\/3$/),
      expect.stringMatching(/\/auth\/csrf$/),
      expect.stringMatching(/\/tasks\/12\/comments\/3$/),
    ]);
    expect(calls[1].init?.method).toBe("POST");
    expect(calls[3].init?.method).toBe("PATCH");
    expect(calls[5].init?.method).toBe("DELETE");
    expect(new Headers(calls[1].init?.headers).get("X-CSRF-Token")).toBe("comment-csrf");
    expect(new Headers(calls[3].init?.headers).get("X-CSRF-Token")).toBe("comment-csrf");
    expect(new Headers(calls[5].init?.headers).get("X-CSRF-Token")).toBe("comment-csrf");
  });
});
