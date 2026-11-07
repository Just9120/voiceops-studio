"""Windows launcher for the existing VoiceOps local worker."""
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from local_worker.enrollment import begin_enrollment
from local_worker.hardware import hardware_inventory
from local_worker.model_download import install_profile, remove_managed_profile
from local_worker.model_profiles import INITIAL_MODEL_REVISIONS, PROFILES, RETAINED_PROFILES
from local_worker.native import NativePaths, NativeServer, model_scratch_root, prepare_audio, probe_audio, verify_installation
from local_worker.parakeet import transcribe_parakeet
from local_worker.process import owned_scratch, single_instance
from local_worker.profile import default_profile, protect, read_profile, write_profile
from local_worker.protocol import APIError, MODEL, PARAKEET_MODEL, RUNTIME_VERSION, Stopped, StudioClient, WorkerError, canonical_id
from local_worker.worker import run

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "VoiceOps Studio Companion"
APP_MUTEX = r"Local\VoiceOpsStudioCompanion"


def legacy_identity(profile):
    return {key: profile[key] for key in ("origin", "token")}


def profile_identity(profile):
    model = profile.get("model", MODEL)
    return model, profile.get("model_revision", INITIAL_MODEL_REVISIONS[model])


def bundled_paths(model_dir, profile):
    # A frozen installer supplies trusted native tools next to the app resources.
    assets = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "voiceops-tools"
    return {
        "runtime": str(assets / "nemo" / "nemo-speech.exe"),
        "decoder": str(model_dir / profile.files[0].name),
        "encoder": str(model_dir / profile.files[1].name) if profile.model == MODEL else None,
        "ffmpeg": str(assets / "ffmpeg.exe"),
        "ffprobe": str(assets / "ffprobe.exe"),
    }


def bundled_probe():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "voiceops-tools" / "probe.wav"


def autostart(enable=None):
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    import winreg
    command = subprocess.list2cmdline([sys.executable, "--background"])
    access = winreg.KEY_QUERY_VALUE | (winreg.KEY_SET_VALUE if enable is not None else 0)
    try:
        handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, access)
    except FileNotFoundError:
        if not enable:
            return False
        handle = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, access)
    with handle as key:
        try:
            previous, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
        except FileNotFoundError:
            previous = None
        if enable is not None and previous is not None and previous != command:
            raise WorkerError("local_autostart_conflict")
        if enable:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, command)
            return True
        if enable is False and previous == command:
            winreg.DeleteValue(key, AUTOSTART_NAME)
            return False
        return previous == command


class CompanionWindow:
    def __init__(self, window, *, background=False):
        self.window = window
        self.legacy_path = default_profile()
        self.identity_path = self.legacy_path.with_name("desktop-identity.json")
        self.runtime_path = self.legacy_path.with_name("desktop-runtime.json")
        self.events = SimpleQueue()
        self.stop = threading.Event()
        self.thread = None
        self.identity = None
        self.legacy = None
        self.approval_url = None
        self.tray = None
        self.exiting = False
        self.inventory_thread = None
        self.inventory_disk = None
        self.probes = {}
        self.answered_install = None
        self.status = tk.StringVar(value="Подключите компьютер к VoiceOps Studio.")
        self.label = tk.StringVar(value="Мой компьютер")
        self.auto = tk.BooleanVar(value=False)
        window.title("VoiceOps Studio — локальный обработчик")
        window.minsize(440, 375)
        window.protocol("WM_DELETE_WINDOW", self.close_window)
        view = ttk.Frame(window, padding=16)
        view.pack(fill="both", expand=True)
        ttk.Label(view, textvariable=self.status, wraplength=410).pack(anchor="w", pady=(0, 10))
        ttk.Label(view, text="Имя компьютера").pack(anchor="w")
        self.label_field = ttk.Entry(view, textvariable=self.label)
        self.label_field.pack(fill="x")
        self.pair_button = ttk.Button(view, text="Связать со Studio", command=self.pair)
        self.import_connection = ttk.Button(view, text="Использовать прежнее подключение", command=self.adopt)
        self.approve_button = ttk.Button(view, text="Открыть подтверждение в браузере", command=self.open_approval)
        self.import_model = ttk.Button(view, text="Импортировать файлы выбранной модели", command=self.import_models)
        ttk.Label(view, text="Модель и версия для установки или запуска").pack(anchor="w", pady=(8, 0))
        defaults = {(profile_id, profile.revision): profile for profile_id, profile in PROFILES.items()}
        self.model_choices = tuple((defaults | RETAINED_PROFILES).items())
        self.model_choice = ttk.Combobox(view, state="readonly", values=self.model_labels())
        self.model_choice.current(0)
        self.model_choice.pack(fill="x")
        self.install_model = ttk.Button(view, text="Выбрать диск и скачать / продолжить", command=self.download_model)
        self.probe_button = ttk.Button(view, text="Проверить скорость выбранной модели", command=self.probe_model)
        self.remove_model_button = ttk.Button(view, text="Удалить выбранную версию", command=self.remove_model)
        self.start_button = ttk.Button(view, text="Запустить обработчик", command=self.start)
        self.stop_button = ttk.Button(view, text="Остановить", command=self.stop_task)
        self.auto_button = ttk.Checkbutton(view, text="Запускать при входе в Windows",
                                           variable=self.auto, command=self.toggle_autostart)
        for button in (self.pair_button, self.import_connection, self.approve_button, self.import_model, self.install_model, self.probe_button, self.remove_model_button,
                       self.start_button, self.stop_button, self.auto_button):
            button.pack(anchor="w", pady=(5, 0))
        restore_active = False
        try:
            if self.legacy_path.exists():
                self.legacy = read_profile(self.legacy_path)
            if self.identity_path.exists():
                self.identity = read_profile(self.identity_path, identity_only=True)
            if self.runtime_path.exists():
                saved = read_profile(self.runtime_path)
                if legacy_identity(saved) == self.identity:
                    for index, (_, candidate) in enumerate(self.model_choices):
                        if (candidate.model, candidate.revision) == profile_identity(saved):
                            self.model_choice.current(index)
                            restore_active = True
                            break
            self.auto.set(autostart())
            if self.identity:
                self.status.set("Компьютер привязан. Обработчик остановлен.")
        except (WorkerError, OSError):
            self.status.set("Не удалось прочитать настройки. Проверьте профиль подключения.")
        self.refresh_model_labels()
        self.enable_controls()
        window.after(100, self.pump)
        window.after(250, self.publish_inventory)
        self.add_tray()
        if background:
            if self.tray:
                window.withdraw()
            if restore_active:
                window.after(0, self.start)

    def add_tray(self):
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (64, 64), "#14213d")
        ImageDraw.Draw(image).polygon([(16, 16), (51, 32), (16, 48)], fill="#74dcff")
        self.tray = pystray.Icon("voiceops_companion", image, "VoiceOps Studio", pystray.Menu(
            pystray.MenuItem("Открыть", lambda *_: self.events.put(("show", None)), default=True),
            pystray.MenuItem("Остановить", lambda *_: self.events.put(("stop", None))),
            pystray.MenuItem("Выход", lambda *_: self.events.put(("exit", None))),
        ))
        threading.Thread(target=self.tray.run, name="voiceops-tray", daemon=True).start()

    def enable_controls(self):
        busy = self.thread is not None
        self.pair_button.configure(state="disabled" if busy else "normal",
                                   text="Переподключить к Studio" if self.identity else "Связать со Studio")
        self.label_field.configure(state="disabled" if busy else "normal")
        self.import_connection.configure(state="normal" if self.legacy and not self.identity and not busy else "disabled")
        self.approve_button.configure(state="normal" if self.approval_url else "disabled")
        self.import_model.configure(state="normal" if self.identity and not busy else "disabled")
        self.install_model.configure(state="normal" if self.identity and not busy else "disabled")
        self.probe_button.configure(state="normal" if self.identity and not busy else "disabled")
        self.remove_model_button.configure(state="normal" if self.identity and not busy else "disabled")
        self.model_choice.configure(state="disabled" if busy else "readonly")
        self.start_button.configure(state="normal" if self.identity and not busy else "disabled")
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.auto_button.configure(state="normal" if getattr(sys, "frozen", False) else "disabled")

    def task(self, action, *, cancelled="Обработчик остановлен."):
        if self.thread:
            return
        self.stop.clear()

        def execute():
            try:
                action()
            except Stopped:
                self.events.put(("status", cancelled))
            except WorkerError as error:
                descriptions = {
                    "local_enrollment_expired": "Запрос истёк. Начните подключение заново.",
                    "local_device_unauthorized": "Доступ отозван. Переподключите компьютер.",
                    "local_profile_unavailable": "Не удалось прочитать защищённый профиль.",
                    "local_runtime_missing": "Отсутствует нужная версия движка или FFmpeg.",
                    "local_model_unavailable": "Файлы модели отсутствуют или имеют другую версию.",
                    "local_model_disk_space": "На выбранном диске недостаточно места.",
                    "local_model_file_invalid": "Файл модели не прошёл проверку размера или SHA-256.",
                    "local_model_path_unsupported": "Выберите папку модели с латинским путём и правом записи.",
                    "local_model_download_interrupted": "Загрузка прервана. Выберите тот же диск, чтобы продолжить.",
                    "local_model_in_use": "Эта версия нужна незавершённому заданию в Studio.",
                    "local_worker_already_running": "Обработчик уже работает на этом компьютере.",
                }
                self.events.put(("status", descriptions.get(error.code, "Действие не завершено. Проверьте подключение к Studio.")))
            except (OSError, ValueError):
                self.events.put(("status", "Не удалось прочитать файлы или подключиться к Studio."))
            finally:
                self.events.put(("done", None))

        self.thread = threading.Thread(target=execute, name="voiceops-companion-task")
        self.thread.start()
        self.enable_controls()

    def pump(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except Empty:
                break
            if kind == "status":
                self.status.set(data)
            elif kind == "approval":
                self.approval_url = data
                self.open_approval()
                self.enable_controls()
            elif kind == "identity":
                self.identity = data
            elif kind == "inventory-disk":
                self.inventory_disk = data
            elif kind == "probe":
                version, probe = data
                self.probes[version] = probe
            elif kind in {"model-removed", "model-updated"}:
                self.probes.pop(data, None)
                self.refresh_model_labels()
            elif kind == "install-request":
                self.accept_install_request(data)
            elif kind == "show":
                self.window.deiconify()
                self.window.lift()
            elif kind == "stop":
                self.stop_task()
            elif kind == "exit":
                self.exiting = True
                self.stop_task()
            elif kind == "done":
                self.thread = None
                self.approval_url = None
                self.refresh_model_labels()
                self.enable_controls()
        if self.exiting and self.thread is None:
            if self.tray:
                self.tray.stop()
            self.window.destroy()
        else:
            self.window.after(100, self.pump)

    def save_identity(self, identity):
        write_profile(self.identity_path, identity, replace=self.identity_path.exists(), identity_only=True)
        self.events.put(("identity", identity))
        self.events.put(("status", "Компьютер привязан. Выберите модель и запустите обработчик."))

    def publish_inventory(self):
        if self.exiting:
            return
        identity, disk = self.identity, self.inventory_disk
        probes = self.probes.copy()
        answered = self.answered_install
        if identity and not (self.inventory_thread and self.inventory_thread.is_alive()):
            def report():
                versions = []
                effective_disk = disk
                for _, candidate in self.model_choices:
                    model, revision = candidate.model, candidate.revision
                    try:
                        profile = self.configured_model(identity, model, revision)
                        if profile is None:
                            continue
                        decoder = Path(profile["paths"]["decoder"])
                        if not decoder.is_file():
                            continue
                    except (OSError, WorkerError):
                        continue
                    effective_disk = effective_disk or decoder.parent
                    verified = False
                    try:
                        verify_installation(
                            NativePaths.from_dict(profile["paths"], model=model), model=model,
                            revision=revision, verified_files=profile["verified_files"], cached_only=True,
                        )
                        verified = True
                    except (OSError, WorkerError):
                        pass
                    versions.append({"model": model, "revision": revision, "verified": verified,
                                     "probe": probes.get((model, revision)) if verified else None})
                defaults = {(item.model, item.revision) for item in PROFILES.values()}
                current = [item for item in versions if (item["model"], item["revision"]) in defaults]
                try:
                    client = StudioClient(identity["origin"], identity["token"])
                    client.json("/inventory", {
                        **hardware_inventory(effective_disk), "model_versions": versions,
                        "installed": [item["model"] for item in current],
                        "verified_installations": [item["model"] for item in current if item["verified"]],
                        "probes": [item["probe"] for item in current if item["probe"] is not None],
                    })
                    pending = client.json("/model-install-request", {"request_id": answered}).get("request")
                    if isinstance(pending, dict) and any((item.model, item.revision) == (
                            pending.get("model"), pending.get("revision")) for item in PROFILES.values()):
                        self.events.put(("install-request", {**pending, "id": canonical_id(pending.get("id"))}))
                except (OSError, WorkerError):
                    pass  # Missing inventory expires; it cannot imply compatibility or readiness.

            self.inventory_thread = threading.Thread(target=report, daemon=True, name="voiceops-inventory")
            self.inventory_thread.start()
        self.window.after(45000, self.publish_inventory)

    def accept_install_request(self, request):
        if self.thread or self.exiting or request["id"] == self.answered_install:
            return
        choice = next((choice for choice in self.model_choices if (choice[1].model, choice[1].revision)
                       == (request["model"], request["revision"])), None)
        if choice is None:
            return
        name = choice[1].name
        self.answered_install = request["id"]
        if messagebox.askyesno("Запрос установки из Studio", f"Установить {name}? Вы сможете выбрать диск.", parent=self.window):
            self.download_model(choice)

    def open_approval(self):
        if self.approval_url:
            webbrowser.open(self.approval_url)

    def pair(self):
        label = self.label.get().strip()
        if not 1 <= len(label) <= 80 or any(ord(char) < 32 or ord(char) == 127 for char in label):
            self.status.set("Введите имя компьютера до 80 символов.")
            return

        def enroll():
            attempt = begin_enrollment(label)
            self.events.put(("status", "Подтвердите подключение в браузере."))
            self.events.put(("approval", attempt.browser_url))
            while not self.stop.is_set():
                try:
                    identity = attempt.finish()
                except APIError as error:
                    if error.status not in {0, 429, 502, 503, 504}:
                        raise
                else:
                    if identity:
                        self.save_identity(identity)
                        return
                self.stop.wait(3)
            raise Stopped("local_worker_interrupted")

        self.task(enroll)

    def adopt(self):
        if self.legacy:
            identity = legacy_identity(self.legacy)

            def adopt_existing():
                StudioClient(identity["origin"], identity["token"]).heartbeat("loading_model")
                self.save_identity(identity)

            self.task(adopt_existing)

    def check_stop(self):
        if self.stop.is_set():
            raise Stopped("local_worker_interrupted")

    def import_models(self):
        identity = self.identity
        choice = self.selected_model()
        chosen = filedialog.askdirectory(title="Папка с весами выбранной модели")
        if not identity or not chosen or not choice:
            return
        if not str(Path(chosen).resolve()).isascii():
            self.status.set("Эта версия движка требует путь без кириллицы. Выберите папку с латинским названием.")
            return

        def validate():
            self.save_model(identity, choice[1], Path(chosen))
            self.events.put(("status", "Модель проверена. Можно запустить обработчик."))

        self.task(validate)

    def selected_model(self):
        index = self.model_choice.current()
        return self.model_choices[index] if index >= 0 else None

    def model_labels(self):
        labels = []
        for _, candidate in self.model_choices:
            installed = False
            if self.identity:
                try:
                    profile = self.configured_model(self.identity, candidate.model, candidate.revision)
                    installed = bool(profile and Path(profile["paths"]["decoder"]).is_file())
                except (OSError, WorkerError):
                    pass
            labels.append(f"{candidate.name} · {candidate.revision[:8]}" + (" · установлена" if installed else ""))
        return labels

    def refresh_model_labels(self):
        index = self.model_choice.current()
        self.model_choice.configure(values=self.model_labels())
        self.model_choice.current(max(index, 0))

    def model_path(self, model, revision):
        return self.runtime_path.with_name(f"desktop-runtime-{model}-{revision}.json")

    def stored_model_paths(self, model, revision):
        yield self.model_path(model, revision)
        if revision == INITIAL_MODEL_REVISIONS[model]:
            yield self.runtime_path.with_name(f"desktop-runtime-{model}.json")

    def configured_model(self, identity, model, revision):
        available = [*self.stored_model_paths(model, revision), self.runtime_path]
        if model == MODEL and self.legacy:
            available.append(self.legacy_path)
        for candidate in available:
            if candidate.exists():
                item = read_profile(candidate)
                if legacy_identity(item) == identity and profile_identity(item) == (model, revision):
                    return item
        return None

    def save_model(self, identity, candidate, directory, *, managed_root=None):
        model, revision = candidate.model, candidate.revision
        values = bundled_paths(directory, candidate)
        self.events.put(("status", "Проверяем файлы модели…"))
        verified = verify_installation(NativePaths.from_dict(values, model=model), model=model, revision=revision,
                                       check=self.check_stop)
        self.check_stop()
        target = self.model_path(model, revision)
        config = {**identity, "model": model, "model_revision": revision, "paths": values, "verified_files": verified}
        if managed_root is not None:
            config["managed_root"] = str(Path(managed_root).resolve())
        write_profile(target, config, replace=target.exists())
        self.events.put(("inventory-disk", directory))
        self.events.put(("model-updated", (model, revision)))

    def download_model(self, choice=None):
        identity = self.identity
        choice = self.selected_model() if choice is None else choice
        if not identity or not choice:
            return
        profile_id, candidate = choice
        chosen = filedialog.askdirectory(title="Диск или папка для моделей VoiceOps Studio")
        if not chosen:
            return
        if not str(Path(chosen).resolve()).isascii():
            self.status.set("Эта версия движка требует путь без кириллицы. Выберите корень диска или папку с латинским названием.")
            return
        self.inventory_disk = chosen

        def download():
            last_percent = None

            def progress(done, total):
                nonlocal last_percent
                percent = done * 100 // total
                if percent != last_percent:
                    last_percent = percent
                    self.events.put(("status", f"Загрузка модели: {done:,} / {total:,} байт ({percent}%)."))

            directory = install_profile(profile_id, chosen, check=self.check_stop, progress=progress,
                                        revision=candidate.revision)
            self.save_model(identity, candidate, directory, managed_root=chosen)
            self.events.put(("status", "Модель скачана. Целостность файлов подтверждена."))

        self.task(download, cancelled="Загрузка приостановлена. Выберите ту же папку, чтобы продолжить.")

    def remove_model(self):
        identity, choice = self.identity, self.selected_model()
        if not identity or not choice:
            return
        profile_id, candidate = choice
        model, revision = candidate.model, candidate.revision
        if not messagebox.askyesno("Удалить версию модели",
            "Скачанные приложением файлы будут удалены с диска. При импорте исходные файлы останутся на месте.",
            parent=self.window):
            return

        def remove():
            with single_instance(self.legacy_path.parent):
                installed = []
                for target in self.stored_model_paths(model, revision):
                    if target.is_file():
                        profile = read_profile(target)
                        if legacy_identity(profile) == identity and profile_identity(profile) == (model, revision):
                            installed.append((target, profile))
                if not installed:
                    self.events.put(("status", "Нет установленной через это приложение версии."))
                    return
                profile = installed[0][1]
                active = read_profile(self.runtime_path) if self.runtime_path.exists() else None
                reply = StudioClient(identity["origin"], identity["token"]).json("/model-removal", {
                    "model": model, "revision": revision,
                })
                if reply != {"allowed": True}:
                    raise WorkerError("local_model_in_use")
                if profile.get("managed_root"):
                    remove_managed_profile(profile_id, profile["managed_root"], profile["paths"]["decoder"],
                                           check=self.check_stop, revision=revision)
                if active and legacy_identity(active) == identity and profile_identity(active) == (model, revision):
                    self.runtime_path.unlink()
                for target, _ in installed:
                    target.unlink()
            self.events.put(("model-removed", (model, revision)))
            self.events.put(("status", "Версия удалена из списка установленных моделей."))

        self.task(remove)

    def probe_model(self):
        identity, choice = self.identity, self.selected_model()
        if not identity or not choice:
            return
        candidate = choice[1]
        model, revision = candidate.model, candidate.revision

        def probe():
            profile = self.configured_model(identity, model, revision)
            if profile is None:
                raise WorkerError("local_model_unavailable")
            paths = NativePaths.from_dict(profile["paths"], model=model)
            root = self.legacy_path.parent
            self.events.put(("status", "Проверяем скорость на короткой синтетической записи…"))
            with single_instance(root), owned_scratch(model_scratch_root(root, paths), prefix="job-") as directory:
                verify_installation(paths, model=model, revision=revision, check=self.check_stop,
                                    verified_files=profile["verified_files"])
                sample = bundled_probe()
                duration = probe_audio(paths, sample, directory, self.check_stop)
                audio = directory / "prepared.wav"
                duration = prepare_audio(paths, sample, audio, start=0, duration=duration, directory=directory,
                                         check=self.check_stop, progress=lambda *_: None)
                started = time.monotonic()
                if model == PARAKEET_MODEL:
                    transcribe_parakeet(paths.runtime, paths.decoder, audio, duration=duration, language="en",
                                        diarize=False, check=self.check_stop)
                else:
                    with NativeServer(paths, directory) as server:
                        server.start(self.check_stop)
                        server.transcribe(audio, duration=duration, language="en", diarize=False, check=self.check_stop)
                elapsed = max(.01, time.monotonic() - started)
                self.events.put(("probe", ((model, revision), {
                    "model": model, "audio_seconds": duration, "elapsed_seconds": elapsed,
                })))
                self.events.put(("status", f"Проба прошла: {duration:.1f} с аудио за {elapsed:.1f} с, включая холодный запуск."))

        self.task(probe)

    def start(self):
        identity = self.identity
        choice = self.selected_model()
        if not identity or not choice:
            return
        candidate = choice[1]

        def run_worker():
            profile = self.configured_model(identity, candidate.model, candidate.revision)
            if profile is None:
                self.events.put(("status", "Сначала скачайте или импортируйте выбранную модель."))
                return
            write_profile(self.runtime_path, profile, replace=self.runtime_path.exists())
            started = False

            def notice(message):
                nonlocal started
                started = True
                self.events.put(("status", message.replace(" Остановка: Ctrl+C.", "")))

            try:
                run(profile, root=self.legacy_path.parent, notice=notice, check_stop=self.check_stop)
            finally:
                if started and self.stop.is_set():
                    try:
                        StudioClient(identity["origin"], identity["token"]).json("/stopped")
                    except APIError:
                        pass  # Studio expires the old heartbeat if it cannot be withdrawn.

        self.task(run_worker)

    def stop_task(self):
        if self.thread:
            self.stop.set()
            self.status.set("Останавливаем…")

    def toggle_autostart(self):
        try:
            self.auto.set(autostart(self.auto.get()))
        except (WorkerError, OSError):
            self.auto.set(False)
            self.status.set("Не удалось изменить автозапуск.")

    def close_window(self):
        if self.tray:
            self.window.withdraw()
        else:
            self.exiting = True
            self.stop_task()


def self_test():
    import pystray
    from PIL import Image  # noqa: F401
    if getattr(sys, "frozen", False):
        external_tray = Path(sys._MEIPASS) / "pystray" / "__init__.py"
        if not external_tray.is_file() or Path(pystray.__file__).resolve() != external_tray.resolve():
            return 1
    probe = b"voiceops-companion-smoke"
    if protect(protect(probe), decrypt=True) != probe:
        return 1
    paths = bundled_paths(Path("."), PROFILES["nemotron-transcribe-iq4-nl"])
    for key, option, version in (("runtime", "--version", RUNTIME_VERSION),
                                  ("ffmpeg", "-version", "8.1.2"), ("ffprobe", "-version", "8.1.2")):
        result = subprocess.run([paths[key], option], capture_output=True, text=True, errors="replace",
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode or version not in result.stdout:
            return 1
    window = tk.Tk()
    window.withdraw()
    ttk.Label(window, text="VoiceOps Studio")
    window.update_idletasks()
    window.destroy()
    return 0


def run_window():
    window = tk.Tk()
    CompanionWindow(window, background="--background" in sys.argv[1:])
    window.mainloop()


def main():
    if "--self-test" in sys.argv[1:]:
        return self_test()
    if "--disable-autostart" in sys.argv[1:]:
        try:
            autostart(False)
        except (WorkerError, OSError):
            return 1
        return 0
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, False, APP_MUTEX)
    if not mutex:
        return 1
    already_running = ctypes.get_last_error() == 183
    try:
        if not already_running:
            run_window()
    finally:
        kernel.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
