import { type KeyboardEvent, useEffect, useId, useRef } from "react";

export function ConfirmClearDialog({
  title,
  description,
  pending,
  onConfirm,
  onCancel,
  confirmLabel = "Да",
  cancelLabel = "Нет",
  secondaryConfirm,
  fallbackFocus,
  error,
}: {
  title: string;
  description: string;
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  cancelLabel?: string;
  secondaryConfirm?: {label: string; onClick: () => void};
  fallbackFocus?: () => void;
  error?: string;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const fallbackFocusRef = useRef(fallbackFocus);
  fallbackFocusRef.current = fallbackFocus;

  useEffect(() => {
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    cancelRef.current?.focus();
    return () => {
      const target = returnFocusRef.current;
      if (target?.isConnected && !target.matches(":disabled")) target.focus();
      else fallbackFocusRef.current?.();
    };
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (!pending) onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    if (controls.length === 0) {
      event.preventDefault();
      return;
    }
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <div className="confirm-clear-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="card confirm-clear-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <button
            type="button"
            className="danger"
            disabled={pending}
            aria-busy={pending || undefined}
            onClick={onConfirm}
          >
            {pending ? "Очищаем…" : confirmLabel}
          </button>
          {secondaryConfirm && <button type="button" className="danger" disabled={pending} onClick={secondaryConfirm.onClick}>{secondaryConfirm.label}</button>}
          <button
            ref={cancelRef}
            type="button"
            className="secondary"
            disabled={pending}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
