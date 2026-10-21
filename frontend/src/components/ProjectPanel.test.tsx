import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Task } from "../api/tasks";
import type { Workspace } from "../api/workspaces";
import { WorkspaceOverview } from "./WorkspaceOverview";

const { projectApi, taskApi } = vi.hoisted(() => ({
  projectApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
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

vi.mock("../api/projects", () => ({ projectApi }));
vi.mock("../api/tasks", () => ({ taskApi }));

function makeWorkspace(
  id: number,
  name: string,
  role: "owner" | "admin" | "member" = "owner",
): Workspace {
  return {
    id,
    name,
    owner_id: 1,
    role,
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

function makeProject(id: number, workspaceId: number, name: string) {
  return {
    id,
    workspace_id: workspaceId,
    name,
    description: `${name} details`,
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

function makeTask(id: number, projectId: number, title: string): Task {
  return {
    id,
    project_id: projectId,
    title,
    description: null,
    status: "todo",
    priority: "medium",
    due_date: null,
    assignee_id: null,
    assignee: null,
    created_at: "2026-10-11T00:00:00+00:00",
    updated_at: "2026-10-11T00:00:00+00:00",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  taskApi.list.mockResolvedValue({ tasks: [], assignees: [] });
  taskApi.listComments.mockResolvedValue({ comments: [] });
  taskApi.listActivity.mockResolvedValue({ activities: [] });
});

afterEach(() => {
  cleanup();
});

describe("workspace projects", () => {
  it("loads projects and displays the selected project details", async () => {
    projectApi.list.mockResolvedValue({
      projects: [makeProject(5, 1, "Roadmap")],
    });

    render(<WorkspaceOverview workspace={makeWorkspace(1, "Research")} />);

    expect(await screen.findByRole("heading", { name: "Roadmap" })).toBeVisible();
    expect(screen.getByText("Roadmap details")).toBeVisible();
    expect(projectApi.list).toHaveBeenCalledWith(1);
  });

  it("shows loading while projects are fetched", async () => {
    let resolveList:
      | ((value: { projects: ReturnType<typeof makeProject>[] }) => void)
      | undefined;
    projectApi.list.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );

    render(<WorkspaceOverview workspace={makeWorkspace(1, "Research")} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading projects");
    resolveList?.({ projects: [] });
    expect(await screen.findByText("No projects in this workspace yet.")).toBeVisible();
  });

  it("shows an empty state and hides project creation for members", async () => {
    projectApi.list.mockResolvedValue({ projects: [] });

    render(<WorkspaceOverview workspace={makeWorkspace(1, "Research", "member")} />);

    expect(await screen.findByText("No projects in this workspace yet.")).toBeVisible();
    expect(screen.queryByLabelText("New project name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create project" })).not.toBeInTheDocument();
  });

  it("shows server errors without exposing administrative form controls", async () => {
    projectApi.list.mockRejectedValue(new Error("Projects are temporarily unavailable."));

    render(<WorkspaceOverview workspace={makeWorkspace(1, "Research", "member")} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Projects are temporarily unavailable.",
    );
    expect(screen.queryByLabelText("New project name")).not.toBeInTheDocument();
  });

  it("lets admins create projects and displays the created project", async () => {
    projectApi.list.mockResolvedValue({ projects: [] });
    projectApi.create.mockResolvedValue({
      project: makeProject(8, 2, "Launch"),
    });

    render(<WorkspaceOverview workspace={makeWorkspace(2, "Product", "admin")} />);
    await screen.findByText("No projects in this workspace yet.");
    fireEvent.change(screen.getByLabelText("New project name"), {
      target: { value: " Launch " },
    });
    fireEvent.change(screen.getByLabelText("Description (optional)"), {
      target: { value: "  Preparing the launch  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("heading", { name: "Launch" })).toBeVisible();
    expect(projectApi.create).toHaveBeenCalledWith(2, {
      name: "Launch",
      description: "Preparing the launch",
    });
  });

  it("validates project names before sending a request", async () => {
    projectApi.list.mockResolvedValue({ projects: [] });

    render(<WorkspaceOverview workspace={makeWorkspace(1, "Research")} />);
    await screen.findByText("No projects in this workspace yet.");
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByText("Enter a project name.")).toBeVisible();
    expect(projectApi.create).not.toHaveBeenCalled();
  });

  it("reloads project content when the selected workspace changes", async () => {
    projectApi.list.mockImplementation(async (workspaceId: number) => ({
      projects: [makeProject(workspaceId * 10, workspaceId, `Project ${workspaceId}`)],
    }));
    const { rerender } = render(
      <WorkspaceOverview workspace={makeWorkspace(1, "Research")} />,
    );
    expect(await screen.findByRole("heading", { name: "Project 1" })).toBeVisible();

    rerender(<WorkspaceOverview workspace={makeWorkspace(2, "Product")} />);

    expect(await screen.findByRole("heading", { name: "Project 2" })).toBeVisible();
    await waitFor(() => expect(projectApi.list).toHaveBeenCalledTimes(2));
    expect(projectApi.list).toHaveBeenNthCalledWith(1, 1);
    expect(projectApi.list).toHaveBeenNthCalledWith(2, 2);
  });

  it("updates notification targets within a workspace without reloading projects", async () => {
    const firstProject = makeProject(10, 1, "Project A");
    const secondProject = makeProject(20, 1, "Project B");
    projectApi.list.mockResolvedValue({ projects: [firstProject, secondProject] });
    taskApi.list.mockImplementation(async (_workspaceId: number, projectId: number) => ({
      tasks:
        projectId === firstProject.id
          ? [makeTask(101, firstProject.id, "Task A")]
          : [makeTask(202, secondProject.id, "Task B")],
      assignees: [],
    }));

    const { rerender } = render(
      <WorkspaceOverview
        workspace={makeWorkspace(1, "Research")}
        targetProjectId={firstProject.id}
        targetTaskId={101}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Project A" })).toBeVisible();
    expect(await screen.findByDisplayValue("Task A")).toBeVisible();
    expect(projectApi.list).toHaveBeenCalledTimes(1);

    rerender(
      <WorkspaceOverview
        workspace={makeWorkspace(1, "Research")}
        targetProjectId={secondProject.id}
        targetTaskId={202}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Project B" })).toBeVisible();
    expect(await screen.findByDisplayValue("Task B")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Select a project" })).toHaveValue("20");
    expect(projectApi.list).toHaveBeenCalledTimes(1);

    rerender(
      <WorkspaceOverview
        workspace={makeWorkspace(1, "Research")}
        targetProjectId={999}
        targetTaskId={999}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Select a project" })).toHaveValue("20");
      expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
    });
  });

  it("does not render project data when no workspace is selected", () => {
    render(<WorkspaceOverview workspace={null} />);

    expect(screen.getByText("Select or create a workspace to view projects.")).toBeVisible();
    expect(projectApi.list).not.toHaveBeenCalled();
  });
});
