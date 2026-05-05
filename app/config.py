import os


def str_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    # ── قاعدة البيانات ──
    SQLALCHEMY_DATABASE_URI = (
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or "postgresql+psycopg2://postgres:Tayaqan123@localhost:5432/tayaqan_db"
    )

    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── البريد الإلكتروني ──
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = str_to_bool(os.getenv("MAIL_USE_TLS"), True)
    MAIL_USE_SSL = str_to_bool(os.getenv("MAIL_USE_SSL"), False)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
    CONTACT_RECEIVER = os.getenv("CONTACT_RECEIVER", MAIL_DEFAULT_SENDER)

    # ── رفع الملفات ──
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB