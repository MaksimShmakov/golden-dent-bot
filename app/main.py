import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from app.config import Settings
from app.scheduler import build_scheduler, schedule_daily_messages
from app.sheets import SheetsClient
from app.storage import SQLiteStateStore
from app.telegram_bot import build_application

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("golden-dent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Settings()
    app.state.config = config
    app.state.sheets = SheetsClient(config.google_sheet_id, config.google_service_account_json)
    app.state.store = SQLiteStateStore(config.data_dir)
    app.state.scheduler = build_scheduler(config.data_dir, config.tz)

    application = build_application(
        config.bot_token,
        config.tz,
        app.state.sheets,
        app.state.store,
        app.state.scheduler,
        config,
    )
    app.state.application = application

    await application.initialize()
    await application.start()
    app.state.polling_enabled = False

    if config.set_webhook and config.webhook_url:
        webhook_url = config.webhook_url.rstrip("/") + config.webhook_path
        await application.bot.set_webhook(
            url=webhook_url,
            secret_token=config.webhook_secret_token,
            drop_pending_updates=True,
        )
        logger.info("Webhook set to %s", webhook_url)
    else:
        if application.updater is None:
            logger.warning("Updater is not available, polling disabled")
        else:
            await application.updater.start_polling(drop_pending_updates=True)
            app.state.polling_enabled = True
            logger.info("Polling started")

    schedule_daily_messages(
        app.state.scheduler,
        application.bot,
        app.state.sheets,
        config.google_appointments_tab,
        config.google_undelivered_tab,
        config.tz,
        config.daily_reminder_hour,
        config.daily_reminder_minute,
        app.state.store,
    )
    app.state.scheduler.start()

    yield

    app.state.scheduler.shutdown(wait=False)
    if app.state.polling_enabled and app.state.application.updater is not None:
        await app.state.application.updater.stop()
    await application.stop()
    await application.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _validate_secret(request: Request) -> None:
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    expected = app.state.config.webhook_secret_token
    if expected and secret != expected:
        raise HTTPException(status_code=403, detail="Invalid secret token")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    _validate_secret(request)
    update_data = await request.json()
    if not update_data:
        raise HTTPException(status_code=400, detail="Empty update")
    update = Update.de_json(update_data, app.state.application.bot)
    await app.state.application.process_update(update)
    return {"ok": True}


@app.post("/webhook/{token}")
async def telegram_webhook_token(request: Request, token: str):
    if token != app.state.config.bot_token:
        raise HTTPException(status_code=403, detail="Invalid token")
    update_data = await request.json()
    update = Update.de_json(update_data, app.state.application.bot)
    await app.state.application.process_update(update)
    return {"ok": True}
