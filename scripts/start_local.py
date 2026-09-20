"""Start the existing local exam sandbox, including its PostgreSQL cluster."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = "fractalschool.exam_sandbox_settings"
SITE_ADDRESS = "127.0.0.1:8001"
PG_DATA = ROOT / ".git" / "exam-year-pg" / "data"
PG_LOG = PG_DATA.parent / "server.log"
DEFAULT_PG_BIN = Path(r"C:\Program Files\postgresql-17.6-1-windows-x64-binaries\pgsql\bin")


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def postgres_options():
    # Database helpers must not open extra Windows console windows.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def find_pg_ctl(directory):
    if directory:
        candidate = Path(directory) / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
    elif (DEFAULT_PG_BIN / "pg_ctl.exe").is_file():
        candidate = DEFAULT_PG_BIN / "pg_ctl.exe"
    else:
        located = shutil.which("pg_ctl")
        candidate = Path(located) if located else None
    if candidate is None or not candidate.is_file():
        raise RuntimeError("Не найден pg_ctl. Укажите папку PostgreSQL: .\\start-local.cmd --pg-bin \"путь к bin\".")
    return candidate


def ensure_postgres(pg_ctl):
    if not (PG_DATA / "PG_VERSION").is_file():
        raise RuntimeError(f"Не найден подготовленный кластер PostgreSQL: {PG_DATA}. См. docs/recsys/exam_year_sandbox.md.")
    status = subprocess.run([str(pg_ctl), "-D", str(PG_DATA), "status"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **postgres_options())
    if status.returncode == 0:
        print("PostgreSQL уже запущен.", flush=True)
        return
    if port_open(55438):
        raise RuntimeError("Порт 55438 занят другим процессом. Подготовленный PostgreSQL не запущен; чужой процесс не остановлен.")
    print("Запускаю локальный PostgreSQL на порту 55438…", flush=True)
    # Use files instead of pipes so the background server cannot keep our
    # output pipe open after pg_ctl exits. Wait only for pg_ctl, not its children.
    launcher_log = PG_DATA.parent / "launcher.log"
    with launcher_log.open("ab") as output:
        result = subprocess.run(
            [str(pg_ctl), "-D", str(PG_DATA), "-l", str(PG_LOG), "-o", "-p 55438 -h 127.0.0.1", "start", "-w", "-t", "15"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            timeout=20, **postgres_options(),
        )
    if result.returncode:
        raise RuntimeError(f"PostgreSQL не смог запуститься. Журналы: {launcher_log} и {PG_LOG}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Check/start PostgreSQL and check Django without starting the website or applying migrations.")
    parser.add_argument("--no-reload", action="store_true", help="Disable Django's development autoreloader.")
    parser.add_argument("--pg-bin", help="Directory containing pg_ctl; normally detected automatically.")
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    try:
        import django
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Установите зависимости: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt") from exc
    django.setup()
    from django.conf import settings
    db = settings.DATABASES["default"]
    if (db["HOST"], str(db["PORT"]), db["NAME"]) != ("127.0.0.1", "55438", "exam_year_sandbox"):
        raise RuntimeError("Настройки изменены: запуск разрешён только для локальной exam_year_sandbox на порту 55438.")
    if not args.check_only and port_open(8001):
        raise RuntimeError("Порт 8001 уже занят. Если тестовый сайт запущен, откройте http://127.0.0.1:8001/. Для перезапуска нажмите Ctrl+C в его терминале.")
    ensure_postgres(find_pg_ctl(args.pg_bin))
    try:
        connection = psycopg2.connect(host=db["HOST"], port=db["PORT"], dbname=db["NAME"],
                                      user=db["USER"], password=db.get("PASSWORD", ""), connect_timeout=5)
    except psycopg2.OperationalError as exc:
        raise RuntimeError("Нет подключения к exam_year_sandbox. Проверьте наличие базы и роль examdev по инструкции docs/recsys/exam_year_sandbox.md. Существующая база автоматически не заменяется.") from exc
    connection.close()
    print("База exam_year_sandbox доступна.", flush=True)
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    Path(settings.STATIC_ROOT).mkdir(parents=True, exist_ok=True)
    manage = [sys.executable, "-X", "utf8", str(ROOT / "manage.py")]
    settings_arg = f"--settings={SETTINGS}"
    if args.check_only:
        subprocess.run([*manage, "check", settings_arg], cwd=ROOT, check=True)
        subprocess.run([*manage, "migrate", "--check", settings_arg], cwd=ROOT, check=True)
        print("Проверка завершена. Запуск сайта: .\\start-local.cmd", flush=True)
        return 0
    print("Проверяю миграции тестовой базы…", flush=True)
    subprocess.run([*manage, "migrate", "--noinput", settings_arg], cwd=ROOT, check=True)
    print(f"\nСайт: http://{SITE_ADDRESS}/\nАдминка: http://{SITE_ADDRESS}/admin/\nОстановка сайта: Ctrl+C. Данные сохраняются; PostgreSQL остаётся запущенным.\n", flush=True)
    command = [*manage, "runserver", SITE_ADDRESS, settings_arg]
    if args.no_reload:
        command.append("--noreload")
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nЛокальный сайт остановлен.")
        raise SystemExit(0)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"\nНе удалось запустить локальный сайт: {exc}", file=sys.stderr)
        raise SystemExit(1)
