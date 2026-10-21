import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace } from "../api/workspaces";
import { WorkspaceOverview } from "./WorkspaceOverview";

const { projectApi, taskApi } = vi.hoisted(() => ({
  projectApi: { list: vi.fn(), create: vi.fn() },
  taskApi: { list: vi.fn(), listActivity: vi.fn(), listComments: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), createComment: vi.fn(), updateComment: vi.fn(), deleteComment: vi.fn() },
}));
vi.mock("../api/projects", () => ({ projectApi }));
vi.mock("../api/tasks", () => ({ taskApi }));

const workspace: Workspace = { id: 1, name: "Research", owner_id: 1, role: "owner", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
const project = { id: 2, workspace_id: 1, name: "Roadmap", description: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
function task(id: number, title: string, due_date: string | null, status: "todo" | "in_progress" | "done" = "todo") {
  return { id, project_id: 2, title, description: null, status, priority: "medium" as const, due_date, assignee_id: null, assignee: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
}

beforeEach(() => {
  vi.clearAllMocks();
  projectApi.list.mockResolvedValue({ projects: [project] });
  taskApi.list.mockResolvedValue({ tasks: [], assignees: [] });
  taskApi.listComments.mockResolvedValue({ comments: [] });
  taskApi.listActivity.mockResolvedValue({ activities: [] });
});
afterEach(() => cleanup());

describe("truthful workspace overview", () => {
  it("derives status, due-date, and project activity summaries from scoped responses", async () => {
    const today = new Date();
    const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    taskApi.list.mockResolvedValue({ tasks: [task(3, "Later", "2099-12-31", "done"), task(4, "Today", todayKey), task(5, "Earlier", "2000-01-01")], assignees: [] });
    taskApi.listActivity.mockResolvedValue({ activities: [{ id: 8, workspace_id: 1, project_id: 2, task_id: null, actor: { id: 1, name: "Ada" }, event_type: "task_created", data: {}, created_at: "2026-01-02T00:00:00Z" }] });

    render(<WorkspaceOverview workspace={workspace} workspaceCount={3} />);

    expect(await screen.findByLabelText("Your workspaces")).toHaveTextContent("3");
    expect(await screen.findByLabelText("Tasks by status")).toHaveTextContent("2 to do · 0 in progress · 1 done");
    expect(screen.getByRole("heading", { name: "Recent project activity" })).toBeVisible();
    expect(screen.getAllByText("Earlier").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Today").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Later").length).toBeGreaterThan(0);
    expect(taskApi.listActivity).toHaveBeenCalledWith(1, 2);
  });

  it("treats malformed top-level project data as unavailable instead of empty success", async () => {
    projectApi.list.mockResolvedValue({ projects: null });
    render(<WorkspaceOverview workspace={workspace} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Projects response was unavailable");
    expect(screen.queryByText("No projects in this workspace yet.")).not.toBeInTheDocument();
  });

  it("does not offer New task while the selected task scope is loading or failed", async () => {
    let rejectTasks: ((error: Error) => void) | undefined;
    taskApi.list.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectTasks = reject; }));
    render(<WorkspaceOverview workspace={workspace} workspaceCount={1} />);
    await waitFor(() => expect(taskApi.list).toHaveBeenCalledWith(1, 2));
    expect(screen.queryByRole("button", { name: "New task" })).not.toBeInTheDocument();
    rejectTasks?.(new Error("Tasks unavailable."));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tasks unavailable.");
    expect(screen.queryByRole("button", { name: "New task" })).not.toBeInTheDocument();
  });

  it("does not select a task when its notification project target is invalid", async () => {
    taskApi.list.mockResolvedValue({ tasks: [task(30, "Unrelated target", null)], assignees: [] });
    render(<WorkspaceOverview workspace={workspace} targetProjectId={999} targetTaskId={30} />);
    await waitFor(() => expect(taskApi.list).toHaveBeenCalledWith(1, 2));
    expect(await screen.findByText("Unrelated target")).toBeVisible();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
  });

  it("keeps the selected task details open when the task list refreshes", async () => {
    const assignedTask = {
      ...task(6, "Assigned task", null),
      assignee_id: 9,
      assignee: { id: 9, name: "Workspace Member" },
    };
    taskApi.list
      .mockResolvedValueOnce({ tasks: [assignedTask], assignees: [{ id: 9, name: "Workspace Member" }] })
      .mockResolvedValueOnce({ tasks: [assignedTask], assignees: [{ id: 9, name: "Workspace Member" }] });

    render(<WorkspaceOverview workspace={workspace} />);

    fireEvent.click(await screen.findByRole("button", { name: /Assigned task/ }));
    expect(await screen.findByLabelText("Assignee")).toHaveValue("9");
    fireEvent.click(screen.getByRole("button", { name: "Refresh tasks" }));

    await waitFor(() => expect(taskApi.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByLabelText("Assignee")).toHaveValue("9");
  });

  it("reloads task data when a notification targets the current project", async () => {
    const notificationTask = task(31, "Notification task", null);
    taskApi.list
      .mockResolvedValueOnce({ tasks: [], assignees: [] })
      .mockResolvedValueOnce({ tasks: [notificationTask], assignees: [] });
    const { rerender } = render(<WorkspaceOverview workspace={workspace} />);

    expect(await screen.findByText("No tasks yet. Add a task to start the board.")).toBeVisible();
    rerender(
      <WorkspaceOverview
        workspace={workspace}
        targetProjectId={project.id}
        targetTaskId={notificationTask.id}
      />,
    );

    expect(await screen.findByLabelText("Title")).toHaveValue("Notification task");
    expect(taskApi.list).toHaveBeenCalledTimes(2);
  });

  it("uses the single contextual primary CTA to focus the registered project form", async () => {
    projectApi.list.mockResolvedValue({ projects: [] });
    let focusCallback: (() => void) | undefined;
    const register = vi.fn((_target: "workspace-name" | "project-name" | "task-title", callback: () => void) => {
      if (_target === "project-name") focusCallback = callback;
      return () => undefined;
    });
    const focusTarget = vi.fn(() => true);
    render(<WorkspaceOverview workspace={workspace} workspaceCount={1} registerFocusTarget={register} focusTarget={focusTarget} />);
    const cta = await screen.findByRole("button", { name: "Start project setup from overview" });
    expect(cta).toHaveClass("button-primary");
    fireEvent.click(cta);
    await waitFor(() => expect(focusTarget).toHaveBeenCalledWith("project-name"));
    expect(register).toHaveBeenCalledWith("project-name", expect.any(Function));
    expect(focusCallback).toBeDefined();
  });
});
