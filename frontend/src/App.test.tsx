import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "./auth/AuthContext";
import { App } from "./App";

const profile = {
  id: 42,
  name: "Ada Lovelace",
  email: "ada@example.test",
  created_at: "2026-01-01T00:00:00+00:00",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderApp(initialEntry = "/login") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <App />
      </MemoryRouter>
    </AuthProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("authentication flow", () => {
  it("registers, logs in, loads the protected profile, and logs out with CSRF", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    let authenticated = false;
    let csrfCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url.endsWith("/auth/csrf")) {
          csrfCount += 1;
          return jsonResponse({ csrf_token: `csrf-${csrfCount}` });
        }
        if (url.endsWith("/auth/register")) {
          return jsonResponse({ status: "created", user: profile }, 201);
        }
        if (url.endsWith("/auth/login")) {
          authenticated = true;
          return jsonResponse({ status: "ok", user: profile });
        }
        if (url.endsWith("/auth/me")) {
          return authenticated
            ? jsonResponse({ user: profile })
            : jsonResponse(
                { error: "authentication_failed", message: "Sign in required." },
                401,
              );
        }
        if (url.endsWith("/workspaces")) {
          return jsonResponse({ workspaces: [] });
        }
        if (url.includes("/notifications?")) {
          return jsonResponse({
            notifications: [],
            unread_count: 0,
            limit: 25,
            offset: 0,
          });
        }
        if (url.endsWith("/auth/logout")) {
          authenticated = false;
          return jsonResponse({ status: "ok", message: "Logged out." });
        }
        throw new Error(`Unexpected API request: ${url}`);
      }),
    );

    renderApp();
    await screen.findByRole("heading", { name: "Sign in to TeamFlow" });
    fireEvent.click(screen.getByRole("link", { name: "Create an account" }));

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Ada Lovelace" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "ada@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "a-valid-password" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "a-valid-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await screen.findByText("Your account is ready. Sign in to continue.");
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "ada@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "a-valid-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Welcome, Ada." })).toBeVisible();
    expect(screen.getByText("ada@example.test")).toBeVisible();
    expect(calls.filter(({ url }) => url.endsWith("/auth/csrf"))).toHaveLength(2);

    for (const call of calls) {
      expect(call.init?.credentials).toBe("include");
    }
    const registration = calls.find(({ url }) => url.endsWith("/auth/register"));
    const login = calls.find(({ url }) => url.endsWith("/auth/login"));
    expect(new Headers(registration?.init?.headers).get("X-CSRF-Token")).toBe(
      "csrf-1",
    );
    expect(new Headers(login?.init?.headers).get("X-CSRF-Token")).toBe("csrf-2");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Sign in to TeamFlow" }),
      ).toBeVisible(),
    );
    const logout = calls.find(({ url }) => url.endsWith("/auth/logout"));
    expect(new Headers(logout?.init?.headers).get("X-CSRF-Token")).toBe("csrf-3");
    expect(calls.filter(({ url }) => url.endsWith("/auth/csrf"))).toHaveLength(3);
  });

  it("shows accessible client-side validation without sending invalid input", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderApp();

    fireEvent.click(await screen.findByRole("link", { name: "Create an account" }));
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Enter your name.")).toBeVisible();
    expect(screen.getByText("Enter a valid email address.")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows backend validation messages on the matching field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/auth/me")) {
          return jsonResponse({ error: "authentication_failed" }, 401);
        }
        if (String(input).endsWith("/auth/csrf")) {
          return jsonResponse({ csrf_token: "csrf-test" });
        }
        return jsonResponse(
          {
            error: "email_already_registered",
            message: "An account with this email already exists.",
            fields: { email: "This email is already registered." },
          },
          409,
        );
      }),
    );

    renderApp();
    fireEvent.click(await screen.findByRole("link", { name: "Create an account" }));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Ada Lovelace" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "ada@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "a-valid-password" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "a-valid-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(
      await screen.findByText("This email is already registered."),
    ).toBeVisible();
  });

  it("treats an unauthenticated account response as signed out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          { error: "authentication_failed", message: "Sign in required." },
          401,
        ),
      ),
    );
    renderApp("/");

    expect(
      await screen.findByRole("heading", { name: "Sign in to TeamFlow" }),
    ).toBeVisible();
    expect(
      screen.queryByText(
        "TeamFlow could not reach the server. Check that the backend is running and try again.",
      ),
    ).not.toBeInTheDocument();
  });

  it("shows the account load error when the account request is rejected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    renderApp("/");

    expect(
      await screen.findByText(
        "TeamFlow could not reach the server. Check that the backend is running and try again.",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("Refresh the page to retry loading your account."),
    ).toBeVisible();
  });

  it("redirects an unauthenticated visit to the protected route to sign-in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          { error: "authentication_failed", message: "Sign in required." },
          401,
        ),
      ),
    );
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/app"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "Sign in to TeamFlow" }),
    ).toBeVisible();
  });
});
