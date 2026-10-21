import { afterEach, describe, expect, it, vi } from "vitest";

import { workspaceApi } from "./workspaces";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("workspace API client", () => {
  it("exposes the safe error code and misconfiguration reason of delivery failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).endsWith("/auth/csrf")
          ? jsonResponse({ csrf_token: "invite-csrf" })
          : new Response(
              JSON.stringify({
                error: "invitation_delivery_rejected",
                message: "Invitation email delivery is misconfigured on the server.",
                delivery_status: "rejected",
                reason: "misconfigured",
              }),
              { status: 502, headers: { "Content-Type": "application/json" } },
            ),
      ),
    );

    await expect(workspaceApi.invite(4, "invitee@example.test", "member")).rejects.toMatchObject({
      status: 502,
      code: "invitation_delivery_rejected",
      reason: "misconfigured",
    });
  });

  it("uses credentialed requests and fetches a CSRF token before creation", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url.endsWith("/auth/csrf")) {
          return jsonResponse({ csrf_token: "workspace-csrf" });
        }
        if (url.endsWith("/workspaces")) {
          return jsonResponse({
            workspace: {
              id: 3,
              name: "Research",
              owner_id: 5,
              role: "owner",
              created_at: "2026-10-11T00:00:00+00:00",
              updated_at: "2026-10-11T00:00:00+00:00",
            },
          });
        }
        throw new Error(`Unexpected API request: ${url}`);
      }),
    );

    const response = await workspaceApi.create("Research");

    expect(response.workspace.name).toBe("Research");
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toMatch(/\/auth\/csrf$/);
    expect(calls[1].url).toMatch(/\/workspaces$/);
    expect(calls[1].init?.method).toBe("POST");
    expect(calls[1].init?.credentials).toBe("include");
    expect(new Headers(calls[1].init?.headers).get("X-CSRF-Token")).toBe(
      "workspace-csrf",
    );
    expect(calls[1].init?.body).toBe(JSON.stringify({ name: "Research" }));
  });

  it("protects invitation acceptance and membership role changes with CSRF", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        return url.endsWith("/auth/csrf")
          ? jsonResponse({ csrf_token: "membership-csrf" })
          : jsonResponse({ status: "ok", message: "Done.", workspace_id: 4 });
      }),
    );

    await workspaceApi.acceptInvitation("one-time-token");
    await workspaceApi.changeMemberRole(4, 8, "admin");
    await workspaceApi.removeMember(4, 8);
    await workspaceApi.leaveWorkspace(4);

    const mutations = calls.filter((call) => !call.url.endsWith("/auth/csrf"));
    expect(mutations.map(({ url }) => url)).toEqual([
      expect.stringMatching(/\/invitations\/accept$/),
      expect.stringMatching(/\/workspaces\/4\/members\/8$/),
      expect.stringMatching(/\/workspaces\/4\/members\/8$/),
      expect.stringMatching(/\/workspaces\/4\/leave$/),
    ]);
    expect(mutations.map(({ init }) => init?.method)).toEqual([
      "POST",
      "PATCH",
      "DELETE",
      "POST",
    ]);
    expect(mutations.every(({ init }) =>
      new Headers(init?.headers).get("X-CSRF-Token") === "membership-csrf",
    )).toBe(true);
    expect(calls.find(({ url }) => url.endsWith("/invitations/accept"))?.init?.body).toBe(
      JSON.stringify({ token: "one-time-token" }),
    );
    expect(calls.every(({ init }) => init?.credentials === "include")).toBe(true);
  });

  it("creates invitations without including token material in client API types", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        return url.endsWith("/auth/csrf")
          ? jsonResponse({ csrf_token: "invite-csrf" })
          : jsonResponse({
              invitation: {
                id: 2,
                workspace_id: 4,
                email: "new@example.test",
                role: "member",
                inviter: null,
                status: "pending",
                delivery_status: "development_outbox",
                created_at: "2026-10-12T00:00:00+00:00",
                expires_at: "2026-10-19T00:00:00+00:00",
              },
              delivery_status: "development_outbox",
              message: "No email was sent.",
            });
      }),
    );

    const result = await workspaceApi.invite(4, "new@example.test", "member");
    expect(result.invitation.email).toBe("new@example.test");
    expect(calls[1].url).toMatch(/\/workspaces\/4\/invitations$/);
    expect(calls[1].init?.method).toBe("POST");
    expect(calls[1].init?.body).toBe(
      JSON.stringify({ email: "new@example.test", role: "member" }),
    );

    await workspaceApi.resendInvitation(4, 2);
    const resend = calls[calls.length - 1];
    expect(resend.url).toMatch(/\/workspaces\/4\/invitations\/2\/resend$/);
    expect(resend.init?.method).toBe("POST");
    expect(resend.init?.body).toBeUndefined();
    expect(new Headers(resend.init?.headers).get("X-CSRF-Token")).toBe("invite-csrf");
  });
});
