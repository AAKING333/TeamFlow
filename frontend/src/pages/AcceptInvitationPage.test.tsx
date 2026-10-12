import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { AcceptInvitationPage } from "./AcceptInvitationPage";

const { workspaceApi, useAuth } = vi.hoisted(() => ({
  workspaceApi: { acceptInvitation: vi.fn() },
  useAuth: vi.fn(),
}));

vi.mock("../api/workspaces", () => ({ workspaceApi }));
vi.mock("../auth/AuthContext", () => ({ useAuth }));

function LoginState() {
  const location = useLocation();
  return <p>{JSON.stringify(location.state)}</p>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/accept-invitation" element={<AcceptInvitationPage />} />
        <Route path="/login" element={<LoginState />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("invitation acceptance screen", () => {
  it("accepts the invitation and clears the in-memory token", async () => {
    useAuth.mockReturnValue({
      user: { id: 7, name: "Invitee", email: "invitee@example.test" },
      loading: false,
    });
    workspaceApi.acceptInvitation.mockResolvedValue({
      status: "ok",
      message: "Accepted.",
      workspace_id: 4,
    });

    renderAt("/accept-invitation?token=single-use-secret");
    fireEvent.click(await screen.findByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByText(/Invitation accepted/)).toBeVisible();
    expect(workspaceApi.acceptInvitation).toHaveBeenCalledWith("single-use-secret");
    expect(screen.queryByRole("button", { name: "Accept invitation" })).not.toBeInTheDocument();
  });

  it("explains an invited-account mismatch without discarding the link", async () => {
    useAuth.mockReturnValue({
      user: { id: 8, name: "Different account", email: "other@example.test" },
      loading: false,
    });
    workspaceApi.acceptInvitation.mockRejectedValue(
      new ApiError("Mismatch.", 403, "invitation_email_mismatch"),
    );

    renderAt("/accept-invitation?token=one-time");
    fireEvent.click(await screen.findByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign in with the invited email.",
    );
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeVisible();
  });

  it("asks unauthenticated visitors to sign in and preserves the invitation in navigation state", async () => {
    useAuth.mockReturnValue({ user: null, loading: false });
    renderAt("/accept-invitation?token=one-time");

    fireEvent.click(await screen.findByRole("link", { name: "Sign in" }));
    expect(await screen.findByText(/accept-invitation/)).toHaveTextContent(
      "?token=one-time",
    );
  });
});
