import { apiRequest, csrfHeaders } from "./client";

export type TaskStatus = "todo" | "in_progress" | "done";
export type TaskPriority = "low" | "medium" | "high";

export interface TaskAssignee {
  id: number;
  name: string;
}

export interface Task {
  id: number;
  project_id: number;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  assignee_id: number | null;
  assignee: TaskAssignee | null;
  created_at: string;
  updated_at: string;
}

export interface TaskInput {
  title: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  due_date?: string | null;
  assignee_id?: number | null;
}

export interface TaskComment {
  id: number;
  task_id: number;
  author: TaskAssignee;
  body: string;
  can_manage: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskActivity {
  id: number;
  workspace_id: number;
  project_id: number;
  task_id: number | null;
  actor: TaskAssignee | null;
  event_type:
    | "task_created"
    | "task_title_changed"
    | "task_description_changed"
    | "task_status_changed"
    | "task_priority_changed"
    | "task_assignee_changed"
    | "task_due_date_changed"
    | "task_deleted";
  data: Record<string, string | boolean | null>;
  created_at: string;
}

export const taskApi = {
  async list(workspaceId: number, projectId: number) {
    return apiRequest<{ tasks: Task[]; assignees: TaskAssignee[] }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks`,
      { cache: "no-store" },
    );
  },

  async create(workspaceId: number, projectId: number, input: TaskInput) {
    return apiRequest<{ task: Task }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks`,
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
    taskId: number,
    input: Partial<TaskInput>,
  ) {
    return apiRequest<{ task: Task }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks/${taskId}`,
      {
        method: "PATCH",
        headers: await csrfHeaders(),
        body: JSON.stringify(input),
      },
    );
  },

  async delete(workspaceId: number, projectId: number, taskId: number) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks/${taskId}`,
      {
        method: "DELETE",
        headers: await csrfHeaders(),
      },
    );
  },

  async listComments(workspaceId: number, projectId: number, taskId: number) {
    return apiRequest<{ comments: TaskComment[] }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks/${taskId}/comments`,
      { cache: "no-store" },
    );
  },

  async createComment(
    workspaceId: number,
    projectId: number,
    taskId: number,
    body: string,
  ) {
    return apiRequest<{ comment: TaskComment }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks/${taskId}/comments`,
      {
        method: "POST",
        headers: await csrfHeaders(),
        body: JSON.stringify({ body }),
      },
    );
  },

  async updateComment(
    workspaceId: number,
    projectId: number,
    taskId: number,
    commentId: number,
    body: string,
  ) {
    return apiRequest<{ comment: TaskComment }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks/${taskId}/comments/${commentId}`,
      {
        method: "PATCH",
        headers: await csrfHeaders(),
        body: JSON.stringify({ body }),
      },
    );
  },

  async deleteComment(
    workspaceId: number,
    projectId: number,
    taskId: number,
    commentId: number,
  ) {
    return apiRequest<{ status: "ok"; message: string }>(
      `/workspaces/${workspaceId}/projects/${projectId}/tasks/${taskId}/comments/${commentId}`,
      {
        method: "DELETE",
        headers: await csrfHeaders(),
      },
    );
  },

  async listActivity(workspaceId: number, projectId: number, taskId?: number) {
    const query = taskId === undefined ? "" : `?task_id=${taskId}`;
    return apiRequest<{ activities: TaskActivity[]; limit: number; offset: number }>(
      `/workspaces/${workspaceId}/projects/${projectId}/activity${query}`,
      { cache: "no-store" },
    );
  },
};
