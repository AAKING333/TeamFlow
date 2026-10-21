import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { projectApi, type Project } from "../api/projects";
import { taskApi, type Task, type TaskActivity, type TaskAssignee } from "../api/tasks";
import type { Workspace } from "../api/workspaces";
import { Button, EmptyState, PriorityBadge, StatusBadge, SummaryCard } from "./Ui";
import { ProjectPanel } from "./ProjectPanel";

export type FocusTarget = "workspace-name" | "project-name" | "task-title";
export type ProjectCreateInput = { name: string; description?: string };
export type ScopeState = { status: "idle" | "loading" | "success" | "error"; error: string | null };

export interface WorkspaceOverviewProps {
  workspace: Workspace | null;
  workspaceCount?: number;
  targetProjectId?: number | null;
  targetTaskId?: number | null;
  registerFocusTarget?: (target: FocusTarget, focus: () => void) => () => void;
  focusTarget?: (target: FocusTarget) => boolean;
}

const idleState = (): ScopeState => ({ status: "idle", error: null });
const ACTIVITY_TYPES = new Set([
  "task_created",
  "task_title_changed",
  "task_description_changed",
  "task_status_changed",
  "task_priority_changed",
  "task_assignee_changed",
  "task_due_date_changed",
  "task_deleted",
]);

function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}
function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}
function validDateKey(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}
function validAssignee(value: unknown): value is TaskAssignee {
  return record(value) && positiveInteger(value.id) && typeof value.name === "string" && value.name.trim().length > 0;
}
function validActivityData(eventType: string, data: Record<string, unknown>) {
  switch (eventType) {
    case "task_created":
      return Object.keys(data).length === 0;
    case "task_deleted":
      return Object.keys(data).length === 1 && typeof data.task_title === "string" && data.task_title.trim().length > 0 && data.task_title.length <= 200;
    case "task_title_changed":
    case "task_description_changed":
      return Object.keys(data).length === 1 && data.changed === true;
    case "task_status_changed":
      return Object.keys(data).length === 2 && ["todo", "in_progress", "done"].includes(String(data.from)) && ["todo", "in_progress", "done"].includes(String(data.to));
    case "task_priority_changed":
      return Object.keys(data).length === 2 && ["low", "medium", "high"].includes(String(data.from)) && ["low", "medium", "high"].includes(String(data.to));
    case "task_assignee_changed":
      return Object.keys(data).length === 1 && typeof data.assigned === "boolean";
    case "task_due_date_changed":
      return Object.keys(data).length === 2 && (data.from === null || validDateKey(data.from)) && (data.to === null || validDateKey(data.to));
    default:
      return false;
  }
}
function validProject(value: unknown, workspaceId: number): value is Project {
  return record(value) && positiveInteger(value.id) && value.workspace_id === workspaceId &&
    typeof value.name === "string" && value.name.trim().length > 0 &&
    (value.description === null || typeof value.description === "string") &&
    validTimestamp(value.created_at) && validTimestamp(value.updated_at);
}
function validTask(value: unknown, projectId: number): value is Task {
  if (!record(value) || !positiveInteger(value.id) || value.project_id !== projectId ||
      typeof value.title !== "string" || !value.title.trim() ||
      (value.description !== null && typeof value.description !== "string") ||
      !["todo", "in_progress", "done"].includes(String(value.status)) ||
      !["low", "medium", "high"].includes(String(value.priority)) ||
      (value.due_date !== null && !validDateKey(value.due_date)) ||
      (value.assignee_id !== null && !positiveInteger(value.assignee_id)) ||
      (value.assignee !== null && !validAssignee(value.assignee)) ||
      (value.assignee && value.assignee_id !== (value.assignee as unknown as Record<string, unknown>).id) ||
      !validTimestamp(value.created_at) || !validTimestamp(value.updated_at)) return false;
  return true;
}
function validActivity(value: unknown, workspaceId: number, projectId: number): value is TaskActivity {
  return record(value) && positiveInteger(value.id) && value.workspace_id === workspaceId &&
    value.project_id === projectId && (value.task_id === null || positiveInteger(value.task_id)) &&
    (value.actor === null || validAssignee(value.actor)) && typeof value.event_type === "string" &&
    ACTIVITY_TYPES.has(value.event_type) && record(value.data) && validActivityData(value.event_type, value.data) && validTimestamp(value.created_at);
}
function parseProjects(value: unknown, workspaceId: number) {
  if (!record(value) || !Array.isArray(value.projects)) throw new Error("Projects response was unavailable. Try again.");
  const projects = value.projects.filter((item): item is Project => validProject(item, workspaceId));
  return { projects, omitted: projects.length !== value.projects.length };
}
function parseTaskResult(value: unknown, projectId: number) {
  if (!record(value) || !Array.isArray(value.tasks) || !Array.isArray(value.assignees)) {
    throw new Error("Tasks response was unavailable. Try again.");
  }
  const tasks = value.tasks.filter((item): item is Task => validTask(item, projectId));
  const assignees = value.assignees.filter(validAssignee);
  return { tasks, assignees, omitted: tasks.length !== value.tasks.length || assignees.length !== value.assignees.length };
}
function parseActivityResult(value: unknown, workspaceId: number, projectId: number) {
  if (!record(value) || !Array.isArray(value.activities)) throw new Error("Project activity response was unavailable. Try again.");
  const activities = value.activities.filter((item): item is TaskActivity => validActivity(item, workspaceId, projectId));
  return { activities, omitted: activities.length !== value.activities.length };
}
function calendarKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function activityDescription(item: TaskActivity) {
  const actor = item.actor?.name ?? "A former user";
  const messages: Record<TaskActivity["event_type"], string> = {
    task_created: "created a task",
    task_title_changed: "changed a task title",
    task_description_changed: "updated a task description",
    task_status_changed: "changed task status",
    task_priority_changed: "changed task priority",
    task_assignee_changed: item.data.assigned ? "assigned a task" : "unassigned a task",
    task_due_date_changed: "changed a task due date",
    task_deleted: "deleted a task",
  };
  return `${actor} ${messages[item.event_type]}.`;
}

export function WorkspaceOverview({
  workspace,
  workspaceCount = 0,
  targetProjectId = null,
  targetTaskId = null,
  registerFocusTarget,
  focusTarget: focusTargetFromOwner,
}: WorkspaceOverviewProps) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsState, setProjectsState] = useState<ScopeState>(idleState);
  const [projectsWarning, setProjectsWarning] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [tasksState, setTasksState] = useState<ScopeState>(idleState);
  const [tasksWarning, setTasksWarning] = useState(false);
  const [assignees, setAssignees] = useState<TaskAssignee[] | null>(null);
  const [projectActivity, setProjectActivity] = useState<TaskActivity[] | null>(null);
  const [projectActivityState, setProjectActivityState] = useState<ScopeState>(idleState);
  const [activityWarning, setActivityWarning] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [focusMessage, setFocusMessage] = useState<string | null>(null);
  const focusTargets = useRef(new Map<FocusTarget, () => void>());
  const projectRequest = useRef(0);
  const projectSnapshotWorkspaceId = useRef<number | null>(null);
  const taskRequest = useRef(0);
  const activityRequest = useRef(0);

  const register = useCallback((target: FocusTarget, focus: () => void) => {
    focusTargets.current.set(target, focus);
    return () => {
      if (focusTargets.current.get(target) === focus) focusTargets.current.delete(target);
    };
  }, []);
  const focusTarget = useCallback((target: FocusTarget) => {
    setFocusMessage(null);
    requestAnimationFrame(() => {
      const focused = focusTargetFromOwner
        ? focusTargetFromOwner(target)
        : Boolean(focusTargets.current.get(target));
      if (!focused) {
        setFocusMessage("That action is not available until its section is ready.");
        return;
      }
      if (!focusTargetFromOwner) focusTargets.current.get(target)?.();
    });
  }, [focusTargetFromOwner]);
  const registerTarget = registerFocusTarget ?? register;

  const loadProjects = useCallback((workspaceId: number) => {
    const requestId = ++projectRequest.current;
    projectSnapshotWorkspaceId.current = workspaceId;
    taskRequest.current += 1;
    activityRequest.current += 1;
    setProjects(null);
    setSelectedProjectId(null);
    setTasks(null);
    setAssignees(null);
    setProjectActivity(null);
    setSelectedTaskId(null);
    setTasksState(idleState());
    setProjectActivityState(idleState());
    setProjectsWarning(false);
    setProjectsState({ status: "loading", error: null });
    void projectApi.list(workspaceId).then((result: unknown) => {
      if (requestId !== projectRequest.current) return;
      const parsed = parseProjects(result, workspaceId);
      setProjects(parsed.projects);
      setProjectsWarning(parsed.omitted);
      setProjectsState({ status: "success", error: null });
    }).catch((error: unknown) => {
      if (requestId !== projectRequest.current) return;
      setProjects(null);
      setProjectsState({ status: "error", error: message(error, "Projects could not be loaded. Try again.") });
    });
  }, []);

  useEffect(() => {
    if (!workspace) {
      projectRequest.current += 1;
      projectSnapshotWorkspaceId.current = null;
      setProjects(null);
      setProjectsState(idleState());
      setSelectedProjectId(null);
      setTasks(null);
      setAssignees(null);
      setProjectActivity(null);
      setSelectedTaskId(null);
      return;
    }
    loadProjects(workspace.id);
  }, [loadProjects, workspace?.id]);

  useLayoutEffect(() => {
    if (!projects) return;
    setSelectedProjectId((current) => {
      if (targetProjectId !== null && projects.some((project) => project.id === targetProjectId)) return targetProjectId;
      if (current !== null && projects.some((project) => project.id === current)) return current;
      return projects[0]?.id ?? null;
    });
  }, [projects, targetProjectId]);

  const loadProjectData = useCallback((workspaceId: number, projectId: number) => {
    const taskId = ++taskRequest.current;
    const activityId = ++activityRequest.current;
    setTasks(null);
    setAssignees(null);
    setProjectActivity(null);
    setTasksWarning(false);
    setActivityWarning(false);
    setTasksState({ status: "loading", error: null });
    setProjectActivityState({ status: "loading", error: null });
    void taskApi.list(workspaceId, projectId).then((result: unknown) => {
      if (taskId !== taskRequest.current || workspace?.id !== workspaceId || selectedProjectId !== projectId) return;
      const parsed = parseTaskResult(result, projectId);
      setTasks(parsed.tasks);
      setAssignees(parsed.assignees);
      setSelectedTaskId((current) => parsed.tasks.some((task) => task.id === current) ? current : null);
      setTasksWarning(parsed.omitted);
      setTasksState({ status: "success", error: null });
    }).catch((error: unknown) => {
      if (taskId !== taskRequest.current) return;
      setTasks(null);
      setAssignees(null);
      setTasksState({ status: "error", error: message(error, "Tasks could not be loaded.") });
    });
    void taskApi.listActivity(workspaceId, projectId).then((result: unknown) => {
      if (activityId !== activityRequest.current || workspace?.id !== workspaceId || selectedProjectId !== projectId) return;
      const parsed = parseActivityResult(result, workspaceId, projectId);
      setProjectActivity(parsed.activities);
      setActivityWarning(parsed.omitted);
      setProjectActivityState({ status: "success", error: null });
    }).catch((error: unknown) => {
      if (activityId !== activityRequest.current) return;
      setProjectActivity(null);
      setProjectActivityState({ status: "error", error: message(error, "Project activity could not be loaded.") });
    });
  }, [selectedProjectId, workspace?.id]);

  useEffect(() => {
    if (!workspace || projectSnapshotWorkspaceId.current !== workspace.id || selectedProjectId === null || !projects?.some((project) => project.id === selectedProjectId && project.workspace_id === workspace.id)) {
      taskRequest.current += 1;
      activityRequest.current += 1;
      setTasks(null);
      setAssignees(null);
      setProjectActivity(null);
      setTasksState(idleState());
      setProjectActivityState(idleState());
      setSelectedTaskId(null);
      return;
    }
    loadProjectData(workspace.id, selectedProjectId);
  }, [loadProjectData, projects, selectedProjectId, targetProjectId, targetTaskId, workspace]);

  useEffect(() => {
    if (!tasks) return;
    setSelectedTaskId((current) => {
      if (targetTaskId !== null) {
        if (targetProjectId === null || targetProjectId !== selectedProjectId) return null;
        return tasks.some((task) => task.id === targetTaskId) ? targetTaskId : null;
      }
      return current !== null && tasks.some((task) => task.id === current) ? current : null;
    });
  }, [selectedProjectId, targetProjectId, targetTaskId, tasks]);

  const onCreateProject = useCallback(async (input: ProjectCreateInput) => {
    if (!workspace) throw new Error("Select a workspace before creating a project.");
    const result = await projectApi.create(workspace.id, input);
    setProjects((current) => [...(current ?? []), result.project].sort((left, right) => left.name.localeCompare(right.name)));
    setProjectsState({ status: "success", error: null });
    setSelectedProjectId(result.project.id);
    return result.project;
  }, [workspace]);

  const onRetryProjects = useCallback(() => {
    if (workspace) loadProjects(workspace.id);
  }, [loadProjects, workspace]);
  const onRetryTasks = useCallback(() => {
    if (workspace && selectedProjectId !== null) loadProjectData(workspace.id, selectedProjectId);
  }, [loadProjectData, selectedProjectId, workspace]);
  const onRetryProjectActivity = useCallback(() => {
    if (!workspace || selectedProjectId === null) return;
    const workspaceId = workspace.id;
    const projectId = selectedProjectId;
    const requestId = ++activityRequest.current;
    setProjectActivity(null);
    setActivityWarning(false);
    setProjectActivityState({ status: "loading", error: null });
    void taskApi.listActivity(workspaceId, projectId).then((result: unknown) => {
      if (requestId !== activityRequest.current || workspace?.id !== workspaceId || selectedProjectId !== projectId) return;
      const parsed = parseActivityResult(result, workspaceId, projectId);
      setProjectActivity(parsed.activities);
      setActivityWarning(parsed.omitted);
      setProjectActivityState({ status: "success", error: null });
    }).catch((error: unknown) => {
      if (requestId !== activityRequest.current) return;
      setProjectActivityState({ status: "error", error: message(error, "Project activity could not be loaded.") });
    });
  }, [selectedProjectId, workspace]);
  const onTaskCreated = useCallback((task: Task) => {
    if (task.project_id !== selectedProjectId) return;
    setTasks((current) => [...(current ?? []), task]);
    setSelectedTaskId(task.id);
  }, [selectedProjectId]);
  const onTaskUpdated = useCallback((task: Task) => {
    if (task.project_id !== selectedProjectId) return;
    setTasks((current) => current?.map((item) => item.id === task.id ? task : item) ?? current);
  }, [selectedProjectId]);
  const onTaskDeleted = useCallback((taskId: number) => {
    setTasks((current) => current?.filter((task) => task.id !== taskId) ?? current);
    setSelectedTaskId((current) => current === taskId ? null : current);
  }, []);

  const selectedProject = projects?.find((project) => project.id === selectedProjectId) ?? null;
  const manageable = workspace?.role === "owner" || workspace?.role === "admin";
  const today = calendarKey(new Date());
  const dueTasks = (tasks ?? []).filter((task) => task.due_date && validDateKey(task.due_date));
  const overdue = dueTasks.filter((task) => task.due_date! < today).sort((a, b) => a.due_date!.localeCompare(b.due_date!) || a.id - b.id).slice(0, 5);
  const upcoming = dueTasks.filter((task) => task.due_date! >= today).sort((a, b) => a.due_date!.localeCompare(b.due_date!) || a.id - b.id).slice(0, 5);
  const statusCounts = tasks ? {
    todo: tasks.filter((task) => task.status === "todo").length,
    in_progress: tasks.filter((task) => task.status === "in_progress").length,
    done: tasks.filter((task) => task.status === "done").length,
  } : null;
  const action = !workspace && workspaceCount === 0
    ? { label: "Start workspace setup", target: "workspace-name" as FocusTarget }
    : projectsState.status === "success" && projects?.length === 0 && manageable
      ? { label: "Start project setup", target: "project-name" as FocusTarget }
      : selectedProject && tasksState.status === "success"
        ? { label: "New task", target: "task-title" as FocusTarget }
        : null;

  return (
    <>
      <section className="overview-panel" aria-labelledby="workspace-overview-heading">
        <div className="overview-panel-heading">
          <div>
            <p className="eyebrow">WORKSPACE OVERVIEW</p>
            <h2 id="workspace-overview-heading">A clear view of what needs attention</h2>
            <p className="dashboard-intro">Real project, task, and activity data for {workspace?.name ?? "your TeamFlow workspace"}.</p>
          </div>
          {action && (
            <Button
              variant="primary"
              aria-label={action.label === "New task" ? undefined : `${action.label} from overview`}
              onClick={() => focusTarget(action.target)}
            >
              {action.label}
            </Button>
          )}
        </div>
        {focusMessage && <p className="error-banner" role="status">{focusMessage}</p>}
        <div className="summary-grid">
          <SummaryCard label="Your workspaces" value={workspaceCount} />
          {projectsState.status === "success" && <SummaryCard label="Projects in this workspace" value={projects?.length ?? 0} />}
          {statusCounts && tasksState.status === "success" && (
            <SummaryCard label="Tasks by status" value={`${statusCounts.todo} to do · ${statusCounts.in_progress} in progress · ${statusCounts.done} done`} />
          )}
        </div>
        {tasksState.status === "success" && selectedProject && (
          <div className="overview-task-groups">
            <section aria-labelledby="overdue-heading"><h3 id="overdue-heading">Overdue tasks</h3>{overdue.length ? overdue.map((task) => <p key={task.id}><strong>{task.title}</strong> · <StatusBadge value={task.status} /> · <PriorityBadge value={task.priority} /> · <span className="overdue-label">Overdue</span> · {task.due_date}{task.assignee && <> · Assigned to {task.assignee.name}</>}</p>) : <p>No overdue tasks</p>}</section>
            <section aria-labelledby="upcoming-heading"><h3 id="upcoming-heading">Upcoming tasks</h3>{upcoming.length ? upcoming.map((task) => <p key={task.id}><strong>{task.title}</strong> · <StatusBadge value={task.status} /> · {task.due_date}{task.assignee && <> · Assigned to {task.assignee.name}</>}</p>) : <p>No upcoming tasks</p>}</section>
          </div>
        )}
        {selectedProject && projectActivityState.status === "success" && (
          <section className="project-activity" aria-labelledby="project-activity-heading">
            <h3 id="project-activity-heading">Recent project activity</h3>
            {projectActivity?.length ? projectActivity.slice(0, 8).map((item) => <article className="activity-item" key={item.id}><p>{activityDescription(item)}</p><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></article>) : <p className="workspace-empty">No recent project activity.</p>}
            {activityWarning && <p className="warning-banner" role="status">Some activity could not be displayed.</p>}
          </section>
        )}
        {selectedProject && projectActivityState.status === "error" && <div><p className="error-banner" role="alert">{projectActivityState.error}</p><button className="quiet-button" type="button" onClick={onRetryProjectActivity}>Try again</button></div>}
        {projectsWarning && <p className="warning-banner" role="status">Some projects could not be displayed.</p>}
        {tasksWarning && <p className="warning-banner" role="status">Some tasks or assignees could not be displayed.</p>}
        {!workspace && workspaceCount === 0 && <EmptyState heading="Start with a workspace">Create a workspace to organize projects and tasks.</EmptyState>}
      </section>
      <ProjectPanel
        workspace={workspace}
        projects={projects}
        projectsState={projectsState}
        selectedProjectId={selectedProjectId}
        onSelectProject={setSelectedProjectId}
        onCreateProject={onCreateProject}
        onRetryProjects={onRetryProjects}
        registerFocusTarget={registerTarget}
        targetTaskId={targetTaskId}
        tasks={tasks}
        tasksState={tasksState}
        assignees={assignees}
        selectedTaskId={selectedTaskId}
        onSelectTask={setSelectedTaskId}
        onTaskCreated={onTaskCreated}
        onTaskUpdated={onTaskUpdated}
        onTaskDeleted={onTaskDeleted}
        onRetryTasks={onRetryTasks}
      />
    </>
  );
}
