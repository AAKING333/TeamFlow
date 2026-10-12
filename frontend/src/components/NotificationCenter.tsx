import { useCallback, useEffect, useRef, useState } from "react";

import { notificationApi, type Notification } from "../api/notifications";

interface NotificationCenterProps {
  onNavigate: (notification: Notification) => void;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Notifications could not be loaded.";
}

function displayDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function NotificationCenter({ onNavigate }: NotificationCenterProps) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const hasLoaded = useRef(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await notificationApi.list();
      setNotifications(result.notifications);
      setUnreadCount(result.unread_count);
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      hasLoaded.current = true;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function markRead(notification: Notification) {
    if (notification.read_at !== null || updatingId !== null) return;
    setUpdatingId(notification.id);
    setActionError(null);
    try {
      const result = await notificationApi.markRead(notification.id);
      setNotifications((items) =>
        items.map((item) =>
          item.id === notification.id ? result.notification : item,
        ),
      );
      setUnreadCount(result.unread_count);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setUpdatingId(null);
    }
  }

  async function markAllRead() {
    if (markingAll || unreadCount === 0) return;
    setMarkingAll(true);
    setActionError(null);
    try {
      const result = await notificationApi.markAllRead();
      const readAt = new Date().toISOString();
      setNotifications((items) =>
        items.map((item) => (item.read_at === null ? { ...item, read_at: readAt } : item)),
      );
      setUnreadCount(result.unread_count);
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setMarkingAll(false);
    }
  }

  async function openNotification(notification: Notification) {
    if (notification.read_at === null) {
      await markRead(notification);
    }
    onNavigate(notification);
    setExpanded(false);
  }

  return (
    <div className="notification-center">
      <button
        className="quiet-button notification-toggle"
        type="button"
        aria-expanded={expanded}
        aria-controls="notification-panel"
        aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`}
        onClick={() => {
          const opening = !expanded;
          setExpanded(opening);
          if (opening && hasLoaded.current) void reload();
        }}
      >
        Notifications
        {unreadCount > 0 && (
          <span className="notification-badge" aria-hidden="true">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {expanded && (
        <section
          className="notification-panel"
          id="notification-panel"
          aria-label="Notifications"
        >
          <div className="notification-panel-heading">
            <h2>Notifications</h2>
            <div>
              <button
                className="quiet-button"
                type="button"
                onClick={() => void reload()}
                disabled={loading}
              >
                Refresh
              </button>
              <button
                className="quiet-button"
                type="button"
                onClick={() => void markAllRead()}
                disabled={markingAll || unreadCount === 0}
              >
                {markingAll ? "Marking…" : "Mark all read"}
              </button>
            </div>
          </div>

          {loadError ? (
            <div>
              <p role="alert">{loadError}</p>
              <button className="quiet-button" type="button" onClick={() => void reload()}>
                Try again
              </button>
            </div>
          ) : loading ? (
            <p role="status">Loading notifications…</p>
          ) : notifications.length === 0 ? (
            <p className="workspace-empty">You’re all caught up.</p>
          ) : (
            <ul className="notification-list">
              {notifications.map((notification) => (
                <li
                  className={notification.read_at === null ? "unread" : ""}
                  key={notification.id}
                >
                  <button
                    className="notification-link"
                    type="button"
                    onClick={() => void openNotification(notification)}
                  >
                    <span>{notification.message}</span>
                    <time dateTime={notification.created_at}>
                      {displayDate(notification.created_at)}
                    </time>
                    {notification.task_id === null && (
                      <span className="notification-context">Open workspace</span>
                    )}
                  </button>
                  {notification.read_at === null && (
                    <button
                      className="notification-read-button"
                      type="button"
                      disabled={updatingId !== null}
                      onClick={() => void markRead(notification)}
                    >
                      {updatingId === notification.id ? "Saving…" : "Mark read"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {actionError && <p className="error-banner" role="alert">{actionError}</p>}
        </section>
      )}
    </div>
  );
}
