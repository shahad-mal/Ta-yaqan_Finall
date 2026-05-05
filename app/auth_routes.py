from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from .models import VerifierUser, Admin
import re

auth = Blueprint("auth", __name__, url_prefix="/auth")


@auth.get("/login")
def login():
    return render_template("auth/login.html")


@auth.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    # ── فحص جدول Admin أولاً ──
    admin = Admin.query.filter_by(adminemail=email).first()
    if admin and check_password_hash(admin.adminpassword, password):
        session.clear()
        session["user_id"] = admin.adminid
        session["admin_id"] = admin.adminid
        session["user_name"] = admin.adminname
        session["is_admin"] = True

        flash("تم تسجيل دخول الأدمن بنجاح ✅", "success")
        return redirect(url_for("main.admin_dashboard"))

    # ── فحص جدول VerifierUser ──
    user = VerifierUser.query.filter_by(verifieremail=email).first()
    if not user or not check_password_hash(user.verifierpassword, password):
        flash("البريد أو كلمة المرور غير صحيحة ❌", "error")
        return redirect(url_for("auth.login"))

    session.clear()
    session["user_id"] = user.verifierid
    session["admin_id"] = None
    session["user_name"] = user.verifiername
    session["is_admin"] = False

    return redirect(url_for("main.upload"))


@auth.get("/signup")
def signup():
    return render_template("auth/signup.html")


@auth.post("/signup")
def signup_post():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    # ✅ تحقق من الحقول الفارغة
    if not name or not email or not password or not confirm_password:
        flash("رجاءً املئي كل الحقول ❌", "error")
        return redirect(url_for("auth.signup"))

    # ✅ تحقق من وجود @ في البريد
    if "@" not in email:
        flash("يجب أن يحتوي البريد الإلكتروني على @ ❌", "error")
        return redirect(url_for("auth.signup"))

    # ✅ تحقق من تطابق كلمة المرور
    if password != confirm_password:
        flash("كلمتا المرور غير متطابقتين ❌", "error")
        return redirect(url_for("auth.signup"))

    # ✅ تحقق من أن كلمة المرور 8 أحرف على الأقل
    if len(password) < 8:
        flash("كلمة المرور يجب أن تكون 8 أحرف على الأقل ❌", "error")
        return redirect(url_for("auth.signup"))

    # ✅ تحقق من وجود حرف واحد على الأقل
    if not re.search(r"[A-Za-z]", password):
        flash("كلمة المرور يجب أن تحتوي على حرف واحد على الأقل ❌", "error")
        return redirect(url_for("auth.signup"))

    # ✅ تحقق من أن البريد غير مسجل مسبقًا
    if VerifierUser.query.filter_by(verifieremail=email).first():
        flash("هذا البريد مسجل مسبقًا ❌", "error")
        return redirect(url_for("auth.signup"))

    # تشفير كلمة المرور
    hashed = generate_password_hash(password)

    user = VerifierUser(
        verifiername=name,
        verifieremail=email,
        verifierpassword=hashed
    )
    db.session.add(user)
    db.session.commit()

    # ✅ تسجيل دخول تلقائي بعد إنشاء الحساب
    session.clear()
    session["user_id"] = user.verifierid
    session["admin_id"] = None
    session["user_name"] = user.verifiername
    session["is_admin"] = False

    return redirect(url_for("main.upload"))


@auth.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.home"))