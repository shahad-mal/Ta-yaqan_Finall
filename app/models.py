from app import db
from sqlalchemy.sql import func


# =========================
# 1) Admin
# =========================
class Admin(db.Model):
    __tablename__ = "admin"

    adminid = db.Column(db.Integer, primary_key=True)
    adminname = db.Column(db.String(30), nullable=False)
    adminemail = db.Column(db.String(40), nullable=False)
    adminpassword = db.Column(db.String(255), nullable=False)

    reports = db.relationship("Report", backref="admin", lazy=True)


# =========================
# 2) Verifier_User
# =========================
class VerifierUser(db.Model):
    __tablename__ = "verifier_user"

    verifierid = db.Column(db.Integer, primary_key=True)
    verifiername = db.Column(db.String(30), nullable=False)
    verifieremail = db.Column(db.String(40), nullable=False)
    verifierpassword = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    inputs = db.relationship("RecitationInput", backref="verifier", lazy=True)
    activities = db.relationship("ActivityLog", backref="verifier", lazy=True)
    target_reports = db.relationship(
        "Report",
        backref="target_verifier",
        lazy=True,
        foreign_keys="Report.targetverifierid"
    )


# =========================
# 3) Quran_Surah
# =========================
class QuranSurah(db.Model):
    __tablename__ = "quran_surah"

    surahid = db.Column(db.Integer, primary_key=True)
    surahname = db.Column(db.String(50), nullable=False)
    ayahcount = db.Column(db.Integer, nullable=False)

    ayat = db.relationship("QuranAyah", backref="surah", lazy=True)


# =========================
# 4) Quran_Ayah
# =========================
class QuranAyah(db.Model):
    __tablename__ = "quran_ayah"

    # إذا بقاعدة البيانات صار Identity/Auto increment فهنا طبيعي ما تحطين قيمة ويدخل لحاله
    ayahid = db.Column(db.Integer, primary_key=True)

    surahid = db.Column(db.Integer, db.ForeignKey("quran_surah.surahid"), nullable=False)
    ayahnumber = db.Column(db.Integer, nullable=False)
    ayahtext = db.Column(db.Text, nullable=False)

    errors = db.relationship("ErrorDetails", backref="ayah", lazy=True)


# =========================
# 5) Reciter
# =========================
class Reciter(db.Model):
    __tablename__ = "reciter"

    reciterid = db.Column(db.Integer, primary_key=True)
    recitername = db.Column(db.String(100), nullable=False)
    reciterimage = db.Column(db.String(255), nullable=True)

    audios = db.relationship("SurahAudio", backref="reciter", lazy=True)


# =========================
# 6) Surah_Audio
# =========================
class SurahAudio(db.Model):
    __tablename__ = "surah_audio"

    audioid = db.Column(db.Integer, primary_key=True)

    reciterid = db.Column(db.Integer, db.ForeignKey("reciter.reciterid"), nullable=False)
    surahid = db.Column(db.Integer, db.ForeignKey("quran_surah.surahid"), nullable=False)

    audio_url = db.Column(db.String(500), nullable=False)

    surah = db.relationship("QuranSurah", backref="audios", lazy=True)


# =========================
# 7) Recitation_Inputs
# =========================
class RecitationInput(db.Model):
    __tablename__ = "recitation_inputs"

    inputid = db.Column(db.Integer, primary_key=True)
    verifierid = db.Column(db.Integer, db.ForeignKey("verifier_user.verifierid"), nullable=False)

    inputtype = db.Column(db.Text, nullable=False)
    filepathorlink = db.Column(db.String(255), nullable=False)

    # ✅ الأعمدة الخاصة باسم الملف والمصدر
    original_filename = db.Column(db.String(255), nullable=True)
    source_name = db.Column(db.String(255), nullable=True)
    stored_filename = db.Column(db.String(255), nullable=True)

    processingdate = db.Column(db.DateTime, nullable=True)
    verificationstatus = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))

    # ✅ بيانات السورة والنتيجة
    surahid = db.Column(db.Integer, db.ForeignKey("quran_surah.surahid"), nullable=True)
    startayah = db.Column(db.Integer, nullable=True)
    endayah = db.Column(db.Integer, nullable=True)
    totalwords = db.Column(db.Integer, nullable=True)
    correctwords = db.Column(db.Integer, nullable=True)

    # ✅ علاقة مع السورة
    surah = db.relationship("QuranSurah", backref="inputs", lazy=True)

    errors = db.relationship("ErrorDetails", backref="input", lazy=True)
    reports = db.relationship("Report", backref="input", lazy=True)

    # ✅ التقدم أثناء المعالجة
    progress_percent = db.Column(db.Integer, default=0)
    progress_step = db.Column(db.String(100), nullable=True)
    progress_label = db.Column(db.String(255), nullable=True)

    # ✅ مشاكل الصوت
    audioissue = db.Column(db.Boolean, default=False)
    audioissuereason = db.Column(db.String(255), nullable=True)
    audioissuemessage = db.Column(db.Text, nullable=True)

    # ✅ المدة ووقت المعالجة
    duration_sec = db.Column(db.Integer, nullable=True)
    processing_seconds = db.Column(db.Integer, nullable=True)


# =========================
# 8) Error_Details
# =========================
class ErrorDetails(db.Model):
    __tablename__ = "error_details"

    errorid = db.Column(db.Integer, primary_key=True)

    inputid = db.Column(db.Integer, db.ForeignKey("recitation_inputs.inputid"), nullable=False)
    referenceayahid = db.Column(db.Integer, db.ForeignKey("quran_ayah.ayahid"), nullable=False)

    errortype = db.Column(db.String(15), nullable=False)
    mismatchedtext = db.Column(db.Text, nullable=False)

    # DECIMAL(8,2)
    errorstarttime = db.Column(db.Numeric(8, 2), nullable=True)
    errorendtime = db.Column(db.Numeric(8, 2), nullable=True)


# =========================
# 9) Recitation_Word_Details
# =========================
class RecitationWordDetails(db.Model):
    __tablename__ = "recitation_word_details"

    wordid = db.Column(db.Integer, primary_key=True)

    inputid = db.Column(db.Integer, db.ForeignKey("recitation_inputs.inputid"), nullable=False)

    # اختياري لو تبين ربط مباشر بآية مرجعية
    referenceayahid = db.Column(db.Integer, db.ForeignKey("quran_ayah.ayahid"), nullable=True)

    ayahnumber = db.Column(db.Integer, nullable=True)
    word_index = db.Column(db.Integer, nullable=True)

    expected_word = db.Column(db.Text, nullable=True)
    spoken_word = db.Column(db.Text, nullable=True)

    # القيم العربية النهائية: صحيح / ناقص / زائد / تحريف
    status = db.Column(db.String(20), nullable=False)

    starttime = db.Column(db.Numeric(8, 2), nullable=True)
    endtime = db.Column(db.Numeric(8, 2), nullable=True)

    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    # علاقات
    input = db.relationship("RecitationInput", backref=db.backref("word_details", lazy=True))
    ayah = db.relationship("QuranAyah", backref=db.backref("word_details", lazy=True))


# =========================
# 10) Reports
# =========================
class Report(db.Model):
    __tablename__ = "reports"

    reportid = db.Column(db.Integer, primary_key=True)

    adminid = db.Column(db.Integer, db.ForeignKey("admin.adminid"), nullable=False)
    targetverifierid = db.Column(db.Integer, db.ForeignKey("verifier_user.verifierid"), nullable=True)
    inputid = db.Column(db.Integer, db.ForeignKey("recitation_inputs.inputid"), nullable=True)

    reporttype = db.Column(db.String(20), nullable=False)

    periodstart = db.Column(db.DateTime, nullable=True)
    periodend = db.Column(db.DateTime, nullable=True)

    generatedat = db.Column(db.DateTime, nullable=False, server_default=func.now())
    filepath = db.Column(db.String(255), nullable=True)


# =========================
# 11) Activity_Log
# =========================
class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    activityid = db.Column(db.Integer, primary_key=True)
    verifierid = db.Column(db.Integer, db.ForeignKey("verifier_user.verifierid"), nullable=False)

    activitytype = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Text, nullable=True)
