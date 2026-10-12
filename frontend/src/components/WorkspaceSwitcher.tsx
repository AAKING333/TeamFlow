import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { workspaceApi, type Workspace } from "../api/workspaces";
import { ProjectPanel } from "./ProjectPanel";
import { WorkspaceMembers } from "./WorkspaceMembers";

function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Workspaces could not be loaded. Try again.";
}

export function WorkspaceSwitcher() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [notificationTarget, setNotificationTarget] = useState<{
    workspaceId: number | null;
    projectId: number | null;
    taskId: number | null;
  }>({ workspaceId: null, projectId: null, taskId: null });
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showMembers, setShowMembers] = useState(false);

  const loadWorkspaces = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await workspaceApi.list();
      setWorkspaces(response.workspaces);
      setSelectedId((currentId) =>
        response.workspaces.some((workspace) => String(workspace.id) === currentId)
          ? currentId
          : String(response.workspaces[0]?.id ?? ""),
      );
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    const workspaceId = Number(searchParams.get("workspace"));
    if (!Number.isInteger(workspaceId) || workspaceId < 1) return;

    const projectId = Number(searchParams.get("project"));
    const taskId = Number(searchParams.get("task"));
    setNotificationTarget({
      workspaceId,
      projectId: Number.isInteger(projectId) && projectId > 0 ? projectId : null,
      taskId: Number.isInteger(taskId) && taskId > 0 ? taskId : null,
    });
    if (workspaces.some((workspace) => workspace.id === workspaceId)) {
      setSelectedId(String(workspaceId));
    }
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams, workspaces]);

  useEffect(() => {
    if (workspaces.some((workspace) => workspace.id === notificationTarget.workspaceId)) {
      setSelectedId(String(notificationTarget.workspaceId));
    }
  }, [notificationTarget.workspaceId, workspaces]);

  const selectedWorkspace = workspaces.find(
    (workspace) => String(workspace.id) === selectedId,
  );

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = workspaceName.trim();
    setNameError(null);
    setRequestError(null);

    if (!normalizedName) {
      setNameError("Enter a workspace name.");
      return;
    }
    if (normalizedName.length > 120) {
      setNameError("Workspace names must be 120 characters or fewer.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await workspaceApi.create(normalizedName);
      setWorkspaces((current) => [...current, response.workspace]);
      setSelectedId(String(response.workspace.id));
      setWorkspaceName("");
    } catch (error) {
      if (error instanceof ApiError && error.fields?.name) {
        setNameError(error.fields.name);
      } else {
        setRequestError(errorMessage(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="workspace-card" aria-labelledby="workspace-heading">
      <div>
        <p className="eyebrow">WORKSPACES</p>
        <h2 id="workspace-heading">Your workspaces</h2>
      </div>

      {loading ? (
        <p role="status">Loading workspaces…</p>
      ) : loadError ? (
        <div>
          <p className="error-banner" role="alert">
            {loadError}
          </p>
          <button className="quiet-button" onClick={() => void loadWorkspaces()} type="button">
            Try again
          </button>
        </div>
      ) : (
        <>
          {workspaces.length > 0 ? (
            <>
            <div className="workspace-selection">
              <label htmlFor="workspace-selector">Current workspace</label>
              <select
                id="workspace-selector"
                value={selectedId}
                onChange={(event) => {
                  setSelectedId(event.target.value);
                  setNotificationTarget({
                    workspaceId: null,
                    projectId: null,
                    taskId: null,
                  });
                }}
              >
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.name}
                  </option>
                ))}
              </select>
              {selectedWorkspace && (
                <p role="status">
                  {selectedWorkspace.name} · {selectedWorkspace.role}
                </p>
              )}
            </div>
            {selectedWorkspace && (
              <>
                <button
                  className="quiet-button"
                  onClick={() => setShowMembers((current) => !current)}
                  type="button"
                >
                  {showMembers ? "Close member management" : "Manage members"}
                </button>
                {showMembers && (
                  <WorkspaceMembers
                    key={selectedWorkspace.id}
                    workspace={selectedWorkspace}
                    onMembershipChanged={() => void loadWorkspaces()}
                  />
                )}
              </>
            )}
            </>
          ) : (
            <p className="workspace-empty">
              No workspaces yet. Create one to get started.
            </p>
          )}

          <ProjectPanel
            workspace={selectedWorkspace ?? null}
            targetProjectId={notificationTarget.projectId}
            targetTaskId={notificationTarget.taskId}
          />

          <form className="workspace-create-form" onSubmit={handleCreate} noValidate>
            <label htmlFor="workspace-name">New workspace name</label>
            <input
              id="workspace-name"
              autoComplete="off"
              maxLength={120}
              value={workspaceName}
              onChange={(event) => setWorkspaceName(event.target.value)}
              aria-invalid={nameError ? true : undefined}
              aria-describedby={nameError ? "workspace-name-error" : undefined}
            />
            {nameError && (
              <p className="field-error" id="workspace-name-error">
                {nameError}
              </p>
            )}
            {requestError && (
              <p className="error-banner" role="alert">
                {requestError}
              </p>
            )}
            <button
              className="primary-button"
              disabled={submitting}
              type="submit"
            >
              {submitting ? "Creating workspace…" : "Create workspace"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
