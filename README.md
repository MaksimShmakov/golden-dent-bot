# Golden Dent Telegram Bot

## Что делает бот

- По `/start` отправляет информационное сообщение с фото `logo-gd.jpg` и 4 кнопками.
- Через 3 дня после первой активации (`/start`) отправляет сообщение с тремя кнопками.
- При "Напомните через 2 недели" ставит повтор через 14 дней.
- При "Не готов записаться" собирает комментарий и пишет в Google Sheets.
- Поддерживает лист **"БД - клиенты"** с актуальными username пользователей бота.
- Ежедневно в 09:00 по Новосибирску:
  - отправляет напоминания о завтрашних записях,
  - отправляет 6-месячные напоминания по дате последнего визита.
- Если сообщение не доставлено (Chat not found), пишет строку в лист "Не доставлено".

Важно: бот может писать пользователю только после того, как пользователь нажал **Start** у бота.

## Формат таблицы

Лист **"Записи для бота"**:
- A: `Date` (например `03.02.2026 18:00`)
- B: `tg_username` (например `@shmaaak`)

Как работает логика:
- Если дата в будущем и равна завтрашнему дню - отправляется сообщение о записи.
- Если дата в прошлом и ровно 6 месяцев назад от сегодня - отправляется 6-месячное напоминание.

Лист **"Не готов записаться (комментарии)"**:
- A: дата и время
- B: tg_username
- C: комментарий

Лист **"Не доставлено"**:
- A: дата и время
- B: tg_username
- C: тип (`appointment` или `6m`)
- D: причина

Лист **"БД - клиенты"**:
- A: `tg_username`

## Локальный запуск

1. Скопируйте `.env.example` в `.env` и заполните значения.
2. Положите сервисный ключ Google в `service-account.json`.
3. Запустите:

```bash
docker compose up --build
```

Если нужен встроенный `nginx`, запускайте с профилем:

```bash
docker compose --profile webhook up --build
```

## Деплой на чистый Ubuntu сервер

1. Подготовьте сервер:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
sudo systemctl enable docker
```

2. Клонируйте проект:

```bash
sudo mkdir -p /opt/golden-dent
sudo chown -R $USER:$USER /opt/golden-dent
git clone https://github.com/MaksimShmakov/golden-dent-bot.git /opt/golden-dent
cd /opt/golden-dent
```

3. Настройте переменные и сервисный ключ:

```bash
cp .env.example .env
nano .env
nano service-account.json
```

4. Запустите бота (polling):

```bash
docker compose up -d --build
docker compose logs -f api
```

## Вебхук и polling

- Если нет домена/https, используйте polling: `SET_WEBHOOK=false` (режим по умолчанию).
- Если есть публичный https домен, включите вебхук: `SET_WEBHOOK=true` и `WEBHOOK_URL`.
- В `WEBHOOK_SECRET_TOKEN` можно задать секрет для Telegram.
- Вебхук принимает запросы на `/webhook`.
- Для запуска с `nginx` используйте профиль `webhook`:

```bash
docker compose --profile webhook up -d --build
```

## Обновление на сервере

```bash
cd /opt/golden-dent
git pull
docker compose up -d --build
```

## CI

В репозитории есть GitHub Actions workflow для ruff и pytest.
