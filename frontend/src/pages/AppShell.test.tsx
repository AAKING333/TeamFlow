import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { notificationApi, workspaceSwitcherState } = vi.hoisted(() => ({
  notificationApi: { list: vi.fn(), markRead: vi.fn(), markAllRead: vi.fn() },
  workspaceSwitcherState: { hasWorkspace: true },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, name: "Ada Lovelace", email: "ada@example.test" },
    logout: vi.fn(),
  }),
}));
vi.mock("../api/notifications", () => ({ notificationApi }));
vi.mock("../components/WorkspaceSwitcher", () => ({
  WorkspaceSwitcher: ({ membersOpen, onMembersOpenChange }: { membersOpen?: boolean; onMembersOpenChange?: (open: boolean) => void }) => (
    <>
      {workspaceSwitcherState.hasWorkspace ? (
        <>
          <button type="button" onClick={() => onMembersOpenChange?.(!membersOpen)}>
            {membersOpen ? "Close member management" : "Manage members"}
          </button>
          {membersOpen && <section id="members-section" tabIndex={-1}>Members</section>}
        </>
      ) : (
        <>
          <label htmlFor="workspace-name">New workspace name</label>
          <input id="workspace-name" />
        </>
      )}
      <section id="projects-section" tabIndex={-1}>Projects</section>
    </>
  ),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  workspaceSwitcherState.hasWorkspace = true;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  notificationApi.list.mockResolvedValue({ notifications: [], unread_count: 0, limit: 25, offset: 0 });
});

describe("authenticated shell surface coordination", () => {
  it("keeps navigation and mobile notifications mutually exclusive with singular focus ownership", async () => {
    const { AppShell } = await import("./AppShell");
    render(<MemoryRouter><AppShell /></MemoryRouter>);

    const menuButton = await screen.findByRole("button", { name: "Open navigation" });
    fireEvent.click(menuButton);
    const navigationDialog = await screen.findByRole("dialog", { name: "Navigation" });
    await waitFor(() => expect(navigationDialog.contains(document.activeElement)).toBe(true));

    const notificationToggle = screen.getByRole("button", { name: "Notifications" });
    fireEvent.click(notificationToggle);
    const notificationDialog = await screen.findByRole("dialog", { name: "Notifications" });
    await waitFor(() => expect(notificationDialog.contains(document.activeElement)).toBe(true));
    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".drawer-backdrop")).toHaveLength(0);
    expect(document.querySelectorAll(".notification-modal-backdrop")).toHaveLength(1);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument());
    expect(notificationToggle).toHaveFocus();

    fireEvent.click(notificationToggle);
    const reopenedNotificationDialog = await screen.findByRole("dialog", { name: "Notifications" });
    await waitFor(() => expect(reopenedNotificationDialog.contains(document.activeElement)).toBe(true));
    fireEvent.click(menuButton);
    const reopenedNavigationDialog = await screen.findByRole("dialog", { name: "Navigation" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument();
      expect(reopenedNavigationDialog.contains(document.activeElement)).toBe(true);
    });
    expect(document.activeElement).not.toBe(notificationToggle);
  });

  it("focuses workspace onboarding when Members is activated without a workspace", async () => {
    workspaceSwitcherState.hasWorkspace = false;
    const { AppShell } = await import("./AppShell");
    render(<MemoryRouter><AppShell /></MemoryRouter>);

    const membersButton = screen.getByRole("button", { name: "Members" });
    fireEvent.click(membersButton);

    await waitFor(() => expect(screen.getByLabelText("New workspace name")).toHaveFocus());
    expect(document.getElementById("members-section")).not.toBeInTheDocument();
    expect(membersButton).not.toHaveClass("active");
    expect(screen.getByRole("button", { name: "Workspace" })).toHaveClass("active");
  });

  it("falls back from the active Members destination after the region closes", async () => {
    const { AppShell } = await import("./AppShell");
    render(<MemoryRouter><AppShell /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Members" }));
    await waitFor(() => expect(document.getElementById("members-section")).toHaveFocus());
    const activeMembersButton = screen.getByRole("button", { name: "Members" });
    await waitFor(() => expect(activeMembersButton).toHaveClass("active"));

    fireEvent.click(screen.getByRole("button", { name: "Close member management" }));
    await waitFor(() => expect(document.getElementById("members-section")).not.toBeInTheDocument());
    expect(activeMembersButton).not.toHaveClass("active");
  });
});
