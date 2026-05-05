"""
build_quran_json.py
يولّد ملف quran_data.json من قاعدة البيانات
يحتوي على: آيات السور 67-114 + الـ prompt لـ whisper

شغّله مرة واحدة:
    python build_quran_json.py
"""

import os, json, re
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Tayaqan123@localhost:5432/tayaqan_db")

def main():
    import psycopg2
    print("🔗 اتصال بقاعدة البيانات...")
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    # السور من 67 إلى 114
    cur.execute("""
        SELECT surahid, surahname, ayahcount
        FROM quran_surah
        WHERE surahid BETWEEN 67 AND 114
        ORDER BY surahid
    """)
    surahs = cur.fetchall()

    result = {}
    prompt_parts = ["بسم الله الرحمن الرحيم"]

    for (sid, sname, acount) in surahs:
        cur.execute("""
            SELECT ayahid, ayahnumber, ayahtext
            FROM quran_ayah
            WHERE surahid = %s
            ORDER BY ayahnumber
        """, (sid,))
        verses = cur.fetchall()

        ayah_list = []
        for (ayahid, ayahnum, ayahtext) in verses:
            if ayahtext:
                ayah_list.append({
                    "ayahid"    : ayahid,
                    "ayahnumber": ayahnum,
                    "ayahtext"  : ayahtext,
                })

        if ayah_list:
            result[str(sid)] = {
                "surahid"   : sid,
                "surahname" : sname,
                "ayahcount" : acount,
                "ayahs"     : ayah_list,
            }
            # أضف أول آية لكل سورة للـ prompt
            prompt_parts.append(ayah_list[0]["ayahtext"])

    cur.close()
    conn.close()

    # بناء الـ prompt (أول آية من كل سورة)
    prompt = " ".join(prompt_parts)
    words  = prompt.split()
    print(f"✓ prompt: {len(words)} كلمة")

    # الملف النهائي
    output = {
        "_info"  : "Quran data for Ta'yaqan — Surahs 67-114",
        "_prompt": prompt,
        "surahs" : result,
    }

    out_path = os.path.join(os.path.dirname(__file__), "quran_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✓ {len(result)} سورة | محفوظ: {out_path}")
    print(f"✓ حجم الملف: {os.path.getsize(out_path)/1024:.1f} KB")

if __name__ == "__main__":
    main()