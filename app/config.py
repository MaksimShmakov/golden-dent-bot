from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    webhook_url: str | None = None
    webhook_path: str = "/webhook"
    webhook_secret_token: str | None = None
    set_webhook: bool = True

    google_sheet_id: str
    google_service_account_json: str
    google_comments_tab: str = "Не готов записаться (комментарии)"
    google_appointments_tab: str = "Записи для бота"
    google_undelivered_tab: str = "Не доставлено"
    google_clients_tab: str = "БД - клиенты"

    tz: str = "Asia/Novosibirsk"
    daily_reminder_hour: int = 9
    daily_reminder_minute: int = 0

    data_dir: str = "/data"
