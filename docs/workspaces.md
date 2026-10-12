# Workspaces and memberships

## API

Workspace routes are under `/api/v1/workspaces`. Workspace IDs are integer
database IDs; every workspace-specific request checks the signed-in user's
membership on the server.

- `POST /api/v1/workspaces` creates a workspace and its initial owner
  membership in one transaction. The JSON body is `{"name": "Design"}`.
- `GET /api/v1/workspaces` returns only workspaces where the current user is a
  member, including that user's role.
- `GET /api/v1/workspaces/<workspace_id>` returns a workspace to its members.
- `PATCH /api/v1/workspaces/<workspace_id>` changes the name.
- `GET /api/v1/workspaces/<workspace_id>/members` lists member IDs, names,
  and roles for workspace members. Only owners and admins receive member email
  addresses in the response.
- `POST /api/v1/workspaces/<workspace_id>/transfer-ownership` transfers
  ownership to an existing member using `{"user_id": 123}`.
- `PATCH /api/v1/workspaces/<workspace_id>/members/<user_id>` changes a role
  to `admin` or `member`.
- `DELETE /api/v1/workspaces/<workspace_id>/members/<user_id>` removes a
  member.
- `POST /api/v1/workspaces/<workspace_id>/leave` lets a non-owner leave.
- `DELETE /api/v1/workspaces/<workspace_id>` deletes the workspace.

All mutation routes require the existing session-bound `X-CSRF-Token` header.
The browser client obtains a token from `/api/v1/auth/csrf`; credentialed
requests continue to use the signed-cookie session.

## Roles and authorization

- `owner` and `admin` can update the workspace name.
- Every member can read workspace details and the member list. Only owners and
  admins can see member email addresses.
- Only the owner can transfer ownership or delete the workspace.
- Ownership can only be transferred to an existing member. The previous owner
  becomes an admin, and the target member becomes the sole owner.
- Only the owner can promote or demote members. Owners cannot change their own
  role; use the existing ownership-transfer route to change ownership.
- Owners can remove admins and members. Admins can remove regular members only.
  A member or admin can leave; the owner must transfer ownership first.
- Administrative role changes/removals revoke pending invitations addressed to
  that member's email.
- A workspace always has a non-null owner user. Deleting an owner user is
  restricted by the database relationship.
- Membership uniqueness, valid roles, and a single owner per workspace are
  database constraints.
- Workspace deletion cascades to memberships; deleting a workspace cannot
  leave orphaned membership rows.

Users who are not members receive the same `workspace_not_found` response for
workspace-specific resources regardless of whether the ID exists. Unauthenticated
requests receive the normal authentication error; authenticated but
unauthorized role operations return `permission_denied`.

## Invitations

- `POST /api/v1/workspaces/<workspace_id>/invitations` creates an invitation
  from `{"email": "person@example.test", "role": "member"}`. Email is trimmed
  and case-folded to match account normalization. Owners may invite admins or
  members; admins may invite members only.
- `GET /api/v1/workspaces/<workspace_id>/invitations` lists unexpired pending
  invitations for owners/admins.
- `DELETE /api/v1/workspaces/<workspace_id>/invitations/<invitation_id>`
  revokes a pending invitation. Admins may revoke member invitations only.
- `POST /api/v1/invitations/accept` accepts `{"token": "..."}` for the
  authenticated account whose normalized email matches the invitation.

Invitation tokens are generated from cryptographically secure randomness and
only their SHA-256 digest is persisted. Tokens expire after seven days.
Invitations cannot grant the owner role, are single-use, and a partial unique
index prevents more than one pending invite per workspace/email. Expired,
accepted, and revoked invitations cannot be reused. Acceptance and membership
creation are committed together; the membership unique constraint protects
against duplicate membership.

No email delivery provider is configured. Creating an invitation does **not**
send email. Without a configured delivery adapter, invitation creation is
rejected in non-development environments and no database record is created.
In development, the raw token is held only in a volatile,
one-time local outbox and can be retrieved by a workspace owner/admin through
`GET /api/v1/workspaces/<workspace_id>/invitations/<invitation_id>/development-link`.
That endpoint exists only in development mode, is authenticated and
workspace-scoped, returns `Cache-Control: no-store`, and cannot retrieve a
token a second time. Ordinary create/list responses never contain a token or
its hash. The outbox is lost when the backend restarts. Production delivery
needs a configured provider before invitations can be distributed; tokens
must not be placed in production logs.

The authenticated workspace selector includes a member-management panel with
role controls, pending invitations, and leave/remove actions. The invitation
acceptance screen strips the token from the visible URL after loading it into
component memory, requires sign-in with the invited account, and clears token
state after acceptance or cancellation.

## Frontend

The authenticated account shell loads the user's workspaces and provides a
workspace selector and creation form. It displays loading, empty, retryable
error, validation, and creation states. Selection is client-side navigation
state only; it does not grant access to a workspace. The API independently
checks membership and permissions on every request.

## Projects

Projects are scoped to a workspace and use the workspace ID in every route:

- `POST /api/v1/workspaces/<workspace_id>/projects` creates a project with
  required `name` and optional `description`.
- `GET /api/v1/workspaces/<workspace_id>/projects` lists that workspace's
  projects.
- `GET /api/v1/workspaces/<workspace_id>/projects/<project_id>` retrieves a
  project only when it belongs to the requested workspace.
- `PATCH /api/v1/workspaces/<workspace_id>/projects/<project_id>` updates
  `name` and/or `description`.
- `DELETE /api/v1/workspaces/<workspace_id>/projects/<project_id>` deletes it.

Names are trimmed and limited to 120 characters. Descriptions are optional,
trimmed, and limited to 2000 characters. Unknown fields are rejected. All
workspace members can list and view projects. Only owners and admins can
create, rename, or delete projects. A non-member receives `workspace_not_found`;
a project ID that is missing or belongs to another workspace receives
`project_not_found`. All mutations use the existing session-bound CSRF token.

The authenticated shell lists projects for the selected workspace, allows
members to select and read a project, and only renders project-creation
controls for owners/admins. Switching workspaces reloads the scoped project
list; server-side membership and role checks remain authoritative.

## Project tasks

Tasks are scoped to a project and use the nested workspace/project routes:

- `POST /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks`
- `GET /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks`
- `GET /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks/<task_id>`
- `PATCH /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks/<task_id>`
- `DELETE /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks/<task_id>`

Task creation requires a trimmed `title` of 1–200 characters. Optional fields
are `description` (up to 2000 characters), `status` (`todo`, `in_progress`, or
`done`), `priority` (`low`, `medium`, or `high`), `due_date` (`YYYY-MM-DD`),
and `assignee_id`. Status defaults to `todo`, priority to `medium`, and due
date and assignee are nullable. Listing accepts `status` and `priority` query
filters and returns tasks plus workspace member IDs and names for assignment
controls. Unknown query parameters and invalid filters return a validation
error.

Every route first checks workspace membership and that the project belongs to
the workspace in the URL; task reads and updates additionally constrain the
task to that project. Workspace members may list, view, create, and update
tasks. Assignment is limited to a user who is a member of that same workspace.
Only owners and admins may delete tasks. A foreign-workspace request receives
`workspace_not_found`; a missing or cross-project project/task receives its
corresponding not-found response. Mutations require the existing session-bound
CSRF token. Project and workspace deletion cascade to their tasks; deleting an
assignee user sets the nullable assignee reference to null.

The project view includes a responsive three-column task board. Members can
create tasks, change status, priority, description, due date, and assignment;
owners/admins also see task deletion. The frontend controls are convenience
only—the backend enforces membership, assignment, and deletion permissions.

## Task comments and activity

Comments use the nested task route:

- `GET` and `POST /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks/<task_id>/comments`
- `PATCH` and `DELETE /api/v1/workspaces/<workspace_id>/projects/<project_id>/tasks/<task_id>/comments/<comment_id>`

Comment creation and edits require a non-blank body of up to 4000 characters.
Workspace members with project access can read and create comments. Authors
can edit and delete their own comments; workspace owners and admins can also
moderate other members' comments. All writes require CSRF. Cross-task comment
IDs return `comment_not_found`, and inaccessible workspaces return
`workspace_not_found`.

`GET /api/v1/workspaces/<workspace_id>/projects/<project_id>/activity` returns
the newest project activity first, with stable `(created_at, id)` ordering and
`limit`/`offset` pagination (default 50, maximum 100). An optional `task_id`
filters to one task. Events include task creation, changes to title,
description, status, priority, assignee, and due date, plus task deletion.
Sensitive text values are not copied into the timeline: text edits record only
that the field changed; status and priority record bounded enum transitions;
assignment records only assigned/unassigned; due-date events record dates.
Deleting a task keeps its activity under the project, sets the task reference
to null, and stores only the bounded task title on the deletion event.
Deleting the project or workspace cascades and purges its activity. Deleting a
user sets activity actor references to null.

The task detail panel loads comments and activity for the selected task,
offers comment creation and author/admin edit/delete controls, and provides a
retry action. Switching tasks or projects clears prior content and ignores
stale in-flight responses. Activity display text is selected from the
server-controlled event type; user-provided strings are never interpreted as
system messages.
