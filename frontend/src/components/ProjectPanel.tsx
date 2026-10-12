import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import { projectApi, type Project } from "../api/projects";
import type { Workspace } from "../api/workspaces";
import { TaskBoard } from "./TaskBoard";

interface ProjectPanelProps {
  workspace: Workspace | null;
  targetProjectId?: number | null;
  targetTaskId?: number | null;
}

function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Projects could not be loaded. Try again.";
}

export function ProjectPanel({
  workspace,
  targetProjectId = null,
  targetTaskId = null,
}: ProjectPanelProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;

    if (!workspace) {
      setProjects([]);
      setSelectedProjectId(null);
      setLoading(false);
      setLoadError(null);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    setLoadError(null);
    setProjects([]);
    setSelectedProjectId(null);
    void projectApi
      .list(workspace.id)
      .then((response) => {
        if (active) {
          setProjects(response.projects);
          setSelectedProjectId(
            response.projects.some((project) => project.id === targetProjectId)
              ? targetProjectId
              : (response.projects[0]?.id ?? null),
          );
        }
      })
      .catch((error: unknown) => {
        if (active) setLoadError(errorMessage(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [workspace?.id]);

  const selectedProject = projects.find(
    (project) => project.id === selectedProjectId,
  );
  const canManageProjects =
    workspace?.role === "owner" || workspace?.role === "admin";

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
      const response = await projectApi.create(workspace.id, {
        name: normalizedName,
        ...(description.trim() ? { description: description.trim() } : {}),
      });
      setProjects((current) =>
        [...current, response.project].sort((left, right) =>
          left.name.localeCompare(right.name),
        ),
      );
      setSelectedProjectId(response.project.id);
      setName("");
      setDescription("");
    } catch (error) {
      if (error instanceof ApiError && error.fields?.name) {
        setFieldError(error.fields.name);
      } else {
        setRequestError(errorMessage(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!workspace) {
    return (
      <section className="project-card" aria-labelledby="projects-heading">
        <h2 id="projects-heading">Projects</h2>
        <p className="workspace-empty">Select or create a workspace to view projects.</p>
      </section>
    );
  }

  return (
    <section className="project-card" aria-labelledby="projects-heading">
      <div>
        <p className="eyebrow">PROJECTS · {workspace.name}</p>
        <h2 id="projects-heading">Workspace projects</h2>
      </div>

      {loading ? (
        <p role="status">Loading projects…</p>
      ) : loadError ? (
        <p className="error-banner" role="alert">
          {loadError}
        </p>
      ) : projects.length === 0 ? (
        <p className="workspace-empty">No projects in this workspace yet.</p>
      ) : (
        <div className="project-selection">
          <label htmlFor="project-selector">Select a project</label>
          <select
            id="project-selector"
            value={selectedProjectId ?? ""}
            onChange={(event) =>
              setSelectedProjectId(
                event.target.value ? Number(event.target.value) : null,
              )
            }
          >
            <option value="">Choose a project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          {selectedProject && (
            <article className="project-details" aria-label="Selected project">
              <h3>{selectedProject.name}</h3>
              <p>
                {selectedProject.description ?? "No project description provided."}
              </p>
            </article>
          )}
        </div>
      )}

      {selectedProject && !loadError && (
        <TaskBoard
          key={`${workspace.id}-${selectedProject.id}`}
          workspace={workspace}
          projectId={selectedProject.id}
          initialTaskId={targetTaskId}
        />
      )}

      {canManageProjects && !loadError && (
        <form className="project-create-form" onSubmit={handleCreate} noValidate>
          <label htmlFor="project-name">New project name</label>
          <input
            id="project-name"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? "project-name-error" : undefined}
          />
          {fieldError && (
            <p className="field-error" id="project-name-error">
              {fieldError}
            </p>
          )}
          <label htmlFor="project-description">Description (optional)</label>
          <textarea
            id="project-description"
            value={description}
            maxLength={2000}
            onChange={(event) => setDescription(event.target.value)}
          />
          {requestError && (
            <p className="error-banner" role="alert">
              {requestError}
            </p>
          )}
          <button className="primary-button" disabled={submitting} type="submit">
            {submitting ? "Creating project…" : "Create project"}
          </button>
        </form>
      )}
    </section>
  );
}
