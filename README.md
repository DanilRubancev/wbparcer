# WB Parser — Сервис анализа товаров Wildberries

Веб-приложение для автоматического сбора и анализа данных о товарах
маркетплейса Wildberries с визуализацией на интерактивных дашбордах.

## Стек технологий

| Слой | Технология |
|------|-----------|
| Бэкенд | Python 3.11+ · Flask 3.x · SQLite |
| Парсинг | requests · WB public API (JSON) |
| Фронтенд | Vanilla JS · Chart.js 4 · Lucide Icons |
| Хранение | SQLite (встроен, без доп. установки) |

---

## Быстрый старт

### 1. Клонируйте / скопируйте проект

```bash
git clone <репозиторий>
# или просто распакуйте архив в папку wb-parser
cd wb-parser
```

---

### 2. Создайте виртуальное окружение (venv)

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Windows (cmd.exe)
.venv\Scripts\activate.bat
```

После активации в терминале появится префикс `(.venv)`.

---

### 3. Установите зависимости

```bash
pip install -r backend/requirements.txt
```

**Содержимое requirements.txt:**

```
flask==3.0.3
flask-cors==4.0.1
requests==2.32.3
```

---

### 4. Запустите бэкенд

```bash
cd backend
python app.py
```

Flask запустится на `http://localhost:8000`.
При первом запуске автоматически создаётся база данных `wb_parser.db`
и демо-пользователь `demo / demo123`.

---

### 5. Откройте фронтенд

Откройте файл `frontend/public/index.html` в браузере:

```bash
# macOS
open frontend/public/index.html

# Linux
xdg-open frontend/public/index.html

# Windows
start frontend/public/index.html
```

Либо используйте любой простой HTTP-сервер (Python):

```bash
# В отдельном терминале из папки проекта
python -m http.server 3000 --directory frontend/public
# Затем откройте http://localhost:3000
```

---

## Структура проекта

```
wb-parser/
├── backend/
│   ├── app.py               # Flask-приложение (API + парсер + аналитика)
│   ├── requirements.txt     # Зависимости Python
│   └── wb_parser.db         # SQLite БД (создаётся автоматически)
│
├── frontend/
│   └── public/
│       ├── index.html       # HTML-оболочка SPA
│       ├── style.css        # Дизайн-система (dark/light mode)
│       └── app.js           # SPA на Vanilla JS (Chart.js, роутинг, API-клиент)
│
└── README.md
```

---

## Использование

### Вход

- Демо-аккаунт: логин `demo`, пароль `demo123`
- Или зарегистрируйте новый аккаунт

### Запуск анализа

В поле поиска введите одно из:

| Тип ввода | Пример |
|-----------|--------|
| Поисковый запрос | `наушники беспроводные` |
| Артикул товара WB | `12345678` |
| Ссылка на страницу WB | `https://wildberries.ru/catalog/123/detail.aspx` |

Нажмите **Анализировать** — парсинг запустится в фоне (~3–10 сек).

### Дашборд содержит

| Блок | Описание |
|------|----------|
| **8 KPI-карточек** | Средняя/медианная/мин/макс цена, средний рейтинг, макс. скидка, отзывы, брендов |
| **Распределение цен** | Bar-chart по ценовым диапазонам |
| **Топ брендов** | Горизонтальный bar-chart (топ-12) |
| **Скидки** | Doughnut-chart по диапазонам скидок |
| **Рейтинги** | Bar-chart распределения оценок |
| **Цена vs Рейтинг** | Scatter-plot корреляции |
| **Топ продавцов** | Doughnut-chart по поставщикам |
| **Таблица товаров** | Все товары: артикул, название, бренд, цена, скидка, рейтинг, отзывы |

### Сохранение

Нажмите кнопку **💾 Сохранить** на дашборде — анализ появится в разделе «Сохранённые».

---

## API-эндпоинты

Все запросы кроме `/api/auth/*` требуют заголовка `X-Auth-Token`.

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/auth/login` | Вход |
| `POST` | `/api/auth/register` | Регистрация |
| `POST` | `/api/auth/logout` | Выход |
| `GET` | `/api/searches` | Список поисков |
| `POST` | `/api/searches` | Создать поиск (запуск парсинга) |
| `GET` | `/api/searches/{id}` | Статус поиска |
| `DELETE` | `/api/searches/{id}` | Удалить поиск |
| `GET` | `/api/searches/{id}/products` | Список товаров |
| `GET` | `/api/searches/{id}/analytics` | Данные для дашборда |
| `GET` | `/api/dashboards` | Сохранённые дашборды |
| `POST` | `/api/dashboards` | Сохранить дашборд |
| `DELETE` | `/api/dashboards/{id}` | Удалить дашборд |
| `GET` | `/api/health` | Healthcheck |

---

## Парсинг

Парсер использует публичное JSON API Wildberries (`search.wb.ru`).
При использовании вы подтверждайте согласие с правилами(https://docs.google.com/document/d/1y_1bcSHD8Uk0zHwFGxYz1OPzi0v9wVbJpM4hczHldXs/edit?tab=t.0#heading=h.tyklxmdx88zr)

---

## Деактивация venv

```bash
deactivate
```

---
