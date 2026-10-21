import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Task, TaskActivity, TaskComment } from "../api/tasks";
import type { Workspace } from "../api/workspaces";
import { TaskBoard } from "./TaskBoard";

const { taskApi } = vi.hoisted(() => ({
  taskApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    listComments: vi.fn(),
    createComment: vi.fn(),
    updateComment: vi.fn(),
    deleteComment: vi.fn(),
    listActivity: vi.fn(),
  },
}));

vi.mock("../api/tasks", () => ({ taskApi }));

function makeWorkspace(
  id: number,
  role: "owner" | "admin" | "member" = "owner",
): Workspace {
  return {
    id,
    name: `Workspace ${id}`,
    owner_id: 1,
    role,
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

function makeTask(
  id: number,
  projectId: number,
  title: string,
  status: Task["status"] = "todo",
): Task {
  return {
    id,
    project_id: projectId,
    title,
    description: null,
    status,
    priority: "high",
    due_date: null,
    assignee_id: 7,
    assignee: { id: 7, name: "Sam" },
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

function makeComment(
  id: number,
  taskId: number,
  body: string,
  canManage = false,
): TaskComment {
  return {
    id,
    task_id: taskId,
    author: { id: 7, name: "Sam" },
    body,
    can_manage: canManage,
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  taskApi.listComments.mockResolvedValue({ comments: [] });
  taskApi.listActivity.mockResolvedValue({ activities: [], limit: 50, offset: 0 });
});
afterEach(() => cleanup());

describe("project task board", () => {
  it("loads tasks into status columns with priority and assignee details", async () => {
    taskApi.list.mockResolvedValue({
      tasks: [makeTask(1, 4, "Review release", "in_progress")],
      assignees: [{ id: 7, name: "Sam" }],
    });

    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);

    expect(await screen.findByRole("button", { name: /Review release/ })).toBeVisible();
    expect(screen.getByText("high")).toBeVisible();
    expect(screen.getByText("Assigned to Sam")).toBeVisible();
    expect(taskApi.list).toHaveBeenCalledWith(2, 4);
  });

  it("shows the three empty columns and lets a member create a task", async () => {
    taskApi.list.mockResolvedValue({ tasks: [], assignees: [] });
    taskApi.create.mockResolvedValue({ task: makeTask(2, 4, "Write tests") });

    render(<TaskBoard workspace={makeWorkspace(2, "member")} projectId={4} />);

    expect(await screen.findByText("No tasks yet. Add a task to start the board.")).toBeVisible();
    expect(screen.getAllByText("No tasks")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    expect(await screen.findByText("Enter a task title.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("New task"), {
      target: { value: "  Write tests  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));

    expect(await screen.findByRole("button", { name: /Write tests/ })).toBeVisible();
    expect(taskApi.create).toHaveBeenCalledWith(2, 4, { title: "Write tests" });
  });

  it("updates status, priority, assignee, and title from task details", async () => {
    const existing = makeTask(1, 4, "Review release");
    taskApi.list.mockResolvedValue({
      tasks: [existing],
      assignees: [{ id: 7, name: "Sam" }, { id: 8, name: "Jo" }],
    });
    taskApi.update.mockImplementation(
      async (_workspaceId: number, _projectId: number, _taskId: number, input) => ({
        task: { ...existing, ...input, assignee: input.assignee_id === 8 ? { id: 8, name: "Jo" } : existing.assignee },
      }),
    );

    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Review release/ }));
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "done" },
    });
    await waitFor(() =>
      expect(taskApi.update).toHaveBeenCalledWith(2, 4, 1, { status: "done" }),
    );
    fireEvent.change(screen.getByLabelText("Priority"), {
      target: { value: "low" },
    });
    fireEvent.change(screen.getByLabelText("Assignee"), {
      target: { value: "8" },
    });
    await waitFor(() =>
      expect(taskApi.update).toHaveBeenCalledWith(2, 4, 1, { assignee_id: 8 }),
    );
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Release reviewed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(taskApi.update).toHaveBeenCalledWith(2, 4, 1, { title: "Release reviewed" }),
    );
    expect(taskApi.update).toHaveBeenCalledWith(2, 4, 1, { priority: "low" });
    expect(taskApi.update).toHaveBeenCalledWith(2, 4, 1, { assignee_id: 8 });
    expect(await screen.findByRole("status")).toHaveTextContent("Task changes saved.");
  });

  it("restores the server draft when Cancel changes is pressed", async () => {
    const existing = makeTask(1, 4, "Original title");
    taskApi.list.mockResolvedValue({ tasks: [existing], assignees: [] });
    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Original title/ }));
    const titleInput = screen.getByLabelText("Title");
    fireEvent.change(titleInput, { target: { value: "Unsaved title" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel changes" }));
    expect(titleInput).toHaveValue("Original title");
    expect(taskApi.update).not.toHaveBeenCalled();
  });

  it("retains edited draft values after a failed save", async () => {
    const existing = makeTask(1, 4, "Original title");
    taskApi.list.mockResolvedValue({ tasks: [existing], assignees: [] });
    taskApi.update.mockRejectedValue(new Error("Task save failed."));
    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Original title/ }));
    const titleInput = screen.getByLabelText("Title");
    fireEvent.change(titleInput, { target: { value: "Unsaved title" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Task save failed.");
    expect(titleInput).toHaveValue("Unsaved title");
  });

  it("shows load errors and retries", async () => {
    taskApi.list
      .mockRejectedValueOnce(new Error("Task service unavailable."))
      .mockResolvedValueOnce({ tasks: [], assignees: [] });

    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Task service unavailable.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No tasks yet. Add a task to start the board.")).toBeVisible();
    expect(taskApi.list).toHaveBeenCalledTimes(2);
  });

  it("loads the newly selected project without rendering the prior project's tasks", async () => {
    let resolveSecond: ((value: { tasks: Task[]; assignees: [] }) => void) | undefined;
    taskApi.list
      .mockResolvedValueOnce({
        tasks: [makeTask(1, 4, "Project 4 task")],
        assignees: [],
      })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
      );
    const { rerender } = render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    expect(await screen.findByRole("button", { name: /Project 4 task/ })).toBeVisible();

    rerender(<TaskBoard workspace={makeWorkspace(2)} projectId={5} />);
    expect(screen.queryByText("Project 4 task")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading tasks");
    resolveSecond?.({ tasks: [makeTask(2, 5, "Project 5 task")], assignees: [] });
    expect(await screen.findByRole("button", { name: /Project 5 task/ })).toBeVisible();
  });

  it("only offers task deletion to workspace admins and owners", async () => {
    taskApi.list.mockResolvedValue({
      tasks: [makeTask(1, 4, "Member task")],
      assignees: [],
    });
    const { rerender } = render(
      <TaskBoard workspace={makeWorkspace(2, "member")} projectId={4} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Member task/ }));
    expect(screen.queryByRole("button", { name: "Delete task" })).not.toBeInTheDocument();

    rerender(<TaskBoard workspace={makeWorkspace(2, "admin")} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Member task/ }));
    expect(screen.getByRole("button", { name: "Delete task" })).toBeVisible();
  });

  it("creates, edits, and deletes comments when the API grants management", async () => {
    const task = makeTask(1, 4, "Discuss release");
    const comment = makeComment(10, task.id, "Initial note", true);
    taskApi.list.mockResolvedValue({ tasks: [task], assignees: [] });
    taskApi.listComments.mockResolvedValue({ comments: [] });
    taskApi.createComment.mockResolvedValue({ comment });
    taskApi.updateComment.mockResolvedValue({
      comment: { ...comment, body: "Edited note" },
    });
    taskApi.deleteComment.mockResolvedValue({ status: "ok", message: "Comment deleted." });

    render(<TaskBoard workspace={makeWorkspace(2, "member")} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Discuss release/ }));

    fireEvent.change(await screen.findByLabelText("Add a comment"), {
      target: { value: " Initial note " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Post comment" }));
    expect(await screen.findByText("Initial note")).toBeVisible();
    expect(taskApi.createComment).toHaveBeenCalledWith(2, 4, 1, "Initial note");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Edit comment by Sam"), {
      target: { value: "Edited note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save comment" }));
    expect(await screen.findByText("Edited note", { selector: "p" })).toBeVisible();
    expect(taskApi.updateComment).toHaveBeenCalledWith(2, 4, 1, 10, "Edited note");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete comment" }));
    await waitFor(() =>
      expect(screen.queryByText("Edited note", { selector: "p" })).not.toBeInTheDocument(),
    );
    expect(taskApi.deleteComment).toHaveBeenCalledWith(2, 4, 1, 10);
  });

  it("shows comments to members without exposing edit controls for another author's comment", async () => {
    const task = makeTask(1, 4, "Member discussion");
    taskApi.list.mockResolvedValue({ tasks: [task], assignees: [] });
    taskApi.listComments.mockResolvedValue({
      comments: [makeComment(10, task.id, "Read-only note")],
    });

    render(<TaskBoard workspace={makeWorkspace(2, "member")} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Member discussion/ }));

    expect(await screen.findByText("Read-only note")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("shows discussion errors and retries comment and activity loading", async () => {
    const task = makeTask(1, 4, "Retry discussion");
    taskApi.list.mockResolvedValue({ tasks: [task], assignees: [] });
    taskApi.listComments
      .mockRejectedValueOnce(new Error("Discussion service unavailable."))
      .mockResolvedValueOnce({ comments: [] });

    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /Retry discussion/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Discussion service unavailable.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No comments yet.")).toBeVisible();
    expect(taskApi.listComments).toHaveBeenCalledTimes(2);
    expect(taskApi.listActivity).toHaveBeenCalledTimes(2);
  });

  it("clears selected-task comments and activity when switching tasks", async () => {
    const first = makeTask(1, 4, "First discussion");
    const second = makeTask(2, 4, "Second discussion");
    const activity: TaskActivity = {
      id: 20,
      workspace_id: 2,
      project_id: 4,
      task_id: first.id,
      actor: { id: 7, name: "Sam" },
      event_type: "task_created",
      data: {},
      created_at: "2026-10-11T00:00:00+00:00",
    };
    taskApi.list.mockResolvedValue({ tasks: [first, second], assignees: [] });
    taskApi.listComments.mockImplementation(async (_workspaceId, _projectId, taskId) => ({
      comments: taskId === first.id
        ? [makeComment(10, first.id, "First task comment")]
        : [makeComment(11, second.id, "Second task comment")],
    }));
    taskApi.listActivity.mockImplementation(async (_workspaceId, _projectId, taskId) => ({
      activities: taskId === first.id ? [activity] : [],
      limit: 50,
      offset: 0,
    }));

    render(<TaskBoard workspace={makeWorkspace(2)} projectId={4} />);
    fireEvent.click(await screen.findByRole("button", { name: /First discussion/ }));
    expect(await screen.findByText("First task comment")).toBeVisible();
    expect(screen.getByText("Sam created this task.")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Second discussion/ }));
    expect(await screen.findByText("Second task comment")).toBeVisible();
    expect(screen.queryByText("First task comment")).not.toBeInTheDocument();
    expect(screen.queryByText("Sam created this task.")).not.toBeInTheDocument();
  });
});
