"""Manage the optional OBS link without starting the local STT worker."""
from pathlib import Path
from queue import Empty, SimpleQueue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from .enrollment import begin_enrollment
from .obs_import import process_import, read_recording
from .profile import read_profile, write_profile
from .protocol import APIError, WorkerError


def open_obs_settings(directory: Path, ffmpeg: Path, script: Path):
    window = tk.Tk()
    window.title("VoiceOps Studio · Импорт OBS")
    window.minsize(420, 410)
    panel = ttk.Frame(window, padding=16)
    panel.pack(fill="both", expand=True)
    profile = directory / "identity.json"
    status = tk.StringVar(value="Привяжите импорт и добавьте скрипт в OBS.")
    approval_url = ""
    busy = False
    stop = threading.Event()
    events = SimpleQueue()

    def linked():
        try:
            read_profile(profile, obs_identity=True)
        except WorkerError:
            return False
        return True

    def pair():
        def enroll():
            try:
                attempt = begin_enrollment("Запись OBS", obs=True)
                events.put(("approval", attempt.browser_url))
                webbrowser.open(attempt.browser_url)
                while not stop.wait(2):
                    try:
                        identity = attempt.finish()
                    except APIError as failure:
                        if failure.status in {0, 429, 502, 503, 504}:
                            continue
                        raise
                    if identity:
                        write_profile(profile, identity, obs_identity=True, replace=profile.exists())
                        events.put(("done", "Импорт OBS привязан."))
                        return
            except (WorkerError, OSError):
                events.put(("done", "Не удалось привязать импорт. Проверьте вход в Studio и повторите."))

        start(enroll, "Подтвердите импорт в браузере.")

    def run_selected():
        selection = items.selection()
        if not selection:
            return
        event_id = selection[0]

        def retry():
            try:
                process_import(directory, event_id, ffmpeg)
            except APIError as failure:
                message = ("Привязка недоступна. Переподключите импорт и повторите." if failure.status == 401
                           else "Studio не подтвердила импорт. Запись сохранена. Повторите позже.")
            except (OSError, WorkerError):
                message = "Не удалось подготовить запись. Проверьте файл и выбранную дорожку."
            else:
                message = "Аудио доступно в черновиках OBS на странице «Транскрибации»."
            events.put(("done", message))

        start(retry, "Подготавливаем и загружаем аудио…")

    def start(action, message):
        nonlocal busy
        if not busy:
            busy = True
            status.set(message)
            update_controls()
            threading.Thread(target=action, daemon=True, name="voiceops-obs-ui").start()

    def copy_script():
        window.clipboard_clear()
        window.clipboard_append(str(script))
        status.set("Путь скопирован. Вставьте его при добавлении скрипта в OBS.")

    def update_controls():
        paired = linked()
        pair_button.configure(state="disabled" if busy else "normal",
                              text="Переподключить импорт" if paired else "Привязать импорт OBS")
        retry_button.configure(state="normal" if paired and not busy and items.selection() else "disabled")
        approval_button.configure(state="normal" if approval_url else "disabled")

    def tick():
        nonlocal busy, approval_url
        try:
            while True:
                action, value = events.get_nowait()
                if action == "approval":
                    approval_url = value
                else:
                    busy = False
                    approval_url = ""
                    status.set(value)
        except Empty:
            pass
        pending = {path.stem for path in directory.glob("*.pending")}
        shown = set(items.get_children())
        for event_id in shown - pending:
            items.delete(event_id)
        for event_id in sorted(pending - shown):
            try:
                label = read_recording(directory, event_id).path.name
            except WorkerError:
                continue
            items.insert("", "end", iid=event_id, text=label)
        update_controls()
        window.after(1200, tick)

    ttk.Label(panel, text="Импорт записей OBS").pack(anchor="w")
    ttk.Label(panel, wraplength=385, text=(
        "После привязки в OBS откройте «Инструменты → Скрипты», добавьте скрипт VoiceOps, "
        "выберите аудиодорожку и включите импорт. После Stop Studio получит только аудио."
    )).pack(fill="x", pady=(6, 8))
    pair_button = ttk.Button(panel, command=pair)
    pair_button.pack(anchor="w")
    approval_button = ttk.Button(panel, text="Открыть подтверждение", command=lambda: webbrowser.open(approval_url))
    approval_button.pack(anchor="w", pady=(4, 0))
    ttk.Button(panel, text="Скопировать путь к скрипту", command=copy_script).pack(anchor="w", pady=(4, 12))
    ttk.Label(panel, text="Записи, ожидающие импорта").pack(anchor="w")
    items = ttk.Treeview(panel, show="tree", height=4, selectmode="browse")
    items.pack(fill="both", expand=True, pady=4)
    items.bind("<<TreeviewSelect>>", lambda _event: update_controls())
    retry_button = ttk.Button(panel, text="Повторить импорт записи", command=run_selected)
    retry_button.pack(anchor="w", pady=(0, 8))
    ttk.Label(panel, textvariable=status, wraplength=385).pack(fill="x")

    def close():
        stop.set()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    tick()
    window.mainloop()
