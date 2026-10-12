import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import {
  workspaceApi,
  type Workspace,
  type WorkspaceInvitation,
  type WorkspaceMember,
} from "../api/workspaces";
import { useAuth } from "../auth/AuthContext";

interface WorkspaceMembersProps {
  workspace: Workspace;
  onMembershipChanged: () => void;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Workspace members could not be loaded.";
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
  const [requestError, setRequestError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [roleDrafts, setRoleDrafts] = useState<Record<number, "admin" | "member">>({});
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [memberResult, invitationResult] = await Promise.all([
        workspaceApi.listMembers(workspace.id),
        canManage ? workspaceApi.listInvitations(workspace.id) : Promise.resolve({ invitations: [] }),
      ]);
      setMembers(memberResult.members);
      setInvitations(invitationResult.invitations);
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
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
    const normalizedEmail = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setFieldError("Enter a valid email address.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await workspaceApi.invite(workspace.id, normalizedEmail, role);
      setEmail("");
      setSuccess(result.message);
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.fields?.email) {
        setFieldError(error.fields.email);
      } else {
        setRequestError(errorMessage(error));
      }
    } finally {
      setSubmitting(false);
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
    setRequestError(null);
    setInvitationUrl(null);
    try {
      const result = await workspaceApi.getDevelopmentInvitationLink(
        workspace.id,
        invitation.id,
      );
      setInvitationUrl(result.invitation_url);
    } catch (error) {
      setRequestError(errorMessage(error));
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

  return (
    <section className="workspace-members" aria-labelledby="members-heading">
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
                    onClick={() => void removeMember(member)}
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
            <button className="primary-button" disabled={submitting} type="submit">
              {submitting ? "Creating invitation…" : "Create invitation"}
            </button>
          </form>
          <div>
            <h4>Pending invitations</h4>
            {invitations.length === 0 ? (
              <p className="workspace-empty">No pending invitations.</p>
            ) : (
              <ul className="workspace-invitation-list">
                {invitations.map((invitation) => (
                  <li key={invitation.id}>
                    <div>
                      <strong>{invitation.email}</strong>
                      <span>{invitation.role} · expires {new Date(invitation.expires_at).toLocaleString()}</span>
                    </div>
                    {import.meta.env.DEV && (
                      <button
                        className="quiet-button"
                        onClick={() => void showDevelopmentLink(invitation)}
                        type="button"
                      >
                        Get local test link
                      </button>
                    )}
                    {(isOwner || invitation.role === "member") && (
                      <button
                        className="quiet-button danger-button"
                        onClick={() => void revoke(invitation)}
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
          onClick={() => void leaveWorkspace()}
          type="button"
        >
          Leave workspace
        </button>
      )}
    </section>
  );
}
