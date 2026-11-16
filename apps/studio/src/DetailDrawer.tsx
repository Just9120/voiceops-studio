import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { lockDocumentScroll } from "./documentScrollLock";

export function DetailDrawer({ title, actions, children, onClose }: { title: string; actions?: ReactNode; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const element = dialog.current;
    const unlock = lockDocumentScroll();
    if (element?.showModal) element.showModal();
    else element?.setAttribute("open", "");
    element?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      // Release native inertness before restoring focus to the list.
      if (element?.open && typeof element.showModal === "function" && typeof element.close === "function") element.close();
      else element?.removeAttribute("open");
      unlock();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(<dialog ref={dialog} className="detail-drawer" aria-labelledby={titleId} data-studio-scroll-lock-allow
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); onClose(); } }}>
    <header><h2 id={titleId}>{title}</h2><button type="button" onClick={onClose}>Закрыть детали</button></header>
    {actions && <div className="detail-drawer-actions">{actions}</div>}
    <div className="detail-drawer-body">{children}</div>
  </dialog>, document.body);
}
