import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace, WorkspaceInvitation, WorkspaceMember } from "../api/workspaces";
import { WorkspaceMembers } from "./WorkspaceMembers";

const { workspaceApi, useAuth } = vi.hoisted(() => ({
  workspaceApi: {
    listMembers: vi.fn(),
    listInvitations: vi.fn(),
    invite: vi.fn(),
    changeMemberRole: vi.fn(),
    removeMember: vi.fn(),
    revokeInvitation: vi.fn(),
    getDevelopmentInvitationLink: vi.fn(),
    leaveWorkspace: vi.fn(),
  },
  useAuth: vi.fn(),
}));

vi.mock("../api/workspaces", () => ({ workspaceApi }));
vi.mock("../auth/AuthContext", () => ({ useAuth }));

function makeWorkspace(role: Workspace["role"] = "owner"): Workspace {
  return {
    id: 4,
    name: "Research",
    owner_id: 1,
    role,
    created_at: "2026-10-12T00:00:00+00:00",
    updated_at: "2026-10-12T00:00:00+00:00",
  };
}

const members: WorkspaceMember[] = [
  { user_id: 1, name: "Owner", email: "owner@example.test", role: "owner" },
  { user_id: 2, name: "Member", email: "member@example.test", role: "member" },
  { user_id: 3, name: "Admin", email: "admin@example.test", role: "admin" },
];

const invitations: WorkspaceInvitation[] = [
  {
    id: 5,
    workspace_id: 4,
    email: "pending@example.test",
    role: "member",
    inviter: { id: 1, name: "Owner" },
    status: "pending",
    created_at: "2026-10-12T00:00:00+00:00",
    expires_at: "2026-10-19T00:00:00+00:00",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  useAuth.mockReturnValue({
    user: { id: 1, name: "Owner", email: "owner@example.test" },
  });
  workspaceApi.listMembers.mockResolvedValue({ members });
  workspaceApi.listInvitations.mockResolvedValue({ invitations });
  workspaceApi.invite.mockResolvedValue({
    invitation: invitations[0],
    delivery_status: "development_outbox",
    message: "No email was sent.",
  });
  workspaceApi.changeMemberRole.mockResolvedValue({
    member: { ...members[1], role: "admin" },
  });
  workspaceApi.removeMember.mockResolvedValue({ status: "ok", message: "Removed." });
  workspaceApi.revokeInvitation.mockResolvedValue({ status: "ok", message: "Revoked." });
  workspaceApi.getDevelopmentInvitationLink.mockResolvedValue({
    invitation_url: "http://localhost:5173/accept-invitation?token=secret",
  });
  workspaceApi.leaveWorkspace.mockResolvedValue({ status: "ok", message: "Left." });
});

afterEach(() => cleanup());

describe("workspace member management", () => {
  it("creates invitations, changes roles, removes members, revokes and retrieves links", async () => {
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("member@example.test")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: " invited@example.test " },
    });
    fireEvent.change(screen.getByLabelText("Workspace role"), {
      target: { value: "admin" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText("No email was sent.")).toBeVisible();
    expect(workspaceApi.invite).toHaveBeenCalledWith(4, "invited@example.test", "admin");

    fireEvent.change(screen.getAllByLabelText("Role")[0], {
      target: { value: "admin" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Save role" })[0]);
    await waitFor(() =>
      expect(workspaceApi.changeMemberRole).toHaveBeenCalledWith(4, 2, "admin"),
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await waitFor(() => expect(workspaceApi.removeMember).toHaveBeenCalledWith(4, 2));

    fireEvent.click(screen.getByRole("button", { name: "Get local test link" }));
    expect(await screen.findByLabelText("One-time local invitation link")).toHaveValue(
      "http://localhost:5173/accept-invitation?token=secret",
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear link" }));
    expect(screen.queryByLabelText("One-time local invitation link")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(workspaceApi.revokeInvitation).toHaveBeenCalledWith(4, 5));
  });

  it("limits admins to member invitations/removals and allows non-owners to leave", async () => {
    useAuth.mockReturnValue({
      user: { id: 3, name: "Admin", email: "admin@example.test" },
    });
    workspaceApi.listMembers.mockResolvedValue({
      members: members.map(({ email: _email, ...member }) => member),
    });
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("admin")}
        onMembershipChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("Members")).toBeVisible();
    expect(screen.queryByText("admin@example.test")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Admin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save role" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Leave workspace" }));
    await waitFor(() => expect(workspaceApi.leaveWorkspace).toHaveBeenCalledWith(4));
  });

  it("shows load errors and provides a retry action", async () => {
    workspaceApi.listMembers
      .mockRejectedValueOnce(new Error("Member service unavailable."))
      .mockResolvedValueOnce({ members, invitations });

    render(
      <WorkspaceMembers
        workspace={makeWorkspace()}
        onMembershipChanged={vi.fn()}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Member service unavailable.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("member@example.test")).toBeVisible();
  });
});
