import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import {
  taskApi,
  type TaskActivity,
  type TaskComment,
  type Task,
  type TaskInput,
  type TaskPriority,
  type TaskStatus,
  type TaskAssignee,
} from "../api/tasks";
import type { Workspace } from "../api/workspaces";

interface TaskBoardProps {
  workspace: Workspace;
  projectId: number;
  initialTaskId?: number | null;
}

const COLUMNS: { status: TaskStatus; label: string }[] = [
  { status: "todo", label: "To do" },
  { status: "in_progress", label: "In progress" },
  { status: "done", label: "Done" },
];

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Tasks could not be loaded.";
}

export function TaskBoard({
  workspace,
  projectId,
  initialTaskId = null,
}: TaskBoardProps) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [assignees, setAssignees] = useState<TaskAssignee[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [activity, setActivity] = useState<TaskActivity[]>([]);
  const [discussionLoading, setDiscussionLoading] = useState(false);
  const [discussionError, setDiscussionError] = useState<string | null>(null);
  const [commentBody, setCommentBody] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [commentSubmitting, setCommentSubmitting] = useState(false);
  const [editingCommentId, setEditingCommentId] = useState<number | null>(null);
  const [editingCommentBody, setEditingCommentBody] = useState("");
  const canDelete = workspace.role === "owner" || workspace.role === "admin";

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await taskApi.list(workspace.id, projectId);
      setTasks(result.tasks);
      setAssignees(result.assignees);
      setSelectedId((current) =>
        result.tasks.some((task) => task.id === current) ? current : null,
      );
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [projectId, workspace.id]);

  useEffect(() => {
    let active = true;
    setTasks([]);
    setAssignees([]);
    setSelectedId(null);
    setLoading(true);
    setLoadError(null);
    void taskApi
      .list(workspace.id, projectId)
      .then((result) => {
        if (!active) return;
        setTasks(result.tasks);
        setAssignees(result.assignees);
        setSelectedId(
          result.tasks.some((task) => task.id === initialTaskId) ? initialTaskId : null,
        );
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
  }, [initialTaskId, projectId, workspace.id]);

  const selected = tasks.find((task) => task.id === selectedId) ?? null;

  const loadDiscussion = useCallback(async () => {
    if (!selectedId) {
      setComments([]);
      setActivity([]);
      return;
    }
    setDiscussionLoading(true);
    setDiscussionError(null);
    try {
      const [commentResult, activityResult] = await Promise.all([
        taskApi.listComments(workspace.id, projectId, selectedId),
        taskApi.listActivity(workspace.id, projectId, selectedId),
      ]);
      setComments(commentResult.comments);
      setActivity(activityResult.activities);
    } catch (error) {
      setDiscussionError(errorMessage(error));
    } finally {
      setDiscussionLoading(false);
    }
  }, [projectId, selectedId, workspace.id]);

  useEffect(() => {
    let active = true;
    if (!selectedId) {
      setComments([]);
      setActivity([]);
      setDiscussionError(null);
      return;
    }
    setComments([]);
    setActivity([]);
    setDiscussionLoading(true);
    setDiscussionError(null);
    void Promise.all([
      taskApi.listComments(workspace.id, projectId, selectedId),
      taskApi.listActivity(workspace.id, projectId, selectedId),
    ])
      .then(([commentResult, activityResult]) => {
        if (!active) return;
        setComments(commentResult.comments);
        setActivity(activityResult.activities);
      })
      .catch((error: unknown) => {
        if (active) setDiscussionError(errorMessage(error));
      })
      .finally(() => {
        if (active) setDiscussionLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, selectedId, workspace.id]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTitle = title.trim();
    setCreateError(null);
    setRequestError(null);
    if (!normalizedTitle) {
      setCreateError("Enter a task title.");
      return;
    }
    if (normalizedTitle.length > 200) {
      setCreateError("Task titles must be 200 characters or fewer.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await taskApi.create(workspace.id, projectId, {
        title: normalizedTitle,
      });
      setTasks((current) => [...current, result.task]);
      setSelectedId(result.task.id);
      setTitle("");
    } catch (error) {
      if (error instanceof ApiError && error.fields?.title) {
        setCreateError(error.fields.title);
      } else {
        setRequestError(errorMessage(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function updateSelected(input: Partial<TaskInput>) {
    if (!selected) return;
    setRequestError(null);
    setSaving(true);
    try {
      const result = await taskApi.update(
        workspace.id,
        projectId,
        selected.id,
        input,
      );
      setTasks((current) =>
        current.map((task) => (task.id === result.task.id ? result.task : task)),
      );
    } catch (error) {
      setRequestError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function deleteSelected() {
    if (!selected) return;
    setRequestError(null);
    setSaving(true);
    try {
      await taskApi.delete(workspace.id, projectId, selected.id);
      setTasks((current) => current.filter((task) => task.id !== selected.id));
      setSelectedId(null);
    } catch (error) {
      setRequestError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function createComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = commentBody.trim();
    setCommentError(null);
    if (!body) {
      setCommentError("Enter a comment.");
      return;
    }
    if (body.length > 4000) {
      setCommentError("Comments must be 4000 characters or fewer.");
      return;
    }
    if (!selected) return;
    setCommentSubmitting(true);
    try {
      const result = await taskApi.createComment(
        workspace.id,
        projectId,
        selected.id,
        body,
      );
      setComments((current) => [...current, result.comment]);
      setCommentBody("");
    } catch (error) {
      setCommentError(errorMessage(error));
    } finally {
      setCommentSubmitting(false);
    }
  }

  async function saveComment(comment: TaskComment) {
    if (!selected) return;
    const body = editingCommentBody.trim();
    if (!body || body.length > 4000) {
      setDiscussionError("Comments must contain 1–4000 characters.");
      return;
    }
    try {
      const result = await taskApi.updateComment(
        workspace.id,
        projectId,
        selected.id,
        comment.id,
        body,
      );
      setComments((current) =>
        current.map((item) => (item.id === result.comment.id ? result.comment : item)),
      );
      setEditingCommentId(null);
      setDiscussionError(null);
    } catch (error) {
      setDiscussionError(errorMessage(error));
    }
  }

  async function deleteComment(comment: TaskComment) {
    if (!selected) return;
    try {
      await taskApi.deleteComment(workspace.id, projectId, selected.id, comment.id);
      setComments((current) => current.filter((item) => item.id !== comment.id));
      setDiscussionError(null);
    } catch (error) {
      setDiscussionError(errorMessage(error));
    }
  }

  function activityDescription(item: TaskActivity) {
    const actor = item.actor?.name ?? "A former user";
    const messages: Record<TaskActivity["event_type"], string> = {
      task_created: "created this task",
      task_title_changed: "changed the task title",
      task_description_changed: "updated the description",
      task_status_changed: `changed status from ${String(item.data.from)} to ${String(item.data.to)}`,
      task_priority_changed: `changed priority from ${String(item.data.from)} to ${String(item.data.to)}`,
      task_assignee_changed: item.data.assigned ? "assigned this task" : "unassigned this task",
      task_due_date_changed: "changed the due date",
      task_deleted: `deleted “${String(item.data.task_title)}”`,
    };
    return `${actor} ${messages[item.event_type]}.`;
  }

  return (
    <section className="task-board" aria-labelledby="task-board-heading">
      <div className="task-board-heading">
        <div>
          <p className="eyebrow">TASKS · {workspace.name}</p>
          <h3 id="task-board-heading">Project board</h3>
        </div>
        <button className="quiet-button" onClick={() => void reload()} type="button">
          Refresh tasks
        </button>
      </div>

      {loadError && (
        <div>
          <p className="error-banner" role="alert">{loadError}</p>
          <button className="quiet-button" onClick={() => void reload()} type="button">
            Try again
          </button>
        </div>
      )}
      {requestError && <p className="error-banner" role="alert">{requestError}</p>}

      <form className="task-create-form" onSubmit={handleCreate} noValidate>
        <label htmlFor="task-title">New task</label>
        <input
          id="task-title"
          value={title}
          maxLength={200}
          onChange={(event) => setTitle(event.target.value)}
          aria-invalid={createError ? true : undefined}
          aria-describedby={createError ? "task-title-error" : undefined}
        />
        {createError && <p className="field-error" id="task-title-error">{createError}</p>}
        <button className="primary-button" disabled={submitting} type="submit">
          {submitting ? "Creating task…" : "Create task"}
        </button>
      </form>

      {loading ? (
        <p role="status">Loading tasks…</p>
      ) : !loadError ? (
        <>
          <div className="task-columns">
            {COLUMNS.map((column) => {
              const columnTasks = tasks.filter((task) => task.status === column.status);
              return (
                <section
                  className="task-column"
                  key={column.status}
                  aria-label={`${column.label} tasks`}
                >
                  <h4>{column.label} <span>{columnTasks.length}</span></h4>
                  {columnTasks.length === 0 ? (
                    <p className="task-column-empty">No tasks</p>
                  ) : (
                    columnTasks.map((task) => (
                      <button
                        className={`task-card${selectedId === task.id ? " selected" : ""}`}
                        key={task.id}
                        onClick={() => setSelectedId(task.id)}
                        type="button"
                      >
                        <strong>{task.title}</strong>
                        <span className={`priority-${task.priority}`}>{task.priority}</span>
                        {task.assignee && <small>Assigned to {task.assignee.name}</small>}
                      </button>
                    ))
                  )}
                </section>
              );
            })}
          </div>
          {tasks.length === 0 && (
            <p className="workspace-empty">No tasks yet. Add a task to start the board.</p>
          )}
        </>
      ) : null}

      {selected && (
        <section className="task-editor" aria-label="Task details">
          <h4>Edit task</h4>
          <label htmlFor="edit-task-title">Title</label>
          <input
            id="edit-task-title"
            key={selected.id}
            defaultValue={selected.title}
            maxLength={200}
            onBlur={(event) => {
              if (event.target.value.trim() !== selected.title) {
                void updateSelected({ title: event.target.value });
              }
            }}
          />
          <label htmlFor="edit-task-description">Description</label>
          <textarea
            id="edit-task-description"
            key={`${selected.id}-description`}
            defaultValue={selected.description ?? ""}
            maxLength={2000}
            onBlur={(event) => {
              if (event.target.value !== (selected.description ?? "")) {
                void updateSelected({ description: event.target.value || null });
              }
            }}
          />
          <label htmlFor="edit-task-status">Status</label>
          <select
            id="edit-task-status"
            value={selected.status}
            disabled={saving}
            onChange={(event) => void updateSelected({ status: event.target.value as TaskStatus })}
          >
            {COLUMNS.map((column) => (
              <option key={column.status} value={column.status}>{column.label}</option>
            ))}
          </select>
          <label htmlFor="edit-task-priority">Priority</label>
          <select
            id="edit-task-priority"
            value={selected.priority}
            disabled={saving}
            onChange={(event) =>
              void updateSelected({ priority: event.target.value as TaskPriority })
            }
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
          <label htmlFor="edit-task-assignee">Assignee</label>
          <select
            id="edit-task-assignee"
            value={selected.assignee_id ?? ""}
            disabled={saving}
            onChange={(event) =>
              void updateSelected({
                assignee_id: event.target.value ? Number(event.target.value) : null,
              })
            }
          >
            <option value="">Unassigned</option>
            {assignees.map((assignee) => (
              <option key={assignee.id} value={assignee.id}>{assignee.name}</option>
            ))}
          </select>
          <label htmlFor="edit-task-due-date">Due date</label>
          <input
            id="edit-task-due-date"
            type="date"
            key={`${selected.id}-due-date`}
            defaultValue={selected.due_date ?? ""}
            onBlur={(event) => {
              const nextDate = event.target.value || null;
              if (nextDate !== selected.due_date) {
                void updateSelected({ due_date: nextDate });
              }
            }}
          />
          {canDelete && (
            <button
              className="quiet-button danger-button"
              disabled={saving}
              onClick={() => void deleteSelected()}
              type="button"
            >
              Delete task
            </button>
          )}
          <section className="task-discussion" aria-label="Task comments and activity">
            <div className="discussion-heading">
              <h4>Comments</h4>
              <button
                className="quiet-button"
                onClick={() => void loadDiscussion()}
                type="button"
              >
                Refresh
              </button>
            </div>
            {discussionLoading ? (
              <p role="status">Loading comments and activity…</p>
            ) : discussionError ? (
              <div>
                <p className="error-banner" role="alert">{discussionError}</p>
                <button
                  className="quiet-button"
                  onClick={() => void loadDiscussion()}
                  type="button"
                >
                  Try again
                </button>
              </div>
            ) : null}
            {!discussionLoading && !discussionError && comments.length === 0 && (
              <p className="workspace-empty">No comments yet.</p>
            )}
            {!discussionLoading && !discussionError && comments.map((comment) => (
              <article className="task-comment" key={comment.id}>
                <div className="comment-meta">
                  <strong>{comment.author.name}</strong>
                  <time dateTime={comment.created_at}>
                    {new Date(comment.created_at).toLocaleString()}
                  </time>
                </div>
                {editingCommentId === comment.id ? (
                  <>
                    <textarea
                      aria-label={`Edit comment by ${comment.author.name}`}
                      maxLength={4000}
                      value={editingCommentBody}
                      onChange={(event) => setEditingCommentBody(event.target.value)}
                    />
                    <button
                      className="quiet-button"
                      onClick={() => void saveComment(comment)}
                      type="button"
                    >
                      Save comment
                    </button>
                    <button
                      className="quiet-button"
                      onClick={() => setEditingCommentId(null)}
                      type="button"
                    >
                      Cancel edit
                    </button>
                  </>
                ) : (
                  <p>{comment.body}</p>
                )}
                {comment.can_manage && editingCommentId !== comment.id && (
                  <div className="comment-actions">
                    <button
                      className="quiet-button"
                      onClick={() => {
                        setEditingCommentId(comment.id);
                        setEditingCommentBody(comment.body);
                      }}
                      type="button"
                    >
                      Edit
                    </button>
                    <button
                      className="quiet-button danger-button"
                      onClick={() => void deleteComment(comment)}
                      type="button"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </article>
            ))}
            {!discussionError && (
              <form className="comment-form" onSubmit={createComment} noValidate>
                <label htmlFor="new-task-comment">Add a comment</label>
                <textarea
                  id="new-task-comment"
                  maxLength={4000}
                  value={commentBody}
                  aria-invalid={commentError ? true : undefined}
                  aria-describedby={commentError ? "task-comment-error" : undefined}
                  onChange={(event) => setCommentBody(event.target.value)}
                />
                {commentError && (
                  <p className="field-error" id="task-comment-error">{commentError}</p>
                )}
                <button
                  className="primary-button"
                  disabled={commentSubmitting}
                  type="submit"
                >
                  {commentSubmitting ? "Posting…" : "Post comment"}
                </button>
              </form>
            )}
            <div className="activity-timeline">
              <h4>Activity</h4>
              {!discussionLoading && !discussionError && activity.length === 0 && (
                <p className="workspace-empty">No activity yet.</p>
              )}
              {activity.map((item) => (
                <article className="activity-item" key={item.id}>
                  <p>{activityDescription(item)}</p>
                  <time dateTime={item.created_at}>
                    {new Date(item.created_at).toLocaleString()}
                  </time>
                </article>
              ))}
            </div>
          </section>
        </section>
      )}
    </section>
  );
}
