import { apiRequest, csrfHeaders } from "./client";

export interface Notification {
  id: number;
  type: "task_assigned" | "task_comment";
  message: string;
  payload: Record<string, never>;
  workspace_id: number;
  project_id: number | null;
  task_id: number | null;
  created_at: string;
  read_at: string | null;
}

export const notificationApi = {
  list(limit = 25, offset = 0) {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return apiRequest<{
      notifications: Notification[];
      unread_count: number;
      limit: number;
      offset: number;
    }>(`/notifications?${query}`, { cache: "no-store" });
  },

  async markRead(notificationId: number) {
    return apiRequest<{ notification: Notification; unread_count: number }>(
      `/notifications/${notificationId}/read`,
      { method: "POST", headers: await csrfHeaders() },
    );
  },

  async markAllRead() {
    return apiRequest<{ status: "ok"; unread_count: number }>(
      "/notifications/read-all",
      { method: "POST", headers: await csrfHeaders() },
    );
  },
};
