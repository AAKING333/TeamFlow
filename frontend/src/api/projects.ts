import { apiRequest, csrfHeaders } from "./client";

export interface Project {
  id: number;
  workspace_id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export const projectApi = {
  async list(workspaceId: number) {
    return apiRequest<{ projects: Project[] }>(
      `/workspaces/${workspaceId}/projects`,
      { cache: "no-store" },
    );
  },

  async get(workspaceId: number, projectId: number) {
    return apiRequest<{ project: Project }>(
      `/workspaces/${workspaceId}/projects/${projectId}`,
      { cache: "no-store" },
    );
  },

  async create(
    workspaceId: number,
    input: { name: string; description?: string },
  ) {
    return apiRequest<{ project: Project }>(
      `/workspaces/${workspaceId}/projects`,
      {
        method: "POST",
        headers: await csrfHeaders(),
        body: JSON.stringify(input),
      },
    );
  },

  async update(
    workspaceId: number,
    projectId: number,
    input: { name?: string; description?: string | null },
  ) {
    return apiRequest<{ project: Project }>(
      `/workspaces/${workspaceId}/projects/${projectId}`,
      {
        method: "PATCH",
        headers: await csrfHeaders(),
        body: JSON.stringify(input),
      },
    );
  },

  async delete(workspaceId: number, projectId: number) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}/projects/${projectId}`,
      {
        method: "DELETE",
        headers: await csrfHeaders(),
      },
    );
  },
};
