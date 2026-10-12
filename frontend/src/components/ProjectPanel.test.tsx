import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace } from "../api/workspaces";
import { ProjectPanel } from "./ProjectPanel";

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

beforeEach(() => {
  vi.clearAllMocks();
  taskApi.list.mockResolvedValue({ tasks: [], assignees: [] });
});

afterEach(() => {
  cleanup();
});

describe("workspace projects", () => {
  it("loads projects and displays the selected project details", async () => {
    projectApi.list.mockResolvedValue({
      projects: [makeProject(5, 1, "Roadmap")],
    });

    render(<ProjectPanel workspace={makeWorkspace(1, "Research")} />);

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

    render(<ProjectPanel workspace={makeWorkspace(1, "Research")} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading projects");
    resolveList?.({ projects: [] });
    expect(await screen.findByText("No projects in this workspace yet.")).toBeVisible();
  });

  it("shows an empty state and hides project creation for members", async () => {
    projectApi.list.mockResolvedValue({ projects: [] });

    render(<ProjectPanel workspace={makeWorkspace(1, "Research", "member")} />);

    expect(await screen.findByText("No projects in this workspace yet.")).toBeVisible();
    expect(screen.queryByLabelText("New project name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create project" })).not.toBeInTheDocument();
  });

  it("shows server errors without exposing administrative form controls", async () => {
    projectApi.list.mockRejectedValue(new Error("Projects are temporarily unavailable."));

    render(<ProjectPanel workspace={makeWorkspace(1, "Research", "member")} />);

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

    render(<ProjectPanel workspace={makeWorkspace(2, "Product", "admin")} />);
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

    render(<ProjectPanel workspace={makeWorkspace(1, "Research")} />);
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
      <ProjectPanel workspace={makeWorkspace(1, "Research")} />,
    );
    expect(await screen.findByRole("heading", { name: "Project 1" })).toBeVisible();

    rerender(<ProjectPanel workspace={makeWorkspace(2, "Product")} />);

    expect(await screen.findByRole("heading", { name: "Project 2" })).toBeVisible();
    await waitFor(() => expect(projectApi.list).toHaveBeenCalledTimes(2));
    expect(projectApi.list).toHaveBeenNthCalledWith(1, 1);
    expect(projectApi.list).toHaveBeenNthCalledWith(2, 2);
  });

  it("does not render project data when no workspace is selected", () => {
    render(<ProjectPanel workspace={null} />);

    expect(screen.getByText("Select or create a workspace to view projects.")).toBeVisible();
    expect(projectApi.list).not.toHaveBeenCalled();
  });
});
