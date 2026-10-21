import { useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import type { Project } from "../api/projects";
import type { Task, TaskActivity, TaskAssignee } from "../api/tasks";
import type { Workspace } from "../api/workspaces";
import { TaskBoard } from "./TaskBoard";
import type { FocusTarget, ProjectCreateInput, ScopeState } from "./WorkspaceOverview";

export interface ProjectPanelProps {
  workspace: Workspace | null;
  targetTaskId?: number | null;
  projects: Project[] | null;
  projectsState: ScopeState;
  selectedProjectId: number | null;
  onSelectProject: (projectId: number) => void;
  onCreateProject: (input: ProjectCreateInput) => Promise<Project>;
  onRetryProjects: () => void;
  registerFocusTarget?: (target: FocusTarget, focus: () => void) => () => void;
  tasks: Task[] | null;
  tasksState: ScopeState;
  assignees: TaskAssignee[] | null;
  selectedTaskId: number | null;
  onSelectTask: (taskId: number | null) => void;
  onTaskCreated: (task: Task) => void;
  onTaskUpdated: (task: Task) => void;
  onTaskDeleted: (taskId: number) => void;
  onRetryTasks: () => void;
  projectActivity?: TaskActivity[] | null;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Projects could not be loaded. Try again.";
}

export function ProjectPanel({
  workspace,
  targetTaskId = null,
  projects,
  projectsState,
  selectedProjectId,
  onSelectProject,
  onCreateProject,
  onRetryProjects,
  registerFocusTarget,
  tasks,
  tasksState,
  assignees,
  selectedTaskId,
  onSelectTask,
  onTaskCreated,
  onTaskUpdated,
  onTaskDeleted,
  onRetryTasks,
}: ProjectPanelProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const canManageProjects = workspace?.role === "owner" || workspace?.role === "admin";
  const selectedProject = projects?.find((project) => project.id === selectedProjectId);

  function registerName(element: HTMLInputElement | null) {
    if (!element || !registerFocusTarget) return undefined;
    return registerFocusTarget("project-name", () => element.focus());
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    setFieldError(null);
    setRequestError(null);
    if (!normalizedName) {
      setFieldError("Enter a project name.");
      return;
    }
    if (normalizedName.length > 120) {
      setFieldError("Project names must be 120 characters or fewer.");
      return;
    }
    if (!workspace) return;
    setSubmitting(true);
    try {
      await onCreateProject({
        name: normalizedName,
        ...(description.trim() ? { description: description.trim() } : {}),
      });
      setName("");
      setDescription("");
    } catch (error) {
      if (error instanceof ApiError && error.fields?.name) setFieldError(error.fields.name);
      else setRequestError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (!workspace) {
    return (
      <section id="projects-section" className="project-card" aria-labelledby="projects-heading">
        <h2 id="projects-heading">Projects</h2>
        <p className="workspace-empty">Select or create a workspace to view projects.</p>
      </section>
    );
  }

  return (
    <section id="projects-section" className="project-card" aria-labelledby="projects-heading">
      <div>
        <p className="eyebrow">PROJECTS · {workspace.name}</p>
        <h2 id="projects-heading">Workspace projects</h2>
      </div>
      {projectsState.status === "loading" ? (
        <p role="status">Loading projects…</p>
      ) : projectsState.status === "error" ? (
        <div>
          <p className="error-banner" role="alert">{projectsState.error ?? "Projects could not be loaded."}</p>
          <button className="quiet-button" type="button" onClick={onRetryProjects}>Try again</button>
        </div>
      ) : projects && projects.length === 0 ? (
        <p className="workspace-empty">No projects in this workspace yet.</p>
      ) : projects ? (
        <div className="project-selection">
          <label htmlFor="project-selector">Select a project</label>
          <select id="project-selector" value={selectedProjectId ?? ""} onChange={(event) => onSelectProject(Number(event.target.value))}>
            <option value="">Choose a project</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
          {selectedProject && (
            <article className="project-details" aria-label="Selected project">
              <h3>{selectedProject.name}</h3>
              <p>{selectedProject.description ?? "No project description provided."}</p>
            </article>
          )}
        </div>
      ) : null}

      {selectedProject && (
        <TaskBoard
          workspace={workspace}
          projectId={selectedProject.id}
          initialTaskId={targetTaskId}
          tasks={tasks}
          tasksState={tasksState}
          assignees={assignees}
          selectedTaskId={selectedTaskId}
          onSelectTask={onSelectTask}
          onTaskCreated={onTaskCreated}
          onTaskUpdated={onTaskUpdated}
          onTaskDeleted={onTaskDeleted}
          onRetryTasks={onRetryTasks}
          registerFocusTarget={registerFocusTarget}
        />
      )}

      {canManageProjects && projectsState.status !== "error" && (
        <form className="project-create-form" onSubmit={handleCreate} noValidate>
          <label htmlFor="project-name">New project name</label>
          <input
            ref={registerName}
            id="project-name"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? "project-name-error" : undefined}
          />
          {fieldError && <p className="field-error" id="project-name-error">{fieldError}</p>}
          <label htmlFor="project-description">Description (optional)</label>
          <textarea id="project-description" value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} />
          {requestError && <p className="error-banner" role="alert">{requestError}</p>}
          <button className="quiet-button" disabled={submitting} type="submit">{submitting ? "Creating project…" : "Create project"}</button>
        </form>
      )}
    </section>
  );
}
