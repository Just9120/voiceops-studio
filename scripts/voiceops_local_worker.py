"""Personal local model companion. Pairing tokens are entered only via hidden stdin."""
import argparse
import getpass
from pathlib import Path
import shutil
import sys

from local_worker.native import NativePaths, verify_installation
from local_worker.profile import default_profile, read_profile, write_profile
from local_worker.protocol import StudioClient, WorkerError
from local_worker.worker import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Локальный обработчик Nemotron для VoiceOps Studio")
    parser.add_argument("--profile", type=Path, help="Защищённый профиль этого пользователя Windows")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="Привязать этот ПК; ключ вводится скрыто")
    pair.add_argument("--origin", default="https://studio.cloud-nodes.net")
    pair.add_argument("--replace", action="store_true", help="Явно заменить прежнюю привязку этого профиля")
    for name in ("runtime", "decoder", "encoder", "ffmpeg", "ffprobe"):
        pair.add_argument("--" + name, type=Path)
    commands.add_parser("run", help="Запустить обработчик; Ctrl+C останавливает его и локальную модель")
    args = parser.parse_args(argv)
    try:
        target = args.profile or default_profile()
        if args.command == "pair":
            if target.exists():
                read_profile(target)
                if not args.replace:
                    raise WorkerError("local_profile_already_exists")
            values = {}
            labels = {"runtime": "nemo-speech.exe", "decoder": "decoder GGUF (IQ4_NL)", "encoder": "encoder GGUF (F16)",
                      "ffmpeg": "ffmpeg.exe", "ffprobe": "ffprobe.exe"}
            for name in labels:
                provided = getattr(args, name)
                found = shutil.which(name if name != "runtime" else "nemo-speech") if name in {"ffmpeg", "ffprobe", "runtime"} else None
                values[name] = str((provided or Path(found or input(f"Путь к {labels[name]}: ").strip().strip('"'))).resolve(strict=True))
            paths = NativePaths.from_dict(values)
            print("Проверяю файлы модели и runtime. На HDD это может занять несколько минут.")
            verified = verify_installation(paths)
            token = getpass.getpass("Одноразовый ключ привязки из Studio (скрытый ввод): ").strip()
            client = StudioClient(args.origin, token)
            # Validate the token with an unready status; pairing does not pretend
            # a model has already loaded or start any transcription.
            client.heartbeat("loading_model")
            write_profile(target, {"origin": client.base, "token": token, "paths": values, "verified_files": verified}, replace=args.replace)
            print("Привязка сохранена для текущего пользователя Windows. Теперь выполните команду run.")
        else:
            run(read_profile(target), root=target.parent)
        return 0
    except KeyboardInterrupt:
        print("Локальный обработчик остановлен.")
        return 130
    except WorkerError as error:
        messages = {
            "local_profile_already_exists": "Этот профиль уже настроен. Для новой привязки используйте pair --replace.",
            "local_profile_changed": "Профиль изменился во время настройки. Повторите привязку.",
            "local_windows_profile_required": "Защищённая привязка этого обработчика поддерживается в Windows.",
            "local_device_unauthorized": "Доступ компьютера отозван. Создайте новый ключ привязки в Studio.",
            "local_model_unavailable": "Файлы модели отсутствуют или не совпадают с проверенной версией.",
            "local_runtime_missing": "Не найден проверенный runtime или FFmpeg. Проверьте пути к установленным файлам.",
            "local_memory_unavailable": "Недостаточно свободной оперативной памяти для модели. Закройте лишние приложения и повторите run.",
            "local_worker_already_running": "Локальный обработчик уже запущен. Второй экземпляр не нужен.",
            "local_connection_lost": "Связь со Studio потеряна. Локальная обработка остановлена; после подключения запустите run заново.",
        }
        print(messages.get(error.code, "Не удалось выполнить действие. Проверьте привязку ПК, файлы модели и доступ к Studio."), file=sys.stderr)
        return 1
    except Exception:
        # No tokens, transcript text, URLs with credentials, native diagnostics
        # or private file paths are printed, including unexpected network errors.
        print("Не удалось выполнить действие. Проверьте привязку ПК, файлы модели и доступ к Studio.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
