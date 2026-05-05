from app import create_app, db
from app.models import Reciter, SurahAudio, QuranSurah

app = create_app()

# اختاري 4 قراء وروابطهم من MP3Quran
RECITERS = [
    {
        "name": "عبد الباسط عبد الصمد",
        "server": "https://server7.mp3quran.net/basit"
    },
    {
        "name": "سعد الغامدي",
        "server": "https://server7.mp3quran.net/s_gmd"
    },
    {
        "name": "ماهر المعيقلي",
        "server": "https://server12.mp3quran.net/maher"
    },
    {
        "name": "ياسر الدوسري",
        "server": "https://server11.mp3quran.net/yasser"
    },
]

with app.app_context():
    surahs = QuranSurah.query.order_by(QuranSurah.surahid).all()

    if not surahs:
        print("❌ جدول quran_surah فاضي. لازم تضيفين السور أول.")
        exit()

    for item in RECITERS:
        reciter = Reciter.query.filter_by(recitername=item["name"]).first()

        if not reciter:
            reciter = Reciter(recitername=item["name"])
            db.session.add(reciter)
            db.session.commit()
            print(f"✅ تم إضافة القارئ: {item['name']}")
        else:
            print(f"ℹ️ القارئ موجود: {item['name']}")

        for surah in surahs:
            exists = SurahAudio.query.filter_by(
                reciterid=reciter.reciterid,
                surahid=surah.surahid
            ).first()

            if exists:
                continue

            surah_num = str(surah.surahid).zfill(3)
            audio_url = f"{item['server']}/{surah_num}.mp3"

            audio = SurahAudio(
                reciterid=reciter.reciterid,
                surahid=surah.surahid,
                audio_url=audio_url
            )

            db.session.add(audio)

        db.session.commit()
        print(f"✅ تم إضافة روابط السور للقارئ: {item['name']}")

    print("🎉 انتهى إدخال بيانات الاستماع بنجاح")