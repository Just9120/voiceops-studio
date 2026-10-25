import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, it } from "vitest";
import { useFormDraft, readFormDraft, clearFormDrafts } from "./formDrafts";
import { composerDraftRows } from "./composerDraft";
import { newComposerRow } from "./batchComposerModel";

beforeEach(() => sessionStorage.clear());
function Form({ project }: { project: string }) {
  const [title, setTitle] = useState("");
  useFormDraft(`test:${project}`, { title }, (value) => {
    if (value && typeof value === "object" && typeof (value as {title?: unknown}).title === "string") setTitle((value as {title: string}).title);
  });
  return <input aria-label="Название" value={title} onChange={(e) => setTitle(e.target.value)} />;
}
it("restores after reload, isolates another project and clears on logout", async () => {
  render(<Form project="owner-a" />);
  await userEvent.type(screen.getByLabelText("Название"), "Synthetic draft");
  cleanup();
  render(<Form project="owner-b" />);
  expect(screen.getByLabelText("Название")).toHaveValue("");
  cleanup();
  render(<Form project="owner-a" />);
  expect(screen.getByLabelText("Название")).toHaveValue("Synthetic draft");
  clearFormDrafts();
  expect(readFormDraft("test:owner-a")).toBeNull();
});
it("rejects malformed storage without breaking the form", () => {
  sessionStorage.setItem("studio-form-draft:v1:test:a", "{broken");
  render(<Form project="a" />);
  expect(screen.getByLabelText("Название")).toHaveValue("");
});
it("restores metadata but never paid bypass consent or arbitrary folder fields", () => {
  const row = newComposerRow();
  row.output_folder={folder_id:"folder", name:"Synthetic folder", web_view_url:"https://drive.google.com/drive/folders/folder"};
  row.segments[0].reprocess_existing=true;
  const result=composerDraftRows([{...row,secret:"never",segments:row.segments.map((s)=>({...s,token:"never"}))}]);
  expect(result?.[0].segments[0].reprocess_existing).toBe(false);
  expect(result?.[0].output_folder?.web_view_url).toBeNull();
  expect(JSON.stringify(result)).not.toContain("never");
  expect(composerDraftRows([row,row])).toBeNull();
  expect(composerDraftRows(Array(51).fill(row))).toBeNull();
});
it("preserves the Disk destination namespace when restoring a draft", () => {
  const row = newComposerRow();
  row.output_folder = { folder_id: "disk-handle", name: "Results", web_view_url: null, provider: "yandex_disk" };
  row.segments[0].output_folder = { ...row.output_folder };
  const restored = composerDraftRows([row]);
  expect(restored?.[0].output_folder?.provider).toBe("yandex_disk");
  expect(restored?.[0].segments[0].output_folder?.provider).toBe("yandex_disk");
  expect(composerDraftRows([{ ...row, output_folder: { ...row.output_folder, provider: "unknown" } }])?.[0].output_folder).toBeNull();
});
