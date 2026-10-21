import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import {
  workspaceApi,
  type Workspace,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "../api/workspaces";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog } from "./Ui";

interface WorkspaceMembersProps {
  workspace: Workspace;
  onMembershipChanged: () => void;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Workspace members could not be loaded.";
}

function loadErrorMessage(error: unknown, subject: string) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "permission_denied":
        return `You do not have permission to view ${subject.toLowerCase()}.`;
      case "workspace_not_found":
        return "This workspace could not be found. It may have been deleted, or you may have lost access.";
      case "internal_server_error":
        return `${subject} could not be loaded because the server reported an error. If TeamFlow was just updated, run the database migrations (flask db upgrade), restart the backend, and try again.`;
      default:
        return error.message;
    }
  }
  return error instanceof Error ? error.message : `${subject} could not be loaded.`;
}

function deliveryNoticeFor(status: WorkspaceInvitation["delivery_status"]) {
  if (status === "accepted") {
    return "The email was handed to the email server. Inbox delivery is not guaranteed, so if it does not arrive, ask the recipient to check their spam folder.";
  }
  if (status === "development_outbox") {
    return "No email was sent: this server has no email provider configured (local development outbox). Use Get local test link below, or set up SMTP to send real email.";
  }
  return null;
}

function invitationDeliveryLabel(status: WorkspaceInvitation["delivery_status"]) {
  switch (status) {
    case "accepted":
      return "Email provider accepted · inbox delivery not guaranteed";
    case "rejected":
      return "Email provider rejected";
    case "unknown":
      return "Email delivery not confirmed";
    case "development_outbox":
      return "Local link only · no email sent";
    default:
      return "Delivery pending";
  }
}

function deliveryErrorMessage(error: ApiError) {
  switch (error.code) {
    case "invitation_delivery_rejected":
      return error.reason === "misconfigured"
        ? "Email delivery is misconfigured on the server, so no email was sent. Ask the server administrator to check the email settings, then retry the invitation."
        : "The email provider rejected this invitation. No email was sent; retry or revoke it.";
    case "invitation_delivery_unavailable":
      return "Email delivery was not confirmed. No success is recorded; retry the invitation.";
    case "invitation_delivery_superseded":
      return "This invitation changed before delivery completed. Refresh the list and try again.";
    default:
      return error.message;
  }
}

export function WorkspaceMembers({
  workspace,
  onMembershipChanged,
}: WorkspaceMembersProps) {
  const { user } = useAuth();
  const canManage = workspace.role === "owner" || workspace.role === "admin";
  const isOwner = workspace.role === "owner";
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [invitationsError, setInvitationsError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [roleDrafts, setRoleDrafts] = useState<Record<number, "admin" | "member">>({});
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);
  const [deliveryNotice, setDeliveryNotice] = useState<string | null>(null);
  const [resendingId, setResendingId] = useState<number | null>(null);
  const [consumedDevelopmentLinks, setConsumedDevelopmentLinks] = useState<Set<number>>(
    () => new Set(),
  );
  const invitationAttemptVersions = useRef(new Map<number, number>());
  const [confirmation, setConfirmation] = useState<{
    title: string;
    message: string;
    confirmLabel: string;
    action: () => Promise<void>;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    setInvitationsError(null);
    const [memberResult, invitationResult] = await Promise.allSettled([
      workspaceApi.listMembers(workspace.id),
      canManage ? workspaceApi.listInvitations(workspace.id) : Promise.resolve({ invitations: [] }),
    ]);
    if (memberResult.status === "fulfilled") {
      setMembers(memberResult.value.members);
    } else {
      setLoadError(loadErrorMessage(memberResult.reason, "Workspace members"));
    }
    if (invitationResult.status === "fulfilled") {
      setInvitations(invitationResult.value.invitations);
    } else {
      setInvitations([]);
      setInvitationsError(loadErrorMessage(invitationResult.reason, "Pending invitations"));
    }
    setLoading(false);
  }, [canManage, workspace.id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestError(null);
    setSuccess(null);
    setFieldError(null);
    setInvitationUrl(null);
    setDeliveryNotice(null);
    const normalizedEmail = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setFieldError("Enter a valid email address.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await workspaceApi.invite(workspace.id, normalizedEmail, role);
      if (result.delivery_status !== "accepted" && result.delivery_status !== "development_outbox") {
        setRequestError("Invitation was created but delivery was not confirmed. Retry the invitation.");
        await load();
        return;
      }
      setEmail("");
      setSuccess(result.message);
      setDeliveryNotice(deliveryNoticeFor(result.delivery_status));
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.fields?.email) {
        setFieldError(error.fields.email);
      } else if (error instanceof ApiError && error.code === "invitation_delivery_unconfigured") {
        setRequestError("Invitation delivery is not configured; no invitation was created.");
      } else if (error instanceof ApiError) {
        setRequestError(deliveryErrorMessage(error));
        if (
          error.code === "invitation_delivery_rejected" ||
          error.code === "invitation_delivery_unavailable" ||
          error.code === "invitation_delivery_superseded"
        ) {
          await load();
        }
      } else {
        setRequestError(errorMessage(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function resend(invitation: WorkspaceInvitation) {
    setRequestError(null);
    setSuccess(null);
    setDeliveryNotice(null);
    setInvitationUrl(null);
    invitationAttemptVersions.current.set(
      invitation.id,
      (invitationAttemptVersions.current.get(invitation.id) ?? 0) + 1,
    );
    setResendingId(invitation.id);
    try {
      const result = await workspaceApi.resendInvitation(workspace.id, invitation.id);
      if (result.delivery_status === "accepted" || result.delivery_status === "development_outbox") {
        setSuccess(result.message);
        setDeliveryNotice(deliveryNoticeFor(result.delivery_status));
        if (result.delivery_status === "development_outbox") {
          setConsumedDevelopmentLinks((current) => {
            const next = new Set(current);
            next.delete(invitation.id);
            return next;
          });
        }
      } else {
        setRequestError("Invitation was resent but delivery was not confirmed. Retry again if needed.");
      }
      await load();
    } catch (error) {
      setRequestError(error instanceof ApiError ? deliveryErrorMessage(error) : errorMessage(error));
      await load();
    } finally {
      setResendingId(null);
    }
  }

  async function changeRole(member: WorkspaceMember) {
    const nextRole = roleDrafts[member.user_id];
    if (!nextRole || nextRole === member.role) return;
    setRequestError(null);
    setSuccess(null);
    try {
      await workspaceApi.changeMemberRole(workspace.id, member.user_id, nextRole);
      setSuccess(`${member.name}'s role was updated.`);
      await load();
    } catch (error) {
      setRequestError(errorMessage(error));
    }
  }

  async function removeMember(member: WorkspaceMember) {
    setRequestError(null);
    setSuccess(null);
    try {
      await workspaceApi.removeMember(workspace.id, member.user_id);
      setSuccess(`${member.name} was removed from the workspace.`);
      await load();
    } catch (error) {
      setRequestError(errorMessage(error));
    }
  }

  async function revoke(invitation: WorkspaceInvitation) {
    setRequestError(null);
    setSuccess(null);
    setInvitationUrl(null);
    try {
      await workspaceApi.revokeInvitation(workspace.id, invitation.id);
      setSuccess("Invitation revoked.");
      await load();
    } catch (error) {
      setRequestError(errorMessage(error));
    }
  }

  async function showDevelopmentLink(invitation: WorkspaceInvitation) {
    const attempt = invitationAttemptVersions.current.get(invitation.id) ?? 0;
    setRequestError(null);
    setInvitationUrl(null);
    try {
      const result = await workspaceApi.getDevelopmentInvitationLink(
        workspace.id,
        invitation.id,
      );
      if (attempt !== (invitationAttemptVersions.current.get(invitation.id) ?? 0)) {
        return;
      }
      setInvitationUrl(result.invitation_url);
      setConsumedDevelopmentLinks((current) => {
        const next = new Set(current);
        next.add(invitation.id);
        return next;
      });
    } catch (error) {
      if (attempt !== (invitationAttemptVersions.current.get(invitation.id) ?? 0)) {
        return;
      }
      if (error instanceof ApiError && error.code === "development_link_unavailable") {
        setConsumedDevelopmentLinks((current) => {
          const next = new Set(current);
          next.add(invitation.id);
          return next;
        });
        setRequestError("The local invitation link is no longer available.");
        await load();
      } else {
        setRequestError(errorMessage(error));
      }
    }
  }

  async function leaveWorkspace() {
    setRequestError(null);
    try {
      await workspaceApi.leaveWorkspace(workspace.id);
      onMembershipChanged();
    } catch (error) {
      setRequestError(errorMessage(error));
    }
  }

  function confirmRemove(member: WorkspaceMember) {
    setConfirmation({
      title: "Remove member?",
      message: `${member.name} will lose access to this workspace.`,
      confirmLabel: "Remove member",
      action: () => removeMember(member),
    });
  }

  function confirmRevoke(invitation: WorkspaceInvitation) {
    setConfirmation({
      title: "Revoke invitation?",
      message: `The invitation for ${invitation.email} will stop working.`,
      confirmLabel: "Revoke invitation",
      action: () => revoke(invitation),
    });
  }

  function confirmLeave() {
    setConfirmation({
      title: "Leave workspace?",
      message: "You will lose access to this workspace until invited again.",
      confirmLabel: "Leave workspace",
      action: leaveWorkspace,
    });
  }

  return (
    <section
      id="members-section"
      tabIndex={-1}
      className="workspace-members"
      aria-labelledby="members-heading"
    >
      <div className="discussion-heading">
        <div>
          <p className="eyebrow">WORKSPACE ACCESS</p>
          <h3 id="members-heading">Members</h3>
        </div>
        <button className="quiet-button" onClick={() => void load()} type="button">
          Refresh members
        </button>
      </div>
      {loadError && (
        <div>
          <p className="error-banner" role="alert">{loadError}</p>
          <button className="quiet-button" onClick={() => void load()} type="button">
            Try again
          </button>
        </div>
      )}
      {requestError && <p className="error-banner" role="alert">{requestError}</p>}
      {success && <p className="success-banner" role="status">{success}</p>}
      {deliveryNotice && <p className="success-banner" role="status">{deliveryNotice}</p>}
      {loading ? (
        <p role="status">Loading members…</p>
      ) : !loadError ? (
        <ul className="workspace-member-list">
          {members.map((member) => {
            const isSelf = member.user_id === user?.id;
            const canRemove =
              canManage && !isSelf &&
              (isOwner || member.role === "member");
            const draft = roleDrafts[member.user_id] ?? member.role;
            return (
              <li className="workspace-member" key={member.user_id}>
                <div>
                  <strong>{member.name}{isSelf ? " (you)" : ""}</strong>
                  {member.email && <span>{member.email}</span>}
                  <span className="role-badge">{member.role}</span>
                </div>
                {isOwner && !isSelf && member.role !== "owner" && (
                  <div className="member-actions">
                    <label htmlFor={`member-role-${member.user_id}`}>Role</label>
                    <select
                      id={`member-role-${member.user_id}`}
                      value={draft}
                      onChange={(event) =>
                        setRoleDrafts((current) => ({
                          ...current,
                          [member.user_id]: event.target.value as "admin" | "member",
                        }))
                      }
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button
                      className="quiet-button"
                      disabled={draft === member.role}
                      onClick={() => void changeRole(member)}
                      type="button"
                    >
                      Save role
                    </button>
                  </div>
                )}
                {canRemove && (
                  <button
                    className="quiet-button danger-button"
                    onClick={() => confirmRemove(member)}
                    type="button"
                  >
                    Remove
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}

      {canManage && (
        <>
          <form className="workspace-invite-form" onSubmit={invite} noValidate>
            <h4>Invite someone</h4>
            <label htmlFor="workspace-invite-email">Email address</label>
            <input
              id="workspace-invite-email"
              autoComplete="email"
              maxLength={320}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={fieldError ? true : undefined}
              aria-describedby={fieldError ? "workspace-invite-error" : undefined}
            />
            {fieldError && (
              <p className="field-error" id="workspace-invite-error">{fieldError}</p>
            )}
            <label htmlFor="workspace-invite-role">Workspace role</label>
            <select
              id="workspace-invite-role"
              value={role}
              onChange={(event) => setRole(event.target.value as "admin" | "member")}
            >
              <option value="member">Member</option>
              {isOwner && <option value="admin">Admin</option>}
            </select>
            <button className="quiet-button" disabled={submitting} type="submit">
              {submitting ? "Creating invitation…" : "Create invitation"}
            </button>
          </form>
          <div>
            <h4>Pending invitations</h4>
            {invitationsError && (
              <div>
                <p className="error-banner" role="alert">{invitationsError}</p>
                <button className="quiet-button" onClick={() => void load()} type="button">
                  Try again
                </button>
              </div>
            )}
            {invitationsError ? null : invitations.length === 0 ? (
              <p className="workspace-empty">No pending invitations.</p>
            ) : (
              <ul className="workspace-invitation-list">
                {invitations.map((invitation) => (
                  <li key={invitation.id}>
                    <div>
                      <strong>{invitation.email}</strong>
                      <span>{invitation.role} · expires {new Date(invitation.expires_at).toLocaleString()}</span>
                      <span>{invitationDeliveryLabel(invitation.delivery_status)}</span>
                    </div>
                    {import.meta.env.DEV && invitation.delivery_status === "development_outbox" && (
                      consumedDevelopmentLinks.has(invitation.id) ? (
                        <button className="quiet-button" disabled type="button">
                          Local link already retrieved
                        </button>
                      ) : (
                        <button
                          className="quiet-button"
                          disabled={resendingId === invitation.id}
                          onClick={() => void showDevelopmentLink(invitation)}
                          type="button"
                        >
                          Get local test link
                        </button>
                      )
                    )}
                    {(isOwner || invitation.role === "member") && (
                      <button
                        className="quiet-button"
                        disabled={resendingId === invitation.id}
                        onClick={() => void resend(invitation)}
                        type="button"
                      >
                        {resendingId === invitation.id ? "Retrying email…" : "Retry email"}
                      </button>
                    )}
                    {(isOwner || invitation.role === "member") && (
                      <button
                        className="quiet-button danger-button"
                        onClick={() => confirmRevoke(invitation)}
                        type="button"
                      >
                        Revoke
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {invitationUrl && (
              <div className="development-invitation-link">
                <label htmlFor="development-invitation-url">One-time local invitation link</label>
                <input id="development-invitation-url" readOnly value={invitationUrl} />
                <button
                  className="quiet-button"
                  onClick={() => setInvitationUrl(null)}
                  type="button"
                >
                  Clear link
                </button>
              </div>
            )}
          </div>
        </>
      )}
      {!isOwner && (
        <button
          className="quiet-button danger-button"
          onClick={confirmLeave}
          type="button"
        >
          Leave workspace
        </button>
      )}
      <ConfirmDialog
        open={confirmation !== null}
        title={confirmation?.title ?? "Confirm action"}
        confirmLabel={confirmation?.confirmLabel}
        onCancel={() => setConfirmation(null)}
        onConfirm={() => {
          if (!confirmation) return;
          void confirmation.action().finally(() => setConfirmation(null));
        }}
      >
        <p>{confirmation?.message}</p>
      </ConfirmDialog>
    </section>
  );
}
