import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ObsImportDrafts } from "./ObsImportDrafts";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("checks the project on the response, retries an error and only adds audio after a click", async () => {
  const projectId = "project-obs";
  const date = "2026-11-27T10:00:00Z";
  const source = {
    id: "source-obs", project_id: projectId, source_type: "local_upload", original_filename: "Запись OBS.flac",
    mime_type: "audio/flac", size_bytes: 1234, drive_file_url: null, upload_status: "uploaded",
    uploaded_at: date, expires_at: null, created_at: date, updated_at: date, deleted_at: null, delete_reason: null,
  };
  const response = (row: typeof source) => new Response(JSON.stringify({ sources: [row], next_cursor: null, page_size: 50 }));
  const request = vi.fn().mockResolvedValueOnce(response({ ...source, project_id: "other-project" }))
    .mockResolvedValueOnce(response(source));
  const onAdd = vi.fn();
  vi.stubGlobal("fetch", request);
  const { rerender } = render(<ObsImportDrafts projectId={projectId} selectedIds={[]} onAdd={onAdd} />);
  fireEvent.click(screen.getByText("Черновики OBS"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить черновики OBS.");
  expect(screen.queryByText(source.original_filename)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Обновить черновики" }));
  const add = await screen.findByRole("button", { name: "Добавить в Batch" });
  expect(onAdd).not.toHaveBeenCalled();
  fireEvent.click(add);
  expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: source.id, project_id: projectId }));
  rerender(<ObsImportDrafts projectId={projectId} selectedIds={[source.id]} onAdd={onAdd} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "В текущей задаче" })).toBeDisabled());
  expect(request).toHaveBeenCalledTimes(2);
  expect(request.mock.calls.every(([path]) => path === `/api/projects/${projectId}/obs-drafts`)).toBe(true);
});
