"""Prepare and run a self-contained local Django development environment."""

import argparse
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = ROOT / ".local"
PG_DATA = LOCAL_ROOT / "postgres" / "data"
PG_LOG_DIR = LOCAL_ROOT / "postgres" / "logs"
PG_LOG = PG_LOG_DIR / "postgres.log"
LOCAL_ENV = ROOT / ".env.local"
LOCAL_ENV_EXAMPLE = ROOT / ".env.local.example"
SETTINGS = "fractalschool.local_settings"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def windows_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def run(command, *, capture=False, check=True):
    kwargs = {
        "cwd": ROOT,
        "check": check,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        **windows_options(),
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run([str(part) for part in command], **kwargs)


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_local_env():
    if LOCAL_ENV.is_file():
        return
    if not LOCAL_ENV_EXAMPLE.is_file():
        raise RuntimeError(f"Не найден шаблон настроек: {LOCAL_ENV_EXAMPLE}")
    shutil.copyfile(LOCAL_ENV_EXAMPLE, LOCAL_ENV)
    print(f"Создан файл локальных настроек: {LOCAL_ENV.name}", flush=True)


def load_config(args):
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "Установите зависимости: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc

    ensure_local_env()
    load_dotenv(LOCAL_ENV, override=True)
    if args.db_port is not None:
        os.environ["LOCAL_DB_PORT"] = str(args.db_port)
    if args.site_port is not None:
        os.environ["LOCAL_SITE_PORT"] = str(args.site_port)
    if args.pg_bin is not None:
        os.environ["LOCAL_PG_BIN"] = args.pg_bin

    config = {
        "db_name": os.environ.get("LOCAL_DB_NAME", "fractalschool_local"),
        "db_user": os.environ.get("LOCAL_DB_USER", "fractalschool_local"),
        "db_host": os.environ.get("LOCAL_DB_HOST", "127.0.0.1"),
        "db_port": int(os.environ.get("LOCAL_DB_PORT", "55438")),
        "site_host": os.environ.get("LOCAL_SITE_HOST", "127.0.0.1"),
        "site_port": int(os.environ.get("LOCAL_SITE_PORT", "8001")),
        "pg_bin": os.environ.get("LOCAL_PG_BIN", ""),
    }
    if config["db_host"] not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("LOCAL_DB_HOST разрешён только для localhost или 127.0.0.1.")
    if config["site_host"] not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("LOCAL_SITE_HOST разрешён только для localhost или 127.0.0.1.")
    for key in ("db_name", "db_user"):
        if not IDENTIFIER.fullmatch(config[key]):
            raise RuntimeError(f"{key} должен содержать только латинские буквы, цифры и подчёркивания.")
    for key in ("db_port", "site_port"):
        if not 1 <= config[key] <= 65535:
            raise RuntimeError(f"Некорректный порт: {config[key]}")
    return config


def postgres_bin_candidates(configured):
    if configured:
        yield Path(configured)
    pg_config = shutil.which("pg_config")
    if pg_config:
        result = run([pg_config, "--bindir"], capture=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            yield Path(result.stdout.strip())
    pg_ctl = shutil.which("pg_ctl")
    if pg_ctl:
        yield Path(pg_ctl).parent
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        postgres_root = program_files / "PostgreSQL"
        if postgres_root.is_dir():
            for directory in sorted(postgres_root.iterdir(), reverse=True):
                yield directory / "bin"
        yield Path(r"C:\Program Files\postgresql-17.6-1-windows-x64-binaries\pgsql\bin")


def find_postgres_tools(configured):
    executable = ".exe" if os.name == "nt" else ""
    required = ("pg_ctl", "initdb", "psql", "createdb", "pg_restore")
    for directory in postgres_bin_candidates(configured):
        tools = {name: directory / f"{name}{executable}" for name in required}
        if all(path.is_file() for path in tools.values()):
            return tools
    raise RuntimeError(
        "Не найден PostgreSQL. Установите PostgreSQL и при необходимости укажите "
        "LOCAL_PG_BIN в .env.local или --pg-bin \"путь к bin\"."
    )


def initialize_cluster(tools):
    if (PG_DATA / "PG_VERSION").is_file():
        return
    if PG_DATA.exists() and any(PG_DATA.iterdir()):
        raise RuntimeError(f"Каталог {PG_DATA} не пуст, но не является кластером PostgreSQL.")
    PG_DATA.mkdir(parents=True, exist_ok=True)
    PG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Первый запуск: создаю локальный PostgreSQL в {PG_DATA}…", flush=True)
    run([
        tools["initdb"], "-D", PG_DATA, "--username=postgres", "--auth=trust",
        "--encoding=UTF8", "--no-locale",
    ])


def ensure_postgres(tools, config):
    initialize_cluster(tools)
    status = run([tools["pg_ctl"], "-D", PG_DATA, "status"], capture=True, check=False)
    if status.returncode == 0:
        print("Локальный PostgreSQL уже запущен.", flush=True)
        return
    if port_open(config["db_host"], config["db_port"]):
        raise RuntimeError(
            f"Порт {config['db_port']} занят другим процессом; локальный PostgreSQL не запускался."
        )
    PG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Запускаю локальный PostgreSQL на {config['db_host']}:{config['db_port']}…", flush=True)
    run([
        tools["pg_ctl"], "-D", PG_DATA, "-l", PG_LOG,
        "-o", f"-p {config['db_port']} -h {config['db_host']}",
        "start", "-w", "-t", "30",
    ])


def stop_postgres(tools):
    if not (PG_DATA / "PG_VERSION").is_file():
        print("Локальный PostgreSQL ещё не создан.", flush=True)
        return
    status = run([tools["pg_ctl"], "-D", PG_DATA, "status"], capture=True, check=False)
    if status.returncode != 0:
        print("Локальный PostgreSQL уже остановлен.", flush=True)
        return
    print("Останавливаю локальный PostgreSQL…", flush=True)
    run([tools["pg_ctl"], "-D", PG_DATA, "stop", "-m", "fast", "-w", "-t", "30"])
    print("Локальный PostgreSQL остановлен.", flush=True)


def psql_value(tools, config, sql):
    result = run([
        tools["psql"], "-h", config["db_host"], "-p", config["db_port"],
        "-U", "postgres", "-d", "postgres", "--tuples-only", "--no-align", "-c", sql,
    ], capture=True)
    return result.stdout.strip()


def ensure_database(tools, config, restore_path=None):
    user_exists = psql_value(
        tools, config, f"SELECT 1 FROM pg_roles WHERE rolname = '{config['db_user']}';"
    ) == "1"
    if not user_exists:
        run([
            tools["psql"], "-h", config["db_host"], "-p", config["db_port"],
            "-U", "postgres", "-d", "postgres", "-c",
            f'CREATE ROLE "{config["db_user"]}" LOGIN CREATEDB;',
        ])

    db_exists = psql_value(
        tools, config, f"SELECT 1 FROM pg_database WHERE datname = '{config['db_name']}';"
    ) == "1"
    if restore_path and db_exists:
        raise RuntimeError("--restore разрешён только при первом создании локальной базы.")
    if not db_exists:
        print(f"Создаю локальную базу {config['db_name']}…", flush=True)
        run([
            tools["createdb"], "-h", config["db_host"], "-p", config["db_port"],
            "-U", "postgres", "--owner", config["db_user"], config["db_name"],
        ])
        if restore_path:
            restore_database(tools, config, restore_path)
    print(f"Локальная база {config['db_name']} доступна.", flush=True)


def restore_database(tools, config, restore_path):
    source = Path(restore_path).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Файл восстановления не найден: {source}")
    print(f"Восстанавливаю данные из {source}…", flush=True)
    if source.suffix.lower() == ".sql":
        run([
            tools["psql"], "-h", config["db_host"], "-p", config["db_port"],
            "-U", config["db_user"], "-d", config["db_name"], "-f", source,
        ])
    else:
        run([
            tools["pg_restore"], "-h", config["db_host"], "-p", config["db_port"],
            "-U", config["db_user"], "-d", config["db_name"],
            "--no-owner", "--no-privileges", source,
        ])


def prepare_django(config, *, check_only=False):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        import django
    except ImportError as exc:
        raise RuntimeError(
            "Установите зависимости: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from exc
    django.setup()
    from django.conf import settings

    db = settings.DATABASES["default"]
    expected = (config["db_host"], str(config["db_port"]), config["db_name"])
    actual = (db["HOST"], str(db["PORT"]), db["NAME"])
    if actual != expected or db["HOST"] not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Защитная проверка остановила запуск: Django настроен не на локальную базу.")
    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    legacy_media = ROOT / "media"
    if legacy_media.is_dir() and not any(media_root.iterdir()):
        print("Копирую существующие локальные media в .local…", flush=True)
        shutil.copytree(legacy_media, media_root, dirs_exist_ok=True)
    Path(settings.STATIC_ROOT).mkdir(parents=True, exist_ok=True)

    manage = [sys.executable, "-X", "utf8", ROOT / "manage.py"]
    settings_arg = f"--settings={SETTINGS}"
    run([*manage, "check", settings_arg])
    if check_only:
        run([*manage, "migrate", "--check", settings_arg])
    else:
        run([*manage, "migrate", "--noinput", settings_arg])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only", "--check", action="store_true",
        help="Проверить уже подготовленное окружение, не применяя миграции и не запуская сайт.",
    )
    parser.add_argument(
        "--prepare-only", action="store_true",
        help="Подготовить базу и применить миграции, но не запускать сайт.",
    )
    parser.add_argument("--no-reload", action="store_true", help="Отключить autoreload Django.")
    parser.add_argument("--pg-bin", help="Каталог bin установленного PostgreSQL.")
    parser.add_argument("--db-port", type=int, help="Порт локального PostgreSQL для этого запуска.")
    parser.add_argument("--site-port", type=int, help="Порт локального сайта для этого запуска.")
    parser.add_argument("--restore", help="При первом создании базы восстановить .dump или .sql.")
    parser.add_argument("--stop", action="store_true", help="Остановить локальный PostgreSQL и завершить работу.")
    args = parser.parse_args()

    config = load_config(args)
    if config["db_port"] == config["site_port"]:
        raise RuntimeError("Порты PostgreSQL и сайта должны различаться.")
    if not args.check_only and not args.prepare_only and port_open(config["site_host"], config["site_port"]):
        raise RuntimeError(f"Порт сайта {config['site_port']} уже занят.")

    tools = find_postgres_tools(config["pg_bin"])
    if args.stop:
        stop_postgres(tools)
        return 0
    ensure_postgres(tools, config)
    ensure_database(tools, config, args.restore)
    prepare_django(config, check_only=args.check_only)

    if args.check_only:
        print("Локальное окружение исправно и не требует миграций.", flush=True)
        return 0
    if args.prepare_only:
        print("Локальное окружение подготовлено. Запуск: .\\start-local.cmd", flush=True)
        return 0

    address = f"{config['site_host']}:{config['site_port']}"
    print(
        f"\nСайт: http://{address}/\nАдминка: http://{address}/admin/\n"
        "Остановка Django: Ctrl+C. Локальный PostgreSQL продолжит работать.\n",
        flush=True,
    )
    command = [
        sys.executable, "-X", "utf8", ROOT / "manage.py", "runserver", address,
        f"--settings={SETTINGS}",
    ]
    if args.no_reload:
        command.append("--noreload")
    return subprocess.call([str(part) for part in command], cwd=ROOT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nЛокальный сайт остановлен.")
        raise SystemExit(0)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"\nНе удалось подготовить локальный сайт: {exc}", file=sys.stderr)
        raise SystemExit(1)
