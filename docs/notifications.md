# In-app notifications

TeamFlow stores task-assignment and assigned-task-comment notifications in the
database. Notification writes share the transaction that creates the task,
changes its assignee, or creates the comment. The actor does not receive a
notification for their own action. Repeating an assignment update without
changing the assignee does not create another event; persisted notification
deduplication keys also prevent duplicate event inserts.

Notifications contain only a concise, generic message and workspace, project,
and task IDs. They do not contain comment text, email addresses, invitation
tokens, or arbitrary client-provided payloads. Workspace invitations do not
produce notifications because TeamFlow does not yet provide a token-safe
notification acceptance flow or email delivery.

All routes require an authenticated signed-cookie session. State-changing
routes require the existing `X-CSRF-Token` header.

## Endpoints

- `GET /api/v1/notifications?limit=25&offset=0` lists the current user's
  notifications for workspaces where they are currently a member, newest
  first. `limit` is 1–100 (default 25); `offset` is 0–1,000,000 (default 0).
  The response includes `notifications`, `unread_count`, `limit`, and `offset`.
- `GET /api/v1/notifications/unread-count` returns the unread count for those
  same accessible workspaces.
- `POST /api/v1/notifications/<notification_id>/read` marks one of the
  current user's accessible notifications read. Missing, other-user, and
  inaccessible-workspace IDs all return the same not-found response.
- `POST /api/v1/notifications/read-all` marks all currently accessible
  notifications for the current user read.

Each notification response contains its type, generic message, empty structured
payload, related IDs, creation time, and nullable read time. It never returns
the deduplication key.

## Retention and limitations

Notifications are deleted when their workspace, project, or task is deleted.
They are also deleted when their recipient is removed from or leaves that
workspace, and when the recipient account is deleted. Workspace membership is
checked on every list/count/read operation, so stale or manipulated IDs cannot
cross workspace boundaries.

The frontend loads notifications on entry to the authenticated app and offers
manual refresh; it does not poll. Assignment and comment events are currently
the only notification types. No email, SMS, push service, notification queue,
or background worker is configured.
