import { cloneElement, isValidElement, useEffect, useId, useRef } from "react";
import type { ReactElement, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  busy?: boolean;
  busyLabel?: string;
}

export function Button({
  variant = "secondary",
  busy = false,
  busyLabel = "Working…",
  children,
  className = "",
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  const variantClass = {
    primary: "button-primary",
    secondary: "button-secondary",
    quiet: "button-quiet",
    danger: "button-secondary button-danger",
  }[variant];
  return (
    <button
      {...props}
      className={`${variantClass} ${className}`.trim()}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      type={type}
    >
      {busy ? busyLabel : children}
    </button>
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string | null;
  children: ReactElement<{ id?: string; "aria-describedby"?: string; "aria-invalid"?: boolean }>;
}

export function Field({ label, htmlFor, hint, error, children }: FieldProps) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children, {
        id: htmlFor,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
      })
    : children;
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {control}
      {hint && <p id={hintId} className="field-hint">{hint}</p>}
      {error && <p id={errorId} className="field-error">{error}</p>}
    </div>
  );
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return <div className={`ui-card ${className}`.trim()}>{children}</div>;
}

export function SummaryCard({
  label,
  value,
  supportingText,
  loading = false,
}: {
  label: string;
  value: ReactNode;
  supportingText?: ReactNode;
  loading?: boolean;
}) {
  return (
    <section className="summary-card" aria-label={label}>
      <p>{label}</p>
      {loading ? <span className="skeleton" role="status">Loading {label.toLowerCase()}…</span> : <strong>{value}</strong>}
      {supportingText && <small>{supportingText}</small>}
    </section>
  );
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-${value}`}>{value.replaceAll("_", " ")}</span>;
}

export function PriorityBadge({ value }: { value: string }) {
  return <span className={`priority-badge priority-${value}`}>{value}</span>;
}

export function RoleBadge({ value }: { value: string }) {
  return <span className="role-badge">{value}</span>;
}

export function Skeleton({ label = "Loading" }: { label?: string }) {
  return <span className="skeleton" role="status" aria-label={label} />;
}

export function EmptyState({ heading, children, action }: { heading: string; children?: ReactNode; action?: ReactNode }) {
  return <section className="empty-state"><h3>{heading}</h3>{children && <p>{children}</p>}{action}</section>;
}

export function ToastRegion({ children }: { children?: ReactNode }) {
  return <div className="toast-region" aria-live="polite" aria-atomic="true">{children}</div>;
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const invokerRef = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const descriptionId = useId();
  useEffect(() => {
    if (!open) {
      if (wasOpen.current) {
        wasOpen.current = false;
        const invoker = invokerRef.current;
        invokerRef.current = null;
        if (invoker?.isConnected) invoker.focus();
      }
      return;
    }
    if (wasOpen.current) return;
    wasOpen.current = true;
    invokerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancelRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea");
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel, open]);
  if (!open) return null;
  return (
    <>
      <div className="drawer-backdrop" aria-hidden="true" onClick={onCancel} />
      <section ref={dialogRef} className="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-heading" aria-describedby={descriptionId}>
        <h2 id="confirm-dialog-heading">{title}</h2>
        <div id={descriptionId}>{children}</div>
        <div className="dialog-actions">
          <button ref={cancelRef} className="quiet-button" type="button" onClick={onCancel}>Cancel</button>
          <button className="quiet-button danger-button" type="button" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </section>
    </>
  );
}
