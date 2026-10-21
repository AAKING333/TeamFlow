import { useCallback, useEffect, useRef, useState } from "react";

import { notificationApi, type Notification } from "../api/notifications";

interface NotificationCenterProps {
  onNavigate: (notification: Notification) => void;
  onOpenChange?: (open: boolean) => void;
  closeRequest?: number;
  suppressFocusReturnOnClose?: boolean;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Notifications could not be loaded.";
}
function displayDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function NotificationCenter({
  onNavigate,
  onOpenChange,
  closeRequest,
  suppressFocusReturnOnClose = false,
}: NotificationCenterProps) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const [mobile, setMobile] = useState(() => typeof window !== "undefined" && window.innerWidth < 1024);
  const hasLoaded = useRef(false);
  const updatingRef = useRef(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const suppressFocusReturnRef = useRef(false);
  const suppressFocusReturnOnCloseRef = useRef(suppressFocusReturnOnClose);
  suppressFocusReturnOnCloseRef.current = suppressFocusReturnOnClose;

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

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const resize = () => setMobile(window.innerWidth < 1024);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (closeRequest === undefined) return;
    suppressFocusReturnRef.current = expanded && suppressFocusReturnOnCloseRef.current;
    setExpanded(false);
    onOpenChange?.(false);
  }, [closeRequest, onOpenChange]);
  useEffect(() => {
    if (!expanded) {
      const suppressFocusReturn = suppressFocusReturnRef.current;
      suppressFocusReturnRef.current = false;
      if (!suppressFocusReturn) toggleRef.current?.focus();
      return;
    }
    const heading = panelRef.current?.querySelector<HTMLElement>("h2, button, [tabindex='0']");
    if (mobile) heading?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpanded(false);
        onOpenChange?.(false);
        return;
      }
      if (!mobile || event.key !== "Tab") return;
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [expanded, mobile, onOpenChange]);

  async function markRead(notification: Notification): Promise<boolean> {
    if (notification.read_at !== null) return true;
    if (updatingRef.current) return false;
    updatingRef.current = true;
    setUpdatingId(notification.id);
    setActionError(null);
    try {
      const result = await notificationApi.markRead(notification.id);
      setNotifications((items) => items.map((item) => item.id === notification.id ? result.notification : item));
      setUnreadCount(result.unread_count);
      return true;
    } catch (error) {
      setActionError(errorMessage(error));
      return false;
    } finally {
      updatingRef.current = false;
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
      setNotifications((items) => items.map((item) => item.read_at === null ? { ...item, read_at: readAt } : item));
      setUnreadCount(result.unread_count);
    } catch (error) { setActionError(errorMessage(error)); }
    finally { setMarkingAll(false); }
  }
  async function openNotification(notification: Notification) {
    if (updatingRef.current) return;
    if (notification.read_at === null && !(await markRead(notification))) return;
    onNavigate(notification);
    setExpanded(false);
    onOpenChange?.(false);
  }
  function close() {
    setExpanded(false);
    onOpenChange?.(false);
  }

  return (
    <div className="notification-center">
      <button ref={toggleRef} className="quiet-button notification-toggle" type="button" aria-expanded={expanded} aria-controls="notification-panel" aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`} onClick={() => {
        const opening = !expanded;
        setExpanded(opening);
        onOpenChange?.(opening);
        if (opening && hasLoaded.current) void reload();
      }}>
        Notifications
        {unreadCount > 0 && <span className="notification-badge" aria-hidden="true">{unreadCount > 99 ? "99+" : unreadCount}</span>}
      </button>
      {expanded && mobile && <div className="notification-modal-backdrop" aria-hidden="true" onClick={close} />}
      {expanded && (
        <section ref={panelRef} className={`notification-panel${mobile ? " notification-modal" : ""}`} id="notification-panel" role={mobile ? "dialog" : "region"} aria-modal={mobile || undefined} aria-label="Notifications">
          <div className="notification-panel-heading">
            <h2 tabIndex={mobile ? -1 : undefined}>Notifications</h2>
            <div>
              {mobile && <button className="quiet-button" type="button" onClick={close}>Close</button>}
              <button className="quiet-button" type="button" onClick={() => void reload()} disabled={loading}>Refresh</button>
              <button className="quiet-button" type="button" onClick={() => void markAllRead()} disabled={markingAll || unreadCount === 0}>{markingAll ? "Marking…" : "Mark all read"}</button>
            </div>
          </div>
          {loadError ? <div><p role="alert">{loadError}</p><button className="quiet-button" type="button" onClick={() => void reload()}>Try again</button></div>
            : loading ? <p role="status">Loading notifications…</p>
              : notifications.length === 0 ? <p className="workspace-empty">You’re all caught up.</p>
                : <ul className="notification-list">{notifications.map((notification) => <li className={notification.read_at === null ? "unread" : ""} key={notification.id}>
                  <button className="notification-link" type="button" disabled={updatingId !== null} onClick={() => void openNotification(notification)}>
                    <span>{notification.message}</span><time dateTime={notification.created_at}>{displayDate(notification.created_at)}</time>{notification.task_id === null && <span className="notification-context">Open workspace</span>}
                  </button>
                  {notification.read_at === null && <button className="notification-read-button" type="button" disabled={updatingId !== null} onClick={() => void markRead(notification)}>{updatingId === notification.id ? "Saving…" : "Mark read"}</button>}
                </li>)}</ul>}
          {actionError && <p className="error-banner" role="alert">{actionError}</p>}
        </section>
      )}
    </div>
  );
}
