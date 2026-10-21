import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Notification } from "../api/notifications";
import { useAuth } from "../auth/AuthContext";
import { RequestError } from "../components/AuthUi";
import { NotificationCenter } from "../components/NotificationCenter";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";

const destinations = [
  ["overview-section", "Overview"],
  ["workspace-section", "Workspace"],
  ["projects-section", "Projects & tasks"],
  ["members-section", "Members"],
  ["profile-section", "Profile"],
] as const;

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [membersOpen, setMembersOpen] = useState(false);
  const [activeSection, setActiveSection] = useState("overview-section");
  const [notificationCloseRequest, setNotificationCloseRequest] = useState(0);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const explicitLock = useRef(false);
  const pendingDestination = useRef<string | null>(null);
  const handleNotificationOpenChange = useCallback((open: boolean) => {
    if (open) setNavigationOpen(false);
  }, []);

  function openNotification(notification: Notification) {
    const query = new URLSearchParams({ workspace: String(notification.workspace_id) });
    if (notification.project_id !== null) query.set("project", String(notification.project_id));
    if (notification.task_id !== null) query.set("task", String(notification.task_id));
    navigate(`/app?${query.toString()}`);
  }

  function closeNavigation() {
    setNavigationOpen(false);
    requestAnimationFrame(() => menuButtonRef.current?.focus());
  }
  function activateDestination(id: string) {
    explicitLock.current = true;
    pendingDestination.current = id;
    if (id === "members-section") setMembersOpen(true);
    if (id !== "members-section") {
      const element = document.getElementById(id);
      if (element) setActiveSection(id);
    }
    setNavigationOpen(false);
    requestAnimationFrame(() => requestAnimationFrame(() => { explicitLock.current = false; }));
    if (id === "members-section") return;
    requestAnimationFrame(() => {
      const target = document.getElementById(id);
      if (target) {
        setActiveSection(id);
        target.scrollIntoView({ block: "start" });
        pendingDestination.current = null;
      }
    });
  }

  useEffect(() => {
    if (!membersOpen || pendingDestination.current !== "members-section") return;
    requestAnimationFrame(() => {
      if (pendingDestination.current !== "members-section") return;
      const members = document.getElementById("members-section");
      const target = members ?? document.getElementById("workspace-name");
      if (!target) return;
      setActiveSection(members ? "members-section" : "workspace-section");
      target.scrollIntoView({ block: "start" });
      (target as HTMLElement).focus();
      pendingDestination.current = null;
    });
  }, [membersOpen]);

  useEffect(() => {
    if (!membersOpen && activeSection === "members-section") {
      const fallback = destinations.map(([id]) => id).find((id) => document.getElementById(id));
      setActiveSection(fallback ?? "overview-section");
    }
  }, [activeSection, membersOpen]);

  useEffect(() => {
    const Observer = window.IntersectionObserver;
    if (!Observer) return;
    const ratios = new Map<string, number>();
    const observer = new Observer((entries) => {
      if (explicitLock.current) return;
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).id;
        ratios.set(id, entry.isIntersecting ? entry.intersectionRatio : 0);
      }
      const mounted = destinations.map(([id]) => id).filter((id) => document.getElementById(id));
      const visible = mounted.filter((id) => (ratios.get(id) ?? 0) > 0);
      const candidates = visible.length ? visible : mounted;
      const best = candidates.reduce<string | null>((current, id) => {
        if (current === null) return id;
        return (ratios.get(id) ?? 0) > (ratios.get(current) ?? 0) ? id : current;
      }, null);
      if (best) setActiveSection(best);
    }, { threshold: [0, 0.25, 0.5, 0.75, 1] });
    destinations.forEach(([id]) => {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    });
    return () => observer.disconnect();
  }, [membersOpen]);

  useEffect(() => {
    if (!navigationOpen) return;
    const first = drawerRef.current?.querySelector<HTMLElement>("button, a, [href]");
    first?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { closeNavigation(); return; }
      if (event.key !== "Tab") return;
      const focusable = drawerRef.current?.querySelectorAll<HTMLElement>("button, a, [href], input, select, textarea");
      if (!focusable?.length) return;
      const firstFocusable = focusable[0];
      const lastFocusable = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstFocusable) { event.preventDefault(); lastFocusable.focus(); }
      else if (!event.shiftKey && document.activeElement === lastFocusable) { event.preventDefault(); firstFocusable.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [navigationOpen]);

  async function handleLogout() {
    setSubmitting(true);
    setRequestError(null);
    try { await logout(); navigate("/login", { replace: true }); }
    catch (error) { setRequestError(error instanceof Error ? error.message : "Unable to sign out. Try again."); }
    finally { setSubmitting(false); }
  }

  const navigation = (
    <nav aria-label="Application navigation">
      {destinations.map(([id, label]) => <button className={`sidebar-link${activeSection === id ? " active" : ""}`} key={id} type="button" onClick={() => activateDestination(id)}>{label}</button>)}
    </nav>
  );

  return (
    <div className="app-shell">
      <aside className="app-sidebar" aria-label="Primary navigation">
        <Link className="brand" to="/app"><span className="brand-mark" aria-hidden="true">T</span>TeamFlow</Link>
        {navigation}
      </aside>
      {navigationOpen && <>
        <div className="drawer-backdrop" aria-hidden="true" onClick={closeNavigation} />
        <aside ref={drawerRef} id="mobile-navigation" className="mobile-nav-drawer" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="discussion-heading"><Link className="brand" to="/app"><span className="brand-mark" aria-hidden="true">T</span>TeamFlow</Link><button className="quiet-button" type="button" onClick={closeNavigation}>Close</button></div>
          {navigation}
        </aside>
      </>}
      <div className="app-main">
        <header className="app-header">
          <div className="discussion-heading">
            <button ref={menuButtonRef} className="quiet-button mobile-nav-toggle" type="button" aria-expanded={navigationOpen} aria-controls="mobile-navigation" onClick={() => {
              const opening = !navigationOpen;
              if (opening) { setNavigationOpen(true); setNotificationCloseRequest((current) => current + 1); }
              else closeNavigation();
            }}>{navigationOpen ? "Close navigation" : "Open navigation"}</button>
            <div><p className="eyebrow">TEAMFLOW WORKSPACE</p><strong>Work in focus</strong></div>
          </div>
          <nav aria-label="Account navigation">
            <NotificationCenter
              onNavigate={openNotification}
              closeRequest={notificationCloseRequest}
              onOpenChange={handleNotificationOpenChange}
              suppressFocusReturnOnClose={navigationOpen}
            />
            <span className="account-name">{user?.name}</span>
            <button className="quiet-button" disabled={submitting} onClick={() => void handleLogout()} type="button">{submitting ? "Signing out…" : "Sign out"}</button>
          </nav>
        </header>
        <main className="dashboard">
          <section id="overview-section" aria-labelledby="overview-heading" tabIndex={-1}>
            <p className="eyebrow">YOUR WORKSPACE</p>
            <h1 id="overview-heading">Welcome, {user?.name.split(" ")[0]}.</h1>
            <p className="dashboard-intro">Keep projects, tasks, and team updates moving in one calm place.</p>
          </section>
          <section id="workspace-section" aria-labelledby="workspace-region-heading" tabIndex={-1}>
            <h2 id="workspace-region-heading" className="visually-hidden">Workspace</h2>
            <WorkspaceSwitcher membersOpen={membersOpen} onMembersOpenChange={(open) => setMembersOpen(open)} />
          </section>
          <section id="profile-section" className="account-card" aria-labelledby="account-heading" tabIndex={-1}>
            <div><p className="eyebrow">PROFILE</p><h2 id="account-heading">Account information</h2></div>
            <dl><div><dt>Name</dt><dd>{user?.name}</dd></div><div><dt>Email</dt><dd>{user?.email}</dd></div></dl>
            <RequestError>{requestError}</RequestError>
          </section>
        </main>
      </div>
    </div>
  );
}
