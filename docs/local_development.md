# Локальный запуск проекта

Локальное окружение изолировано от Railway и production. Код и сценарий
запуска хранятся в Git, а база, журналы, media и static создаются в `.local/`
и на GitHub не отправляются.

## Первый запуск на Windows

Нужны Python и PostgreSQL. Из корня проекта выполните:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start-local.cmd
```

При первом запуске скрипт автоматически:

1. создаёт `.env.local` из `.env.local.example`;
2. находит установленный PostgreSQL;
3. создаёт кластер в `.local/postgres/data`;
4. запускает его только на `127.0.0.1`;
5. создаёт роль и базу `fractalschool_local`;
6. при наличии старой папки `media/` один раз копирует её в `.local/media`;
7. применяет миграции;
8. запускает сайт на <http://127.0.0.1:8001/>.

Следующие запуски выполняются той же командой:

```powershell
.\start-local.cmd
```

Остановка Django — `Ctrl+C`. PostgreSQL остаётся запущенным, чтобы следующий
запуск был быстрым. Локальная база и загруженные файлы сохраняются.

При необходимости остановить и локальный PostgreSQL:

```powershell
.\start-local.cmd --stop
```

## Настройки компьютера

Необязательные параметры находятся в `.env.local`. Файл не входит в Git.
Обычно достаточно значений по умолчанию. Пример доступен в
`.env.local.example`.

Если PostgreSQL не найден автоматически, укажите его каталог `bin`:

```dotenv
LOCAL_PG_BIN=C:\Program Files\PostgreSQL\17\bin
```

Либо передайте путь для одного запуска:

```powershell
.\start-local.cmd --pg-bin "C:\Program Files\PostgreSQL\17\bin"
```

Изменить порт сайта можно в `.env.local` или для одного запуска:

```powershell
.\start-local.cmd --site-port 8010
```

## Полезные режимы

Только подготовить базу и применить миграции:

```powershell
.\start-local.cmd --prepare-only
```

Проверить уже подготовленное окружение без изменения схемы:

```powershell
.\start-local.cmd --check
```

При первом создании базы можно восстановить дамп:

```powershell
.\start-local.cmd --restore D:\FS\backups\backup.dump
```

Восстановление намеренно запрещено, если локальная база уже существует.

## Прямые команды Django

После первого запуска существует `.env.local`, поэтому обычные команды
`manage.py` автоматически используют локальные настройки:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py shell
```

Production использует `fractalschool.settings`, потому что `.env.local` туда не
передаётся. При необходимости настройки всё равно можно выбрать явно через
`--settings`.

## Что переносится между компьютерами

Через Git переносятся код, миграции, `start-local.cmd`, `start_local.py` и
шаблон настроек. Содержимое `.local`, `.env.local`, локальные пользователи,
база и media не переносятся. Для одинаковых данных используйте отдельный дамп
и параметр `--restore`, а media копируйте отдельно.
