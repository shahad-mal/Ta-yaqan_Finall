import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_mail import Mail

db = SQLAlchemy()
mail = Mail()


def str_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def create_app():
    # تحميل متغيرات البيئة من .env
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

    app = Flask(__name__)

    # إعدادات المشروع الأساسية
    app.config.from_object("app.config.Config")

    # Override DB URI من Neon (DATABASE_URL)
    db_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
    if db_url:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = db_url

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Secret Key
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    # ✅ Mail Config (المهم هنا)
    app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
    app.config["MAIL_USE_TLS"] = str_to_bool(os.getenv("MAIL_USE_TLS"), True)
    app.config["MAIL_USE_SSL"] = str_to_bool(os.getenv("MAIL_USE_SSL"), False)
    app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER")

    # 🔍 للتأكد (اختياري)
    print("MAIL_SERVER =", app.config["MAIL_SERVER"])
    print("MAIL_PORT =", app.config["MAIL_PORT"])
    print("MAIL_USE_TLS =", app.config["MAIL_USE_TLS"])
    print("MAIL_USE_SSL =", app.config["MAIL_USE_SSL"])
    print("MAIL_USERNAME =", app.config["MAIL_USERNAME"])

    # تفعيل الإضافات
    db.init_app(app)
    mail.init_app(app)

    # تسجيل الـ blueprints
    from app.routes import main
    app.register_blueprint(main)

    from .auth_routes import auth
    app.register_blueprint(auth)

    # إنشاء الجداول
    with app.app_context():
        db.create_all()

    return app