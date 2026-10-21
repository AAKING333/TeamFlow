import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
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
    resendInvitation: vi.fn(),
    getDevelopmentInvitationLink: vi.fn(),
    leaveWorkspace: vi.fn(),
  },
  useAuth: vi.fn(),
}));

vi.mock("../api/workspaces", () => ({ workspaceApi }));
vi.mock("../auth/AuthContext", () => ({ useAuth }));

function runtimeInvitationUrl() {
  const url = new URL("http://localhost:5173/accept-invitation");
  const token = `opaque-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  url.searchParams.set("token", token);
  return url.toString();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

let developmentInvitationUrl = "";

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
    delivery_status: "development_outbox",
    created_at: "2026-10-12T00:00:00+00:00",
    expires_at: "2026-10-19T00:00:00+00:00",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  developmentInvitationUrl = runtimeInvitationUrl();
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
  workspaceApi.resendInvitation.mockResolvedValue({
    invitation: invitations[0],
    delivery_status: "development_outbox",
    message: "No email was sent.",
  });
  workspaceApi.getDevelopmentInvitationLink.mockResolvedValue({
    invitation_url: developmentInvitationUrl,
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
    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));
    await waitFor(() => expect(workspaceApi.removeMember).toHaveBeenCalledWith(4, 2));

    fireEvent.click(screen.getByRole("button", { name: "Retry email" }));
    await waitFor(() =>
      expect(workspaceApi.resendInvitation).toHaveBeenCalledWith(4, 5),
    );

    fireEvent.click(screen.getByRole("button", { name: "Get local test link" }));
    expect(await screen.findByLabelText("One-time local invitation link")).toHaveValue(
      developmentInvitationUrl,
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear link" }));
    expect(screen.queryByLabelText("One-time local invitation link")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Local link already retrieved" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    fireEvent.click(screen.getByRole("button", { name: "Revoke invitation" }));
    await waitFor(() => expect(workspaceApi.revokeInvitation).toHaveBeenCalledWith(4, 5));
  }, 10000);

  it("restores the local-link action after resending a consumed invitation", async () => {
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.click(screen.getByRole("button", { name: "Get local test link" }));
    expect(await screen.findByLabelText("One-time local invitation link")).toBeVisible();
    expect(screen.getByRole("button", { name: "Local link already retrieved" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry email" }));
    await waitFor(() =>
      expect(workspaceApi.resendInvitation).toHaveBeenCalledWith(4, 5),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Get local test link" })).toBeVisible(),
    );
    expect(screen.queryByLabelText("One-time local invitation link")).not.toBeInTheDocument();
  });

  it("discards a local-link response from before resend starts", async () => {
    const linkRequest = deferred<{ invitation_url: string }>();
    const resendRequest = deferred<{
      invitation: WorkspaceInvitation;
      delivery_status: "development_outbox";
      message: string;
    }>();
    workspaceApi.getDevelopmentInvitationLink.mockReturnValueOnce(linkRequest.promise);
    workspaceApi.resendInvitation.mockReturnValueOnce(resendRequest.promise);

    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    const localLinkButton = screen.getByRole("button", { name: "Get local test link" });
    fireEvent.click(localLinkButton);
    const retryButton = screen.getByRole("button", { name: "Retry email" });
    fireEvent.click(retryButton);

    expect(screen.getByRole("button", { name: "Retrying email…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Get local test link" })).toBeDisabled();
    linkRequest.resolve({ invitation_url: developmentInvitationUrl });
    await waitFor(() =>
      expect(screen.queryByLabelText("One-time local invitation link")).not.toBeInTheDocument(),
    );

    resendRequest.resolve({
      invitation: invitations[0],
      delivery_status: "development_outbox",
      message: "No email was sent.",
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Get local test link" })).toBeEnabled(),
    );
    expect(screen.queryByLabelText("One-time local invitation link")).not.toBeInTheDocument();
  });

  it("shows provider delivery failures without a success message", async () => {
    workspaceApi.invite.mockRejectedValueOnce(
      new ApiError(
        "The email provider rejected this invitation.",
        502,
        "invitation_delivery_rejected",
      ),
    );
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "rejected@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(
      await screen.findByText(/email provider rejected this invitation/i),
    ).toBeVisible();
    expect(screen.queryByRole("status", { name: /Invitation created/i })).not.toBeInTheDocument();
  });

  it("makes a truthful email-server claim after the provider accepts an invitation", async () => {
    workspaceApi.invite.mockResolvedValueOnce({
      invitation: { ...invitations[0], delivery_status: "accepted" },
      delivery_status: "accepted",
      message: "Invitation created. The email provider accepted the message for processing.",
    });
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "accepted@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(await screen.findByText(/handed to the email server/i)).toBeVisible();
    expect(screen.getByText(/ask the recipient to check their spam folder/i)).toBeVisible();
    expect(screen.queryByText(/delivered to/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no email was sent/i)).not.toBeInTheDocument();
  });

  it("tells the user no email was sent when only the development outbox is configured", async () => {
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "outbox@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(
      await screen.findByText(/no email provider configured \(local development outbox\)/i),
    ).toBeVisible();
    expect(screen.queryByText(/handed to the email server/i)).not.toBeInTheDocument();
  });

  it("explains a server-side email misconfiguration without exposing details", async () => {
    workspaceApi.invite.mockRejectedValueOnce(
      new ApiError(
        "Invitation email delivery is misconfigured on the server.",
        502,
        "invitation_delivery_rejected",
        undefined,
        "misconfigured",
      ),
    );
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "misconfigured@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(await screen.findByText(/email delivery is misconfigured on the server/i)).toBeVisible();
    expect(screen.queryByText(/handed to the email server/i)).not.toBeInTheDocument();
    expect(workspaceApi.listInvitations).toHaveBeenCalledTimes(2);
  });

  it("shows the accepted-by-email-server notice after a successful retry", async () => {
    workspaceApi.resendInvitation.mockResolvedValueOnce({
      invitation: { ...invitations[0], delivery_status: "accepted" },
      delivery_status: "accepted",
      message: "Invitation resent. The email provider accepted the message for processing.",
    });
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.click(screen.getByRole("button", { name: "Retry email" }));

    expect(await screen.findByText(/handed to the email server/i)).toBeVisible();
    expect(workspaceApi.resendInvitation).toHaveBeenCalledWith(4, 5);
  });

  it("shows uncertain creation delivery without a success message", async () => {
    workspaceApi.invite.mockRejectedValueOnce(
      new ApiError(
        "Invitation email delivery was not confirmed.",
        503,
        "invitation_delivery_unavailable",
      ),
    );
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "unknown@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(await screen.findByText(/delivery was not confirmed/i)).toBeVisible();
    expect(screen.queryByText("No email was sent.")).not.toBeInTheDocument();
  });

  it("shows resend loading and rejection without claiming success", async () => {
    const resendRequest = deferred<{
      invitation: WorkspaceInvitation;
      delivery_status: "accepted";
      message: string;
    }>();
    workspaceApi.resendInvitation.mockReturnValueOnce(resendRequest.promise);
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.click(screen.getByRole("button", { name: "Retry email" }));
    expect(screen.getByRole("button", { name: "Retrying email…" })).toBeDisabled();
    resendRequest.reject(
      new ApiError(
        "The email provider rejected this invitation.",
        502,
        "invitation_delivery_rejected",
      ),
    );

    expect(
      await screen.findByText(/email provider rejected this invitation/i),
    ).toBeVisible();
    expect(screen.queryByText("No email was sent.")).not.toBeInTheDocument();
  });

  it("shows resend unavailable errors and refreshes invitation state", async () => {
    workspaceApi.resendInvitation.mockRejectedValueOnce(
      new ApiError(
        "Invitation email delivery was not confirmed.",
        503,
        "invitation_delivery_unavailable",
      ),
    );
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    fireEvent.click(screen.getByRole("button", { name: "Retry email" }));

    expect(await screen.findByText(/delivery was not confirmed/i)).toBeVisible();
    expect(workspaceApi.listInvitations).toHaveBeenCalledTimes(2);
  });

  it("restores focus to the remove trigger after a successful confirmation", async () => {
    render(
      <WorkspaceMembers
        workspace={makeWorkspace("owner")}
        onMembershipChanged={vi.fn()}
      />,
    );

    await screen.findByText("member@example.test");
    const removeButton = screen.getAllByRole("button", { name: "Remove" })[0];
    removeButton.focus();
    fireEvent.click(removeButton);
    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));

    await waitFor(() => {
      expect(workspaceApi.removeMember).toHaveBeenCalledWith(4, 2);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(document.activeElement).toBe(removeButton);
    });
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
    fireEvent.click(screen.getAllByRole("button", { name: "Leave workspace" })[1]);
    await waitFor(() => expect(workspaceApi.leaveWorkspace).toHaveBeenCalledWith(4));
  });

  it("gives a useful message for a server error and keeps members visible when invitations fail", async () => {
    workspaceApi.listInvitations
      .mockRejectedValueOnce(
        new ApiError("An unexpected error occurred.", 500, "internal_server_error"),
      )
      .mockResolvedValueOnce({ invitations });

    render(
      <WorkspaceMembers
        workspace={makeWorkspace()}
        onMembershipChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("member@example.test")).toBeVisible();
    expect(await screen.findByRole("alert")).toHaveTextContent(/flask db upgrade/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/Pending invitations could not be loaded/);
    expect(screen.queryByText("No pending invitations.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("pending@example.test")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains a permission failure when members cannot be loaded", async () => {
    workspaceApi.listMembers.mockRejectedValueOnce(
      new ApiError("Workspace administrator access is required.", 403, "permission_denied"),
    );

    render(
      <WorkspaceMembers
        workspace={makeWorkspace("member")}
        onMembershipChanged={vi.fn()}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to view workspace members.",
    );
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
