# Рекомендательная система ЕГЭ

Этот проект представляет собой пример рекомендательной системы для подготовки к ЕГЭ.

## Установка и запуск

Создайте файл `.env` и укажите переменные окружения:

```bash
SECRET_KEY=changeme
DEBUG=True
ALLOWED_HOSTS=localhost
CSRF_TRUSTED_ORIGINS=http://localhost
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
```

Затем выполните миграции и запустите сервер:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_ege
python manage.py collectstatic --noinput
python manage.py runserver
```

## Примеры cURL

Создание попытки решения задания:

```bash
curl -X POST http://localhost:8000/api/attempts/ \
     -H "Content-Type: application/json" \
     -d '{"task_id": 1, "user_id": 1, "is_correct": true}'
```

Получение списка следующих задач:

```bash
curl "http://localhost:8000/api/next-task/?n=5"
```

## Формат `task_snapshot`

Каждая попытка по заданию хранит снимок данных в поле `VariantTaskAttempt.task_snapshot`.
Структура поля унифицирована и состоит из двух уровней:

```json
{
  "task": {
    "type": "static" | "dynamic",
    "task_id": 1,
    "title": "Задание",
    "description": "Условие",
    "rendering_strategy": "markdown",
    "image": "https://example.com/media/tasks/screenshots/1.png",
    "generator_slug": "math/addition",
    "generation_mode": "generator" | "pre_generated",
    "dataset_id": 42,
    "seed": 123456,
    "payload": {"min": 1, "max": 5},
    "content": {"question": "2 + 2", "choices": [3, 4, 5]},
    "difficulty_level": 40,
    "correct_answer": {"value": 4},
    "answers": {"value": 4},
    "meta": {"difficulty": "base"}
  },
  "response": {"chosen": 4}
}
```

* Для статических заданий `task.type = "static"`, а содержимое заполняется из
  полей модели `Task` (`title`, `description`, `rendering_strategy`) и
  `default_payload`. Поле `difficulty_level` хранит сложность от 0 до 100,
  `correct_answer` содержит эталонный ответ, а `image` — ссылку на скриншот,
  если он загружен.
* Для динамических заданий `task.type = "dynamic"`; поле
  `generator_slug` указывает выбранный генератор, `seed` — детерминированное
  значение, используемое генератором, `payload` и `content` — фактически
  сгенерированные данные, а в `answers` и `meta` хранятся дополнительные
  сведения от генератора (если они есть). Поля `difficulty_level`,
  `correct_answer` и `image` также передаются из исходного задания.

### Доступные динамические генераторы

* `math/addition` — простые арифметические выражения на сложение.
* `words/sequence` — задачи на восстановление пропущенного слова в последовательности.
* `informatics/path-counter` — подсчёт количества программ исполнителя; в
  `default_payload` (и в зафиксированном `payload` снапшота) ожидаются поля
  `start`, `target`, `max_depth`, `limit_value`, `commands`, `transitions`,
  `required_command_index` и `forbidden_command_index`.
* Объект `response` содержит данные, отправленные студентом при решении. Если
  попытка ещё не совершена, ключ `response` отсутствует.

При старте попытки варианта система создаёт техническую запись с
`attempt_number = 0`, которая содержит только часть `task` — это снапшот
задания, отображаемый студенту. Все последующие записи с
`attempt_number > 0` наследуют этот снапшот и добавляют раздел `response`.


## Формулы

### EWMA
Экспоненциально взвешенное среднее оценивает текущий уровень знания, учитывая последние результаты:

$$S_t = \alpha x_t + (1 - \alpha) S_{t-1}$$

где $S_t$ — новое значение, $x_t$ — текущий результат, $\alpha$ — коэффициент сглаживания.

### Beta
Распределение Бета обновляется по числу верных и неверных ответов, описывая вероятность успеха:

$$p(\theta \mid a,b) = \frac{\theta^{a-1}(1-\theta)^{b-1}}{B(a,b)}$$

где $a$ — количество верных ответов + 1, $b$ — количество неверных ответов + 1, $B(a,b)$ — бета-функция.

### Забывание
Модель забывания уменьшает влияние старых ответов во времени:

$$w_t = w_{t-1} e^{-\lambda \Delta t}$$

где $w_t$ — вес знания, $\lambda$ — коэффициент забывания, $\Delta t$ — прошедшее время.

## Заявки на обучение

Приложение `applications` позволяет пользователям оставлять заявки на обучение.
Модель `Application` содержит контактные данные, класс обучения и выбранные
предметы. Форма `ApplicationForm` используется для создания заявок через
веб-интерфейс.

Функция `get_application_price` вычисляет стоимость в зависимости от количества
выбранных предметов. Например:

```python
from applications.utils import get_application_price

price = get_application_price(0)  # стоимость при отсутствии выбранных предметов
price_two = get_application_price(2)  # стоимость при выборе двух предметов
```

