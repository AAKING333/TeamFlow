import { apiRequest, csrfHeaders } from "./client";

export type WorkspaceRole = "owner" | "admin" | "member";

export interface Workspace {
  id: number;
  name: string;
  owner_id: number;
  role: WorkspaceRole;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceMember {
  user_id: number;
  name: string;
  email?: string;
  role: WorkspaceRole;
}

export interface WorkspaceInvitation {
  id: number;
  workspace_id: number;
  email: string;
  role: Exclude<WorkspaceRole, "owner">;
  inviter: { id: number; name: string } | null;
  status: "pending" | "accepted" | "revoked" | "expired";
  created_at: string;
  expires_at: string;
}

export const workspaceApi = {
  async list() {
    return apiRequest<{ workspaces: Workspace[] }>("/workspaces", {
      cache: "no-store",
    });
  },

  async create(name: string) {
    return apiRequest<{ workspace: Workspace }>("/workspaces", {
      method: "POST",
      headers: await csrfHeaders(),
      body: JSON.stringify({ name }),
    });
  },

  async get(workspaceId: number) {
    return apiRequest<{ workspace: Workspace }>(`/workspaces/${workspaceId}`, {
      cache: "no-store",
    });
  },

  async update(workspaceId: number, name: string) {
    return apiRequest<{ workspace: Workspace }>(`/workspaces/${workspaceId}`, {
      method: "PATCH",
      headers: await csrfHeaders(),
      body: JSON.stringify({ name }),
    });
  },

  async listMembers(workspaceId: number) {
    return apiRequest<{ members: WorkspaceMember[] }>(
      `/workspaces/${workspaceId}/members`,
      { cache: "no-store" },
    );
  },

  async invite(workspaceId: number, email: string, role: "admin" | "member") {
    return apiRequest<{
      invitation: WorkspaceInvitation;
      delivery_status: "not_configured" | "development_outbox";
      message: string;
    }>(`/workspaces/${workspaceId}/invitations`, {
      method: "POST",
      headers: await csrfHeaders(),
      body: JSON.stringify({ email, role }),
    });
  },

  async listInvitations(workspaceId: number) {
    return apiRequest<{ invitations: WorkspaceInvitation[] }>(
      `/workspaces/${workspaceId}/invitations`,
      { cache: "no-store" },
    );
  },

  async revokeInvitation(workspaceId: number, invitationId: number) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}/invitations/${invitationId}`,
      {
        method: "DELETE",
        headers: await csrfHeaders(),
      },
    );
  },

  async getDevelopmentInvitationLink(workspaceId: number, invitationId: number) {
    return apiRequest<{ invitation_url: string }>(
      `/workspaces/${workspaceId}/invitations/${invitationId}/development-link`,
      { cache: "no-store" },
    );
  },

  async acceptInvitation(token: string) {
    return apiRequest<{ status: "ok"; message: string; workspace_id: number }>(
      "/invitations/accept",
      {
        method: "POST",
        headers: await csrfHeaders(),
        body: JSON.stringify({ token }),
      },
    );
  },

  async changeMemberRole(
    workspaceId: number,
    userId: number,
    role: "admin" | "member",
  ) {
    return apiRequest<{ member: WorkspaceMember }>(
      `/workspaces/${workspaceId}/members/${userId}`,
      {
        method: "PATCH",
        headers: await csrfHeaders(),
        body: JSON.stringify({ role }),
      },
    );
  },

  async removeMember(workspaceId: number, userId: number) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}/members/${userId}`,
      {
        method: "DELETE",
        headers: await csrfHeaders(),
      },
    );
  },

  async leaveWorkspace(workspaceId: number) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}/leave`,
      {
        method: "POST",
        headers: await csrfHeaders(),
      },
    );
  },

  async transferOwnership(workspaceId: number, userId: number) {
    return apiRequest<{ workspace: Workspace }>(
      `/workspaces/${workspaceId}/transfer-ownership`,
      {
        method: "POST",
        headers: await csrfHeaders(),
        body: JSON.stringify({ user_id: userId }),
      },
    );
  },

  async delete(workspaceId: number) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}`,
      {
        method: "DELETE",
        headers: await csrfHeaders(),
      },
    );
  },
};
