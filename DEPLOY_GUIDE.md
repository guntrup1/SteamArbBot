# Полное руководство по деплою Steam Market Bot

Пошаговая инструкция: MongoDB Atlas (бесплатная база данных) → GitHub → деплой на бесплатный сервер.

---

## ЧАСТЬ 1: Бесплатная база данных MongoDB Atlas

MongoDB Atlas — бесплатный облачный MongoDB. Лимиты: 512 МБ хранилища, 1 кластер — для этого бота более чем достаточно.

### Шаг 1: Регистрация

1. Зайди на https://www.mongodb.com/atlas
2. Нажми **Try Free** (или **Start Free**)
3. Зарегистрируйся через Google, GitHub или email + пароль
4. Подтверди email если потребуется

### Шаг 2: Создание бесплатного кластера

1. После входа выбери **M0 FREE** (бесплатный тариф)
2. Провайдер: **AWS** (по умолчанию)
3. Регион: **Frankfurt (eu-central-1)** или ближайший к тебе
4. Имя кластера: `Cluster0` (или любое)
5. Нажми **Create Deployment**

### Шаг 3: Создание пользователя базы данных

1. После создания кластера тебя попросят создать пользователя
2. Выбери **Password** аутентификацию
3. Введи:
   - Username: `steambot` (или любое)
   - Password: нажми **Autogenerate Secure Password** и **СКОПИРУЙ ПАРОЛЬ**
4. Нажми **Create Database User**

### Шаг 4: Настройка доступа по IP

1. Перейди в **Network Access** (слева в меню)
2. Нажми **Add IP Address**
3. Нажми **Allow Access from Anywhere** (0.0.0.0/0) — чтобы сервер мог подключиться
4. Нажми **Confirm**

### Шаг 5: Получение строки подключения

1. Перейди в **Database** (слева в меню)
2. Нажми **Connect** рядом с кластером
3. Выбери **Drivers**
4. Скопируй строку подключения — она выглядит так:
   ```
   mongodb+srv://steambot:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
5. **Замени `<password>` на пароль** который ты скопировал в Шаге 3
6. **Сохрани эту строку** — это твой `MONGO_URL`

### Шаг 6: Проверка подключения (опционально)

Можешь проверить подключение локально:
```bash
pip install "pymongo[srv]"
python -c "from pymongo import MongoClient; c = MongoClient('ТВОЯ_СТРОКА'); print(c.server_info()['version']); print('OK')"
```

> Коллекции и индексы создадутся автоматически при первом запуске приложения (функция `init_db()`).

---

## ЧАСТЬ 2: Деплой на бесплатный сервер

Есть два лучших бесплатных варианта. Рекомендую **Render** — проще всего.

---

### ВАРИАНТ A: Render.com (рекомендуется)

Бесплатный тариф: 750 часов/месяц, засыпает через 15 мин неактивности (просыпается при запросе за ~30 сек).

#### Шаг 1: Залить код на GitHub

1. Создай аккаунт на https://github.com если нет
2. Создай новый репозиторий: нажми **+** → **New repository**
   - Имя: `steam-market-bot`
   - Видимость: **Private** (рекомендуется)
   - НЕ ставь галочку "Initialize with README"
   - Нажми **Create repository**

3. На Replit открой Shell (или локально) и выполни:
   ```bash
   git remote add github https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/steam-market-bot.git
   git push github main
   ```
   (Введи логин и токен GitHub — токен создаётся на https://github.com/settings/tokens → Generate new token → repo scope)

#### Шаг 2: Регистрация на Render

1. Зайди на https://render.com
2. Нажми **Get Started for Free**
3. Зарегистрируйся через **GitHub** (проще всего — сразу свяжет репозитории)

#### Шаг 3: Создание Web Service

1. На дашборде Render нажми **New** → **Web Service**
2. Выбери **Build and deploy from a Git repository** → Next
3. Подключи свой GitHub репозиторий `steam-market-bot`
4. Настройки:
   - **Name**: `steam-market-bot`
   - **Region**: `Frankfurt (EU Central)` (или ближайший)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: **Free**

5. Нажми **Advanced** и добавь **Environment Variables**:
   - `MONGO_URL` = `mongodb+srv://steambot:пароль@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority` (строка из Atlas)
   - `MONGO_DB_NAME` = `steam_bot`
   - `SESSION_SECRET` = любая случайная строка (например: `my_super_secret_key_2024_xyz`)
   - `PORT` = `10000` (Render использует этот порт)

6. Нажми **Create Web Service**

#### Шаг 4: Ожидание деплоя

- Render начнёт установку зависимостей и запуск (~2-5 минут)
- Когда статус станет **Live**, твой бот будет доступен по адресу:
  `https://steam-market-bot.onrender.com`

#### Шаг 5: Обновление кода

Каждый раз когда ты делаешь `git push github main`, Render автоматически пересобирает и деплоит.

---

### ВАРИАНТ B: Railway.app

Railway даёт $5 бесплатного кредита в месяц (~500 часов работы). Не засыпает.

#### Шаг 1: Код на GitHub (как в Варианте A, Шаг 1)

#### Шаг 2: Регистрация

1. Зайди на https://railway.app
2. Войди через GitHub

#### Шаг 3: Создание проекта

1. Нажми **New Project**
2. Выбери **Deploy from GitHub repo**
3. Выбери репозиторий `steam-market-bot`
4. Railway автоматически определит Python проект

#### Шаг 4: Переменные окружения

1. Нажми на сервис → **Variables**
2. Добавь:
   - `MONGO_URL` = строка из Atlas
   - `MONGO_DB_NAME` = `steam_bot`
   - `SESSION_SECRET` = случайная строка
   - `PORT` = `5000`

#### Шаг 5: Настройка запуска

1. В настройках сервиса → **Settings** → **Deploy**
2. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

#### Шаг 6: Публикация

1. Нажми **Generate Domain** в настройках → получишь URL типа `steam-bot.up.railway.app`

---

## ЧАСТЬ 3: Загрузка кода на GitHub (подробно)

Если ты никогда не работал с Git/GitHub:

### Способ 1: Через Replit Shell

```bash
# 1. Создай токен на GitHub: https://github.com/settings/tokens
#    Нажми "Generate new token (classic)", выбери scope "repo", скопируй токен

# 2. В Replit Shell:
git remote add github https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/steam-market-bot.git

# 3. Запуш код:
git push github main
# Логин: твой GitHub username
# Пароль: вставь токен (НЕ пароль от GitHub)
```

### Способ 2: Скачать файлы и залить вручную

1. На Replit нажми на три точки у файлового дерева → **Download as ZIP**
2. На GitHub создай репозиторий
3. Нажми **uploading an existing file** и перетащи все файлы из архива
4. Нажми **Commit changes**

---

## ЧАСТЬ 4: Итоговая структура переменных

| Переменная | Где взять | Пример |
|---|---|---|
| `MONGO_URL` | MongoDB Atlas → Connect → Drivers | `mongodb+srv://steambot:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority` |
| `MONGO_DB_NAME` | Имя базы данных | `steam_bot` |
| `SESSION_SECRET` | Придумай сам | `my_secret_key_2024_abc123` |
| `PORT` | Render: `10000`, Railway: `5000` | `10000` |

---

## ЧАСТЬ 5: После деплоя

1. **Открой URL** — бот должен показать Dashboard
2. **Перейди в Настройки** и заполни:
   - Telegram токен и Chat ID (если используешь уведомления)
   - Steam API ключ (если нужен LIVE режим)
3. **Перейди в Сканер или Арбитраж** — проверь что работает поиск предметов
4. Коллекции и индексы MongoDB создадутся автоматически при первом запуске

---

## Возможные проблемы и решения

### "Application error" на Render
- Проверь логи: Render Dashboard → твой сервис → Logs
- Убедись что `MONGO_URL` указан корректно
- Убедись что `PORT` = `10000`

### Бот засыпает на Render (бесплатный тариф)
- Это нормально — засыпает через 15 мин без запросов
- Просыпается автоматически при следующем запросе (~30 сек)
- Для постоянной работы используй Railway или платный тариф Render

### Ошибка подключения к MongoDB
- Проверь что строка `MONGO_URL` начинается с `mongodb+srv://`
- Проверь что пароль в строке корректный (без `<` и `>`)
- Проверь что в Network Access на Atlas стоит `0.0.0.0/0` (Allow from Anywhere)
- Если пароль содержит спецсимволы (`@`, `#`, `%` и т.д.), закодируй их URL-encoding

### Ошибка "No module named..."
- Убедись что `requirements.txt` в корне проекта
- Пересобери: на Render нажми **Manual Deploy** → **Clear build cache & deploy**

### Ошибка "dnspython" или "DNS resolution"
- Убедись что в `requirements.txt` стоит `pymongo[srv]` (с `[srv]`)
- Это установит `dnspython` для поддержки `mongodb+srv://` строк подключения
