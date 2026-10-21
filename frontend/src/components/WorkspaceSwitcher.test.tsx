import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

const { workspaceApi, projectApi, taskApi } = vi.hoisted(() => ({
  workspaceApi: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    listMembers: vi.fn(),
    transferOwnership: vi.fn(),
    delete: vi.fn(),
  },
  projectApi: { list: vi.fn() },
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

vi.mock("../api/workspaces", () => ({ workspaceApi }));
vi.mock("../api/projects", () => ({ projectApi }));
vi.mock("../api/tasks", () => ({ taskApi }));

function makeWorkspace(
  id: number,
  name: string,
  role: "owner" | "admin" | "member" = "owner",
) {
  return {
    id,
    name,
    owner_id: 1,
    role,
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  projectApi.list.mockResolvedValue({ projects: [] });
  taskApi.list.mockResolvedValue({ tasks: [], assignees: [] });
  taskApi.listComments.mockResolvedValue({ comments: [] });
  taskApi.listActivity.mockResolvedValue({ activities: [] });
});

afterEach(() => {
  cleanup();
});

function renderSwitcher(initialEntry = "/app") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <WorkspaceSwitcher />
    </MemoryRouter>,
  );
}

describe("workspace selection", () => {
  it("shows loading state and selects the first loaded workspace", async () => {
    let resolveList: ((value: { workspaces: ReturnType<typeof makeWorkspace>[] }) => void) | undefined;
    workspaceApi.list.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );

    renderSwitcher();
    expect(screen.getByRole("status")).toHaveTextContent("Loading workspaces");

    resolveList?.({ workspaces: [makeWorkspace(1, "Research")] });

    expect(await screen.findByLabelText("Current workspace")).toHaveValue("1");
    expect(screen.getByRole("status")).toHaveTextContent("Research · owner");
  });

  it("shows the empty state and creates and selects a workspace", async () => {
    workspaceApi.list.mockResolvedValue({ workspaces: [] });
    workspaceApi.create.mockResolvedValue({
      workspace: makeWorkspace(7, "Design"),
    });

    renderSwitcher();
    expect(
      await screen.findByText("No workspaces yet. Create one to get started."),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(await screen.findByText("Enter a workspace name.")).toBeVisible();
    expect(workspaceApi.create).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("New workspace name"), {
      target: { value: "  Design  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    expect(await screen.findByLabelText("Current workspace")).toHaveValue("7");
    expect(screen.getByRole("status")).toHaveTextContent("Design · owner");
    expect(workspaceApi.create).toHaveBeenCalledWith("Design");
  });

  it("surfaces load errors and allows retrying", async () => {
    workspaceApi.list
      .mockRejectedValueOnce(new Error("Workspace service unavailable."))
      .mockResolvedValueOnce({ workspaces: [makeWorkspace(2, "Recovery")] });

    renderSwitcher();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Workspace service unavailable.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Current workspace")).toHaveValue("2"),
    );
    expect(workspaceApi.list).toHaveBeenCalledTimes(2);
  });

  it("switches the selected workspace", async () => {
    workspaceApi.list.mockResolvedValue({
      workspaces: [
        makeWorkspace(1, "Research", "owner"),
        makeWorkspace(2, "Design", "member"),
      ],
    });
    projectApi.list.mockImplementation(async (workspaceId: number) => ({
      projects: [
        {
          id: workspaceId * 10,
          workspace_id: workspaceId,
          name: `Project ${workspaceId}`,
          description: null,
          created_at: "2026-10-11T00:00:00+00:00",
          updated_at: "2026-10-11T00:00:00+00:00",
        },
      ],
    }));

    renderSwitcher();
    const selector = await screen.findByLabelText("Current workspace");
    await waitFor(() => expect(selector).toHaveValue("1"));
    expect(await screen.findByRole("heading", { name: "Project 1" })).toBeVisible();

    fireEvent.change(selector, { target: { value: "2" } });

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Design · member"),
    );
    expect(await screen.findByRole("heading", { name: "Project 2" })).toBeVisible();
    expect(projectApi.list).toHaveBeenNthCalledWith(1, 1);
    expect(projectApi.list).toHaveBeenNthCalledWith(2, 2);
  });

  it("does not request the previous project under the new workspace", async () => {
    workspaceApi.list.mockResolvedValue({
      workspaces: [makeWorkspace(1, "Research"), makeWorkspace(2, "Design")],
    });
    projectApi.list.mockImplementation(async (workspaceId: number) => ({
      projects: [{
        id: workspaceId * 10,
        workspace_id: workspaceId,
        name: `Project ${workspaceId}`,
        description: null,
        created_at: "2026-10-11T00:00:00+00:00",
        updated_at: "2026-10-11T00:00:00+00:00",
      }],
    }));

    renderSwitcher();
    const selector = await screen.findByLabelText("Current workspace");
    await screen.findByRole("heading", { name: "Project 1" });
    fireEvent.change(selector, { target: { value: "2" } });
    await screen.findByRole("heading", { name: "Project 2" });

    expect(taskApi.list).not.toHaveBeenCalledWith(2, 10);
    expect(taskApi.listActivity).not.toHaveBeenCalledWith(2, 10);
    expect(taskApi.list).toHaveBeenCalledWith(2, 20);
  });


  it("opens the workspace, project, and task referenced by a notification", async () => {
    workspaceApi.list.mockResolvedValue({
      workspaces: [
        makeWorkspace(1, "Research"),
        makeWorkspace(2, "Design", "member"),
      ],
    });
    projectApi.list.mockImplementation(async (workspaceId: number) => ({
      projects: [
        {
          id: workspaceId * 10,
          workspace_id: workspaceId,
          name: `Project ${workspaceId}`,
          description: null,
          created_at: "2026-10-11T00:00:00+00:00",
          updated_at: "2026-10-11T00:00:00+00:00",
        },
      ],
    }));
    taskApi.list.mockResolvedValue({
      tasks: [
        {
          id: 30,
          project_id: 20,
          title: "Follow up on assignment",
          description: null,
          status: "todo",
          priority: "medium",
          due_date: null,
          assignee_id: null,
          assignee: null,
          created_at: "2026-10-11T00:00:00+00:00",
          updated_at: "2026-10-11T00:00:00+00:00",
        },
      ],
      assignees: [],
    });

    renderSwitcher("/app?workspace=2&project=20&task=30");

    await waitFor(() =>
      expect(screen.getByLabelText("Current workspace")).toHaveValue("2"),
    );
    expect(await screen.findByLabelText("Select a project")).toHaveValue("20");
    expect(await screen.findByLabelText("Title")).toHaveValue("Follow up on assignment");
  });

  it("focuses the workspace decision CTA through the mounted switcher form", async () => {
    workspaceApi.list.mockResolvedValue({ workspaces: [] });

    renderSwitcher();

    fireEvent.click(await screen.findByRole("button", { name: "Start workspace setup from overview" }));
    await waitFor(() => expect(screen.getByLabelText("New workspace name")).toHaveFocus());
    expect(workspaceApi.create).not.toHaveBeenCalled();
  });

  it("focuses the project decision CTA through the mounted project form", async () => {
    workspaceApi.list.mockResolvedValue({ workspaces: [makeWorkspace(1, "Research")] });
    projectApi.list.mockResolvedValue({ projects: [] });

    renderSwitcher();

    fireEvent.click(await screen.findByRole("button", { name: "Start project setup from overview" }));
    await waitFor(() => expect(screen.getByLabelText("New project name")).toHaveFocus());
    expect(projectApi.list).toHaveBeenCalledTimes(1);
  });

  it("focuses the task decision CTA through the mounted task form", async () => {
    workspaceApi.list.mockResolvedValue({ workspaces: [makeWorkspace(1, "Research")] });
    projectApi.list.mockResolvedValue({
      projects: [{
        id: 10,
        workspace_id: 1,
        name: "Roadmap",
        description: null,
        created_at: "2026-10-11T00:00:00+00:00",
        updated_at: "2026-10-11T00:00:00+00:00",
      }],
    });

    renderSwitcher();

    fireEvent.click(await screen.findByRole("button", { name: "New task" }));
    await waitFor(() => expect(screen.getByLabelText("New task")).toHaveFocus());
    expect(taskApi.create).not.toHaveBeenCalled();
  });
});
