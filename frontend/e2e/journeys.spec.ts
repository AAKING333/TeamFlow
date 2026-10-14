import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const runId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;

async function registerAccount(
  page: Page,
  name: string,
  email: string,
  accountPassword: string,
) {
  await page.goto("/register");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(accountPassword);
  await page.getByLabel("Confirm password", { exact: true }).fill(accountPassword);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

async function signIn(
  page: Page,
  email: string,
  accountPassword: string,
  destination: RegExp = /\/app$/,
) {
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(accountPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(destination);
}

test("registers, signs in, and signs out", async ({ page }) => {
  const email = `auth-${runId}@example.invalid`;
  const accountPassword = `Tf-${runId}-Pass!`;
  await registerAccount(page, "Authentication Smoke User", email, accountPassword);
  await signIn(page, email, accountPassword);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to TeamFlow" })).toBeVisible();
});

test("completes collaboration journeys and isolates workspace data", async ({ browser, page }) => {
  test.setTimeout(90_000);
  const ownerEmail = `owner-${runId}@example.invalid`;
  const memberEmail = `member-${runId}@example.invalid`;
  const outsiderEmail = `outsider-${runId}@example.invalid`;
  const memberPassword = `Tf-${runId}-member-Pass!`;
  const ownerPassword = `Tf-${runId}-owner-Pass!`;
  const outsiderPassword = `Tf-${runId}-outsider-Pass!`;
  const workspaceName = `Smoke Workspace ${runId.slice(0, 8)}`;
  const projectName = `Smoke Project ${runId.slice(0, 8)}`;
  const taskTitle = `Smoke Task ${runId.slice(0, 8)}`;
  const commentBody = `Smoke comment ${runId.slice(0, 8)}`;

  await registerAccount(page, "Workspace Owner", ownerEmail, ownerPassword);
  await signIn(page, ownerEmail, ownerPassword);

  const workspaceResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/workspaces") &&
    response.request().method() === "POST"
  );
  await page.getByLabel("New workspace name").fill(workspaceName);
  await page.getByRole("button", { name: "Create workspace" }).click();
  const workspaceResponse = await workspaceResponsePromise;
  expect(workspaceResponse.ok()).toBeTruthy();
  const { workspace } = await workspaceResponse.json() as {
    workspace: { id: number };
  };

  const projectResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/v1/workspaces/${workspace.id}/projects`) &&
    response.request().method() === "POST"
  );
  await page.getByLabel("New project name").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  const projectResponse = await projectResponsePromise;
  expect(projectResponse.ok()).toBeTruthy();
  const { project } = await projectResponse.json() as {
    project: { id: number };
  };
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  await page.getByRole("button", { name: "Manage members" }).click();
  await page.getByLabel("Email address", { exact: true }).last().fill(memberEmail);
  await page.getByLabel("Workspace role").selectOption("member");
  await page.getByRole("button", { name: "Create invitation" }).click();
  const invitation = page.locator(".workspace-invitation-list li").filter({
    hasText: memberEmail,
  });
  await expect(invitation).toBeVisible();
  await invitation.getByRole("button", { name: "Get local test link" }).click();
  const invitationUrl = await page.getByLabel("One-time local invitation link").inputValue();
  await page.getByRole("button", { name: "Clear link" }).click();

  const memberContext = await browser.newContext();
  const memberPage = await memberContext.newPage();
  await memberPage.goto(invitationUrl);
  await expect(memberPage.getByRole("heading", { name: "Join a workspace" })).toBeVisible();
  await memberPage.getByRole("link", { name: "Create an account" }).click();
  await registerAccount(memberPage, "Workspace Member", memberEmail, memberPassword);
  await signIn(memberPage, memberEmail, memberPassword, /\/accept-invitation/);
  await expect(memberPage.getByRole("heading", { name: "Join a workspace" })).toBeVisible();
  await memberPage.getByRole("button", { name: "Accept invitation" }).click();
  await expect(memberPage.getByRole("status")).toContainText("Invitation accepted.");
  await memberPage.getByRole("link", { name: "Continue to TeamFlow" }).click();
  await expect(memberPage.getByRole("status").filter({ hasText: `${workspaceName} · member` }))
    .toBeVisible();
  await expect(memberPage.getByRole("button", { name: "Create project" })).toHaveCount(0);
  await expect(memberPage.getByRole("heading", { name: "Invite someone" })).toHaveCount(0);
  await expect(memberPage.getByRole("heading", { name: projectName })).toBeVisible();

  const taskResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/v1/workspaces/${workspace.id}/projects/${project.id}/tasks`) &&
    response.request().method() === "POST"
  );
  await page.getByLabel("New task").fill(taskTitle);
  await page.getByRole("button", { name: "Create task" }).click();
  const taskResponse = await taskResponsePromise;
  expect(taskResponse.ok()).toBeTruthy();
  const { task } = await taskResponse.json() as { task: { id: number } };
  const taskCard = page.getByRole("button", { name: new RegExp(taskTitle) });
  await taskCard.click();
  await page.getByLabel("Status").selectOption("in_progress");
  await page.getByLabel("Priority").selectOption("high");
  await expect(
    page.getByRole("region", { name: "In Progress tasks" }).getByText(taskTitle),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: new RegExp(`${taskTitle}.*high`) }))
    .toBeVisible();

  await page.getByLabel("Add a comment").fill(commentBody);
  await page.getByRole("button", { name: "Post comment" }).click();
  await expect(page.getByRole("article").filter({ hasText: commentBody })).toBeVisible();

  await page.getByRole("button", { name: "Refresh tasks" }).click();
  await expect(
    page.getByLabel("Assignee").getByRole("option", { name: "Workspace Member" }),
  ).toBeAttached();
  await page.getByLabel("Assignee").selectOption({ label: "Workspace Member" });
  await expect(page.getByRole("button", { name: new RegExp(`Assigned to Workspace Member`) }))
    .toBeVisible();
  const notificationToggle = memberPage.getByRole("button", { name: /Notifications/ });
  await notificationToggle.click();
  await expect(notificationToggle).toHaveAccessibleName("Notifications, 1 unread");
  const notificationPanel = memberPage.getByRole("region", { name: "Notifications" });
  const assignmentNotification = notificationPanel.getByRole("button", {
    name: /You were assigned to a task/,
  });
  await expect(assignmentNotification).toBeVisible();
  await assignmentNotification.click();
  await expect(memberPage.getByRole("heading", { name: "Edit task" })).toBeVisible();
  await expect(notificationToggle).toHaveAccessibleName("Notifications");

  const outsiderContext = await browser.newContext();
  const outsiderPage = await outsiderContext.newPage();
  await registerAccount(outsiderPage, "Workspace Outsider", outsiderEmail, outsiderPassword);
  await signIn(outsiderPage, outsiderEmail, outsiderPassword);
  const workspaceAccess = await outsiderContext.request.get(
    `http://127.0.0.1:5000/api/v1/workspaces/${workspace.id}`,
  );
  const projectAccess = await outsiderContext.request.get(
    `http://127.0.0.1:5000/api/v1/workspaces/${workspace.id}/projects/${project.id}`,
  );
  const taskAccess = await outsiderContext.request.get(
    `http://127.0.0.1:5000/api/v1/workspaces/${workspace.id}/projects/${project.id}/tasks/${task.id}`,
  );
  expect(workspaceAccess.status()).toBe(404);
  expect(projectAccess.status()).toBe(404);
  expect(taskAccess.status()).toBe(404);

  await page.getByLabel("New workspace name").fill(`Other Workspace ${runId.slice(0, 8)}`);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByText("No projects in this workspace yet.")).toBeVisible();
  await expect(page.getByText(taskTitle)).toHaveCount(0);
  await page.getByLabel("Current workspace").selectOption({ label: workspaceName });
  await expect(page.getByRole("button", { name: new RegExp(taskTitle) })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(taskTitle) }).click();
  await expect(page.getByText(commentBody)).toBeVisible();

  await outsiderContext.close();
  await memberContext.close();
});
