import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./apiClient";
import * as drafts from "./realtimeDrafts";
import { RealtimeSessionHistory, parseRealtimeSessionPage } from "./RealtimeSessionHistory";

vi.mock("./apiClient", () => ({api:vi.fn()}));
vi.mock("./realtimeDrafts", async () => ({...await vi.importActual("./realtimeDrafts"),
  listLocalRealtimeDrafts:vi.fn(), loadLocalRealtimeDraft:vi.fn(), deleteLocalRealtimeDraft:vi.fn()}));

function draft(id: string, minute: number) {
  return drafts.makeRealtimeDraft({ownerUserId:"owner", projectId:"project", clientSessionId:id, revision:1,
    committedSegments:[id], partial:"", now:new Date(`2026-11-04T10:0${minute}:00Z`)});
}
const a = draft("session_123456789a", 1);
const b = draft("session_123456789b", 2);
const c = draft("session_123456789c", 3);
const summary = (row: drafts.RealtimeDraft) => ({client_session_id:row.client_session_id,revision:row.revision,updated_at:row.updated_at,
  committed_segment_count:row.committed_segments.length,committed_character_count:row.committed_segments.join("").length,partial_character_count:0});
const payload = (row: drafts.RealtimeDraft) => ({client_session_id:row.client_session_id,revision:row.revision,
  committed_segments:row.committed_segments,partial:row.partial,updated_at:row.updated_at,expires_at:null});

describe("saved Live sessions", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(drafts.listLocalRealtimeDrafts).mockResolvedValue([]);
    vi.mocked(drafts.loadLocalRealtimeDraft).mockResolvedValue(null);
    vi.mocked(drafts.deleteLocalRealtimeDraft).mockResolvedValue(undefined);
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("merges local sessions with all requested server pages and opens the selected text only", async () => {
    const onOpen = vi.fn().mockResolvedValue(undefined);
    vi.mocked(drafts.listLocalRealtimeDrafts).mockResolvedValue([c]);
    vi.mocked(api).mockImplementation(async path => {
      if (path.includes("cursor=")) return {sessions:[summary(b)],next_cursor:null,page_size:1};
      if (path.includes("?page_size=")) return {sessions:[summary(a)],next_cursor:"next_page",page_size:1};
      return {draft:payload(a),cleared:false};
    });
    render(<RealtimeSessionHistory ownerUserId="owner" projectId="project" disabled={false} currentDraft={null} refreshKey={0} onOpen={onOpen} />);
    expect(api).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("Сохранённые Live-сессии"));
    await waitFor(() => expect(screen.getAllByRole("button",{name:"Открыть сессию"})).toHaveLength(2));
    await userEvent.click(screen.getByRole("button",{name:"Загрузить ещё сессии"}));
    await waitFor(() => expect(screen.getAllByRole("button",{name:"Открыть сессию"})).toHaveLength(3));
    await userEvent.click(screen.getAllByRole("button",{name:"Открыть сессию"}).at(-1)!);
    await waitFor(() => expect(onOpen).toHaveBeenCalledOnce());
    expect(onOpen.mock.calls[0][0].client_session_id).toBe(a.client_session_id);
    expect(drafts.loadLocalRealtimeDraft).toHaveBeenCalledWith("owner","project",expect.any(Date),a.client_session_id);
    expect(api).toHaveBeenLastCalledWith(`/projects/project/realtime/drafts/${a.client_session_id}`,expect.objectContaining({cache:"no-store"}));
  });

  it("retires an old local copy after another browser cleared that exact server session", async () => {
    const onOpen = vi.fn().mockResolvedValue(undefined);
    vi.mocked(drafts.listLocalRealtimeDrafts).mockResolvedValue([a,c]);
    vi.mocked(drafts.loadLocalRealtimeDraft).mockResolvedValue(a);
    vi.mocked(api).mockImplementation(async path => path.includes("?page_size=")
      ? {sessions:[],next_cursor:null,page_size:50} : {draft:null,cleared:true});
    render(<RealtimeSessionHistory ownerUserId="owner" projectId="project" disabled={false} currentDraft={null} refreshKey={0} onOpen={onOpen} />);
    await userEvent.click(screen.getByText("Сохранённые Live-сессии"));
    await waitFor(() => expect(screen.getAllByRole("button",{name:"Открыть сессию"})).toHaveLength(2));
    await userEvent.click(screen.getAllByRole("button",{name:"Открыть сессию"}).at(-1)!);
    expect(await screen.findByText(/Эта сессия уже очищена в Studio/)).toBeInTheDocument();
    expect(drafts.deleteLocalRealtimeDraft).toHaveBeenCalledExactlyOnceWith("owner","project",a.client_session_id);
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button",{name:"Открыть сессию"})).toHaveLength(1);
  });

  it("preserves local access during a server outage and prevents switching an active recording", async () => {
    const onOpen = vi.fn().mockResolvedValue(undefined);
    vi.mocked(drafts.listLocalRealtimeDrafts).mockResolvedValue([a]);
    vi.mocked(drafts.loadLocalRealtimeDraft).mockResolvedValue(a);
    vi.mocked(api).mockRejectedValue(new TypeError("synthetic offline"));
    const view = render(<RealtimeSessionHistory ownerUserId="owner" projectId="project" disabled currentDraft={null} refreshKey={0} onOpen={onOpen} />);
    await userEvent.click(screen.getByText("Сохранённые Live-сессии"));
    expect(await screen.findByRole("button",{name:"Открыть сессию"})).toBeDisabled();
    expect(onOpen).not.toHaveBeenCalled();
    view.rerender(<RealtimeSessionHistory ownerUserId="owner" projectId="project" disabled={false} currentDraft={null} refreshKey={0} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("button",{name:"Открыть сессию"}));
    await waitFor(() => expect(onOpen).toHaveBeenCalledOnce());
    expect(screen.getByText(/Открыта локальная копия/)).toBeInTheDocument();
    expect(drafts.deleteLocalRealtimeDraft).not.toHaveBeenCalled();
  });

  it("rejects duplicate sessions, invalid counts and cursor loops rather than hiding partial coverage", () => {
    expect(parseRealtimeSessionPage({sessions:[summary(a),summary(a)],next_cursor:null,page_size:50})).toBeNull();
    expect(parseRealtimeSessionPage({sessions:[{...summary(a),committed_segment_count:5001}],next_cursor:null,page_size:50})).toBeNull();
    expect(parseRealtimeSessionPage({sessions:[],next_cursor:"cursor",page_size:50})).toBeNull();
  });
});
