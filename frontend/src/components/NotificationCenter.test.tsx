import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationCenter } from "./NotificationCenter";

const { notificationApi } = vi.hoisted(() => ({
  notificationApi: {
    list: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
}));

vi.mock("../api/notifications", () => ({ notificationApi }));

function makeNotification(id: number, readAt: string | null = null) {
  return {
    id,
    type: "task_assigned" as const,
    message: "You were assigned to a task.",
    payload: {},
    workspace_id: 2,
    project_id: 3,
    task_id: 4,
    created_at: "2026-10-12T10:00:00+00:00",
    read_at: readAt,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  notificationApi.list.mockResolvedValue({
    notifications: [],
    unread_count: 0,
    limit: 25,
    offset: 0,
  });
});

afterEach(() => {
  cleanup();
});

describe("notification center", () => {
  it("loads an unread badge and marks one notification read", async () => {
    const item = makeNotification(5);
    notificationApi.list.mockResolvedValue({
      notifications: [item],
      unread_count: 1,
      limit: 25,
      offset: 0,
    });
    notificationApi.markRead.mockResolvedValue({
      notification: { ...item, read_at: "2026-10-12T11:00:00+00:00" },
      unread_count: 0,
    });

    render(<NotificationCenter onNavigate={vi.fn()} />);
    const toggle = await screen.findByRole("button", {
      name: "Notifications, 1 unread",
    });
    fireEvent.click(toggle);
    fireEvent.click(await screen.findByRole("button", { name: "Mark read" }));

    expect(notificationApi.markRead).toHaveBeenCalledWith(5);
    expect(
      await screen.findByRole("button", { name: "Notifications" }),
    ).toBeVisible();
  });

  it("opens the related resource and marks the notification read", async () => {
    const item = makeNotification(6);
    const onNavigate = vi.fn();
    notificationApi.list.mockResolvedValue({
      notifications: [item],
      unread_count: 1,
      limit: 25,
      offset: 0,
    });
    notificationApi.markRead.mockResolvedValue({
      notification: { ...item, read_at: "2026-10-12T11:00:00+00:00" },
      unread_count: 0,
    });

    render(<NotificationCenter onNavigate={onNavigate} />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    fireEvent.click(await screen.findByRole("button", { name: /assigned to a task/ }));

    await waitFor(() => {
      expect(notificationApi.markRead).toHaveBeenCalledWith(6);
      expect(onNavigate).toHaveBeenCalledWith(item);
    });
  });

  it("marks all notifications as read", async () => {
    const item = makeNotification(7);
    notificationApi.list.mockResolvedValue({
      notifications: [item],
      unread_count: 1,
      limit: 25,
      offset: 0,
    });
    notificationApi.markAllRead.mockResolvedValue({ status: "ok", unread_count: 0 });

    render(<NotificationCenter onNavigate={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));

    expect(notificationApi.markAllRead).toHaveBeenCalledOnce();
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeVisible();
  });

  it("shows empty, loading, and retryable error states", async () => {
    let resolveList:
      | ((value: {
          notifications: ReturnType<typeof makeNotification>[];
          unread_count: number;
          limit: number;
          offset: number;
        }) => void)
      | undefined;
    notificationApi.list
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveList = resolve;
        }),
      )
      .mockRejectedValueOnce(new Error("Notification service unavailable."))
      .mockResolvedValueOnce({
        notifications: [],
        unread_count: 0,
        limit: 25,
        offset: 0,
      });

    render(<NotificationCenter onNavigate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Loading notifications");
    resolveList?.({ notifications: [], unread_count: 0, limit: 25, offset: 0 });
    expect(await screen.findByText("You’re all caught up.")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Notification service unavailable.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("You’re all caught up.")).toBeVisible();
  });
});
