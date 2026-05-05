"""
app/quran_processor.py
"""

import os
import re
import math
import json
import subprocess
import tempfile
from pathlib import Path


MODEL_PATH   = os.path.join(os.path.dirname(__file__), '..', 'final_quran_model_v3')
WHISPER_SIZE = 'medium'
DEVICE       = 'cpu'

_QURAN_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'quran_data.json')
_quran_data      = None


def _load_quran_json() -> dict:
    global _quran_data
    if _quran_data is None:
        if os.path.exists(_QURAN_JSON_PATH):
            with open(_QURAN_JSON_PATH, 'r', encoding='utf-8') as f:
                _quran_data = json.load(f)
        else:
            _quran_data = {}
    return _quran_data


def get_whisper_prompt() -> str:
    data = _load_quran_json()
    return data.get('_prompt', 'بسم الله الرحمن الرحيم تلاوة قرآنية باللغة العربية')


def normalize(text: str) -> str:
    text = str(text or '')
    text = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]', '', text)
    text = text.replace('\u0640', '')
    text = text.translate(str.maketrans({

        'أ': 'ا',

        'إ': 'ا',

        'آ': 'ا',

        'ة': 'ه',

        'ى': 'ي',

        'ؤ': 'و',

        'ئ': 'ي',

    }))
    text = re.sub(r'[^\u0621-\u064A\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def fuzzy_ratio(a: str, b: str) -> int:
    from rapidfuzz import fuzz
    return fuzz.ratio(normalize(a), normalize(b))


def token_exists_fuzzy(target: str, tokens: list, threshold: int = 72) -> bool:
    target = normalize(target)
    for t in tokens:
        if fuzzy_ratio(target, t) >= threshold:
            return True
    return False


def count_fuzzy_matches(target_words: list, tokens: list, threshold: int = 72) -> int:
    used = set()
    count = 0

    for tw in target_words:
        best_idx = -1
        best_sc  = -1

        for i, tk in enumerate(tokens):
            if i in used:
                continue
            sc = fuzzy_ratio(tw, tk)
            if sc > best_sc:
                best_sc = sc
                best_idx = i

        if best_idx >= 0 and best_sc >= threshold:
            used.add(best_idx)
            count += 1

    return count


def _same_word(a: str, b: str) -> bool:
    return normalize(a or '') == normalize(b or '')


def _is_local_repeat(word: str, prev_word: str = '', next_word: str = '') -> bool:
    word      = normalize(word)
    prev_word = normalize(prev_word)
    next_word = normalize(next_word)

    if not word:
        return False

    if prev_word and word == prev_word:
        return True

    if next_word and word == next_word:
        return True

    return False

def _matches_any_word(word: str, candidates: list, threshold: int = 78) -> bool:
    word = normalize(word)
    for c in candidates:
        if fuzzy_ratio(word, c) >= threshold:
            return True
    return False

def _word_count(text: str) -> int:
    return len(normalize(text).split())


def detect_audio_issue(
    wh1_text: str,
    wh2_text: str,
    corrected: list,
    surah_info: dict,
) -> dict:
    wh1_norm = normalize(wh1_text)
    wh2_norm = normalize(wh2_text)

    wh1_count = len(wh1_norm.split())
    wh2_count = len(wh2_norm.split())

    correct_count = sum(
        1 for w in corrected
        if not w.get('missing') and not w.get('extra')
    )
    missing_count = sum(1 for w in corrected if w.get('missing'))
    extra_count   = sum(1 for w in corrected if w.get('extra'))
    total_count   = len(corrected)

    ayahcount = int(surah_info.get('ayahcount', 0) or 0)

    if total_count > 0:
        missing_ratio = missing_count / total_count
        extra_ratio   = extra_count / total_count
        correct_ratio = correct_count / total_count
    else:
        missing_ratio = 0.0
        extra_ratio   = 0.0
        correct_ratio = 0.0

    # سور طويلة
    if ayahcount >= 40:
        if wh2_count <= 20:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'too_short_for_long_surah',
                'audio_issue_message': 'تعذر التحقق من التلاوة لأن التسجيل يبدو غير واضح أو يحتوي على صدى أو تشويش مرتفع.',
            }

        if missing_ratio >= 0.70 and correct_ratio <= 0.25:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'high_missing_long_surah',
                'audio_issue_message': 'جودة التسجيل غير مناسبة للتحقق الدقيق. قد يحتوي التسجيل على صدى أو تشويش أو انخفاض في وضوح الصوت.',
            }

    # سور متوسطة
    elif ayahcount >= 12:
        if wh2_count <= 10:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'too_short_medium_surah',
                'audio_issue_message': 'تعذر استخراج نص كافٍ من التلاوة. يرجى رفع تسجيل أوضح.',
            }

        if missing_ratio >= 0.65 and correct_ratio <= 0.30:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'high_missing_medium_surah',
                'audio_issue_message': 'التسجيل غير واضح بما يكفي للتحقق. قد يحتوي على صدى أو تشويش.',
            }

    # سور قصيرة
    else:
        # لا نكون متشددين هنا حتى ما نخرب القصار
        if wh2_count <= 3 and correct_count <= 2:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'very_short_short_surah',
                'audio_issue_message': 'التسجيل قصير جدًا أو غير واضح، وتعذر التحقق منه بدقة.',
            }

    # إذا أغلب الناتج زيادات أو أخطاء غريبة
    if total_count >= 8 and (missing_ratio + extra_ratio) >= 0.80:
        return {
            'audio_issue': True,
            'audio_issue_reason': 'alignment_collapsed',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    return {
        'audio_issue': False,
        'audio_issue_reason': '',
        'audio_issue_message': '',
    }

def detect_mid_echo_collapse(wh1_text: str, wh2_text: str, corrected: list, surah_info: dict) -> dict:
    """
    كشف الحالات التي لا يكون فيها التسجيل منهارًا بالكامل،
    لكنه مشوّه بما يكفي لعدم الوثوق بالتقرير النهائي.
    هذا يفيد مع الصدى المتوسط/العالي.
    """

    wh1_norm = normalize(wh1_text)
    wh2_norm = normalize(wh2_text)

    wh1_words = wh1_norm.split()
    wh2_words = wh2_norm.split()

    total_count = len(corrected)
    if total_count == 0:
        return {
            'audio_issue': True,
            'audio_issue_reason': 'empty_after_cleanup',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    correct_count = sum(1 for w in corrected if not w.get('missing') and not w.get('extra'))
    missing_count = sum(1 for w in corrected if w.get('missing'))
    extra_count   = sum(1 for w in corrected if w.get('extra'))

    missing_ratio = missing_count / total_count
    extra_ratio   = extra_count / total_count
    correct_ratio = correct_count / total_count

    ayahcount = int(surah_info.get('ayahcount', 0) or 0)
    surah_type = classify_surah_type(ayahcount)

    # 1) إذا النص الثاني أطول ظاهريًا لكن أغلب النتيجة أخطاء/زيادات
    if len(wh2_words) >= 8 and (missing_ratio + extra_ratio) >= 0.65 and correct_ratio <= 0.40:
        return {
            'audio_issue': True,
            'audio_issue_reason': 'mid_echo_alignment_collapse',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    # 2) لو الزيادات كثيرة بشكل غير منطقي
    if total_count >= 10 and extra_ratio >= 0.45 and correct_ratio <= 0.50:
        return {
            'audio_issue': True,
            'audio_issue_reason': 'too_many_extras_from_echo',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    # 3) للسور القصيرة: نكون أخف حتى ما نظلم التلاوات الناقصة فعلاً
    if surah_type == 'short':
        if total_count >= 6 and extra_ratio >= 0.55 and correct_ratio <= 0.35:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'short_surah_echo_collapse',
                'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
            }

    # 4) للسور المتوسطة والطويلة: missing + extra معًا علامة سيئة
    else:
        if total_count >= 12 and missing_ratio >= 0.35 and extra_ratio >= 0.25 and correct_ratio <= 0.45:
            return {
                'audio_issue': True,
                'audio_issue_reason': 'mixed_missing_extra_due_to_echo',
                'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
            }

    return {
        'audio_issue': False,
        'audio_issue_reason': '',
        'audio_issue_message': '',
    }


# ─────────────────────────────────────────────
# الخطوة 1 — تحضير الصوت
# ─────────────────────────────────────────────
def prepare_audio(source: str) -> str:
    import sys
    import shutil

    if re.match(r'^https?://', source.strip()):
        ytdlp = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
        if not ytdlp:
            scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
            for name in ["yt-dlp.exe", "yt-dlp"]:
                candidate = os.path.join(scripts_dir, name)
                if os.path.exists(candidate):
                    ytdlp = candidate
                    break
        if not ytdlp:
            ytdlp = "yt-dlp"

        out_dir = tempfile.mkdtemp()

        res = subprocess.run([
            ytdlp,
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '0',
            '-o', os.path.join(out_dir, 'audio.%(ext)s'),
            source
        ], capture_output=True, text=True)

        if res.returncode != 0:
            raise RuntimeError(f"فشل تحميل الرابط: {res.stderr[-300:]}")

        raw = next(
            (str(f) for f in Path(out_dir).iterdir()
             if f.suffix.lower() in {
                 '.mp3', '.wav', '.ogg', '.m4a', '.webm',
                 '.mp4', '.mkv', '.mov', '.aac'
             }),
            None
        )

        if not raw:
            raise RuntimeError("لم يُوجد ملف صوت بعد التحميل")
    else:
        if not os.path.exists(source):
            raise FileNotFoundError(f"الملف غير موجود: {source}")
        raw = source

    wav = tempfile.mktemp(suffix='_taqan.wav')

    res = subprocess.run([
        'ffmpeg', '-y',
        '-i', raw,
        '-vn',
        '-ar', '16000',
        '-ac', '1',
        '-af', 'highpass=f=80,lowpass=f=8000,afftdn=nf=-25,dynaudnorm=p=0.9',
        wav
    ], capture_output=True, text=True)

    if res.returncode != 0:
        raise RuntimeError(f"فشل ffmpeg: {res.stderr[-300:]}")

    return wav


# ─────────────────────────────────────────────
# الخطوة 2 — whisper
# ─────────────────────────────────────────────
def run_whisper(wav: str, prompt: str = None) -> dict:
    import os
    import requests

    colab_url = os.getenv("COLAB_ASR_URL")

    if not colab_url:
        raise RuntimeError("COLAB_ASR_URL غير موجود في Render Environment Variables")

    with open(wav, "rb") as f:
        response = requests.post(
            colab_url,
            files={"file": f},
            timeout=300
        )

    response.raise_for_status()
    data = response.json()

    text = normalize(data.get("text", ""))

    words = []
    current_time = 0.0

    for word in text.split():
        words.append({
            "word": word,
            "start": current_time,
            "end": current_time + 0.5,
            "confidence": 1.0,
            "source": "colab_whisper",
        })
        current_time += 0.5

    print(f"\n🎙️ DEBUG Colab whisper: {text[:220]}")

    return {
        "text": text,
        "words": words
    }


# ─────────────────────────────────────────────
# الخطوة 3 — wav2vec2
# ─────────────────────────────────────────────
def run_wav2vec2(wav: str) -> str:
    import torch
    import librosa
    from transformers import AutoProcessor, AutoModelForCTC

    prc = AutoProcessor.from_pretrained(MODEL_PATH)
    mdl = AutoModelForCTC.from_pretrained(MODEL_PATH)
    mdl.eval()

    audio, _ = librosa.load(wav, sr=16000)
    chunks   = [audio[i:i + 16000 * 30] for i in range(0, len(audio), 16000 * 30)]
    parts    = []

    for ch in chunks:
        inp = prc(ch, sampling_rate=16000, return_tensors='pt', padding=True)
        with torch.no_grad():
            logits = mdl(**inp).logits
        ids = torch.argmax(logits, dim=-1)
        parts.append(normalize(prc.batch_decode(ids)[0]))

    return ' '.join(parts).strip()


# ─────────────────────────────────────────────
# الخطوة 4 — كشف السورة
# ─────────────────────────────────────────────
def detect_surah(text: str, db_surahs: dict) -> dict:
    words_list  = [w for w in normalize(text).split() if len(w) > 2]
    first_words = set(words_list[:10])
    all_words   = set(words_list)
    total       = len(db_surahs)

    word_df = {}
    surah_words = {}

    for num, data in db_surahs.items():
        ws = set(w for v in data['verses'] for w in normalize(v).split() if len(w) > 2)
        surah_words[num] = ws
        for w in ws:
            word_df[w] = word_df.get(w, 0) + 1

    def tfidf_score(recited, surah_ws):
        if not surah_ws:
            return 0.0
        sc = sum(
            (math.log(total / word_df.get(w, 1)) + 1) * (len(w) / 4)
            for w in surah_ws if w in recited
        )
        return sc / math.sqrt(len(surah_ws))

    scores_full  = {num: tfidf_score(all_words, ws) for num, ws in surah_words.items()}
    scores_first = {num: tfidf_score(first_words, ws) for num, ws in surah_words.items()}
    scores       = {num: 0.6 * scores_full[num] + 0.4 * scores_first[num] for num in surah_words}

    best = max(scores, key=lambda k: scores[k])
    top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]

    print(f"\n🔍 DEBUG detect_surah:")
    print(f"   النص: {text[:100]}")
    for num, sc in top3:
        print(f"   {db_surahs[num]['name']}: {sc:.2f}")

    return {
        'number'   : best,
        'name'     : db_surahs[best]['name'],
        'score'    : round(scores[best], 3),
        'ayahcount': db_surahs[best]['ayahcount'],
    }


def build_surah_prompt(db_surahs: dict, surah_number: int, max_ayahs: int = 8) -> str:
    surah = db_surahs.get(surah_number, {})
    verses = surah.get('verses', [])[:max_ayahs]
    text = ' '.join(normalize(v) for v in verses if v)
    return text.strip() or get_whisper_prompt()

def classify_surah_type(ayah_count: int) -> str:
    if ayah_count <= 11:
        return 'short'
    elif ayah_count <= 25:
        return 'medium'
    return 'long'

def align_short(whisper_words: list, surah_verses: list) -> list:
    from rapidfuzz import fuzz

    ref_verses_norm = [normalize(v) for v in surah_verses]
    ref_words = []
    ayah_map = []

    for ayah_idx, verse in enumerate(ref_verses_norm, start=1):
        for w in verse.split():
            ref_words.append(w)
            ayah_map.append(ayah_idx)

    # حذف البسملة والاستعاذة من المدخل
    BASMALA = normalize('بسم الله الرحمن الرحيم')
    ISTIATHA_WORDS = {'اعوذ', 'اعود', 'عوذ', 'بالله', 'من', 'الشيطان', 'الشطان', 'الرجيم', 'الرجم'}

    words = whisper_words[:]

    bsm_idx = next((i for i, w in enumerate(words) if 'بسم' in w['word']), -1)
    if bsm_idx >= 0:
        bsm_len = len(BASMALA.split())
        words = words[bsm_idx + bsm_len:]
    else:
        skip_end = 0
        for i, w in enumerate(words[:10]):
            if w['word'] in ISTIATHA_WORDS:
                skip_end = i + 1
            else:
                break
        if skip_end > 0:
            words = words[skip_end:]

    words = [w for w in words if w['word'] not in NON_QURAN]

    corrected = []
    i = 0  # ref index
    j = 0  # rec index

    def append_missing(ref_word, ayah_num, ts):
        corrected.append({
            'word': ref_word,
            'start': ts,
            'end': ts,
            'confidence': 0.0,
            'source': 'missing',
            'corrected': False,
            'missing': True,
            'ayah': ayah_num,
        })

    while i < len(ref_words) and j < len(words):
        ref_w = ref_words[i]
        rec_w = words[j]['word']
        ayah_num = ayah_map[i]

        sim = fuzz.ratio(ref_w, rec_w)

        # تطابق طبيعي أو قريب جدًا
        if sim >= 88:
            corrected.append({
                **words[j],
                'corrected': False,
                'missing': False,
                'ayah': ayah_num,
            })
            i += 1
            j += 1
            continue

        # لو الكلمة الحالية تكرار محلي بريء
        prev_word = corrected[-1]['word'] if corrected else ''
        next_ref = ref_words[i + 1] if i + 1 < len(ref_words) else ''
        if _is_local_repeat(rec_w, prev_word=prev_word, next_word=next_ref):
            j += 1
            continue

        # لو الكلمة التالية في التسجيل تطابق المرجع الحالي -> الحالية زائدة
        if j + 1 < len(words) and fuzz.ratio(ref_w, words[j + 1]['word']) >= 88:
            corrected.append({
                'word': words[j]['word'],
                'start': words[j]['start'],
                'end': words[j]['end'],
                'confidence': words[j].get('confidence', 0),
                'source': 'extra',
                'corrected': False,
                'missing': False,
                'extra': True,
                'ayah': ayah_num,
            })
            j += 1
            continue

        # لو الكلمة التالية في المرجع تطابق الحالية -> المرجعية الحالية ناقصة
        if i + 1 < len(ref_words) and fuzz.ratio(ref_words[i + 1], rec_w) >= 88:
            ts = corrected[-1]['end'] if corrected else words[j]['start']
            append_missing(ref_w, ayah_num, ts)
            i += 1
            continue

        # غير ذلك: نعتبر المرجعية ناقصة أولاً
        ts = corrected[-1]['end'] if corrected else words[j]['start']
        append_missing(ref_w, ayah_num, ts)
        i += 1

    # باقي المرجع = ناقص
    while i < len(ref_words):
        ref_w = ref_words[i]
        ayah_num = ayah_map[i]
        ts = corrected[-1]['end'] if corrected else 0.0
        append_missing(ref_w, ayah_num, ts)
        i += 1

    # باقي التسجيل = زائد
    last_ayah = ayah_map[-1] if ayah_map else 1
    while j < len(words):
        rec_w = words[j]['word']
        prev_word = corrected[-1]['word'] if corrected else ''
        if not _is_local_repeat(rec_w, prev_word=prev_word):
            corrected.append({
                'word': rec_w,
                'start': words[j]['start'],
                'end': words[j]['end'],
                'confidence': words[j].get('confidence', 0),
                'source': 'extra',
                'corrected': False,
                'missing': False,
                'extra': True,
                'ayah': last_ayah,
            })
        j += 1

    return corrected

# ─────────────────────────────────────────────
# الخطوة 5 — المحاذاة
# ─────────────────────────────────────────────
NON_QURAN = {
    'اشتركوا', 'اشترك', 'القناه', 'القناة', 'سبسكرايب',
    'لايك', 'الجرس', 'التنبيهات', 'موسيقى', 'موسيقي',
    'الرابط', 'الوصف', 'تابعوا', 'شاهد', 'فيديو',
}

def is_probable_echo_repeat(word: str, previous_words: list, current_time: float = 0.0, current_ayah: int = 0) -> bool:
    """
    هل الكلمة الحالية مجرد تكرار/صدى لكلمة ظهرت قبلها؟
    previous_words: قائمة آخر الكلمات المصححة قبل الحالية
    """
    current_word = normalize(word)
    if not current_word:
        return False

    for prev in reversed(previous_words[-8:]):
        prev_word = normalize(prev.get('word', ''))
        if not prev_word:
            continue

        prev_time = float(prev.get('start', 0) or 0)
        prev_ayah = prev.get('ayah', 0)

        same_or_close = fuzzy_ratio(current_word, prev_word) >= 90
        close_time = abs(current_time - prev_time) <= 2.5
        close_ayah = abs((current_ayah or 0) - (prev_ayah or 0)) <= 1

        if same_or_close and close_time and close_ayah:
            return True

    return False

def align_and_correct(whisper_words: list, w2v_text: str, surah_verses: list) -> list:
    from rapidfuzz import fuzz

    w2v_words = normalize(w2v_text).split() if w2v_text else []
    ref_verses_norm = [normalize(v) for v in surah_verses]

    surah_vocab = set()
    for verse in ref_verses_norm:
        for ww in verse.split():
            surah_vocab.add(ww)

    def verse_sim(verse_norm: str, text_chunk: str) -> float:
        v_words = verse_norm.split()
        t_words = text_chunk.split()
        if not v_words:
            return 0.0

        matched = count_fuzzy_matches(v_words, t_words, threshold=72)
        return matched / max(len(v_words), 1)

    # بناء الكلمات المميزة لكل آية
    all_verse_words = [set(v.split()) for v in ref_verses_norm]
    verse_unique_words = []

    for vi, vws in enumerate(all_verse_words):
        other = set()
        for oi, ows in enumerate(all_verse_words):
            if oi != vi:
                other.update(ows)

        unique = vws - other
        if not unique:
            unique = {w for w in vws if len(w) > 3}
        if not unique:
            unique = vws

        verse_unique_words.append(unique)

    # تجاهل الاستعاذة والبسملة
    BASMALA_NORM   = normalize('بسم الله الرحمن الرحيم')
    BASMALA_WORDS  = BASMALA_NORM.split()
    ISTIATHA_WORDS = {
        'اعوذ', 'اعود', 'عوذ', 'بالله',
        'من', 'الشيطان', 'الشطان', 'الرجيم', 'الرجم',
    }

    bsm_idx = next((i for i, w in enumerate(whisper_words) if 'بسم' in w['word']), -1)
    if bsm_idx >= 0:
        whisper_words = whisper_words[bsm_idx + len(BASMALA_WORDS):]
    else:
        skip_end = 0
        for i, w in enumerate(whisper_words[:10]):
            if w['word'] in ISTIATHA_WORDS:
                skip_end = i + 1
            else:
                break
        if skip_end > 0:
            whisper_words = whisper_words[skip_end:]

    # حذف البسملة من المرجع لو موجودة
    if ref_verses_norm:
        if normalize(ref_verses_norm[0]) == BASMALA_NORM:
            ref_verses_norm    = ref_verses_norm[1:]
            surah_verses       = surah_verses[1:]
            all_verse_words    = all_verse_words[1:]
            verse_unique_words = verse_unique_words[1:]
        elif ref_verses_norm[0].startswith(BASMALA_NORM):
            stripped = ref_verses_norm[0][len(BASMALA_NORM):].strip()
            ref_verses_norm[0] = stripped
            surah_verses[0]    = surah_verses[0].replace('بسم الله الرحمن الرحيم', '', 1).strip()
            all_verse_words[0] = set(stripped.split())

            other = set()
            for oi, ows in enumerate(all_verse_words):
                if oi != 0:
                    other.update(ows)

            unique = all_verse_words[0] - other
            if not unique:
                unique = {w for w in all_verse_words[0] if len(w) > 3}
            if not unique:
                unique = all_verse_words[0]

            verse_unique_words[0] = unique

    whisper_words_clean = [w for w in whisper_words if w['word'] not in NON_QURAN]

    print(f"\n📝 whisper_words بعد الحذف: {[w['word'] for w in whisper_words_clean[:20]]}")

    # المستوى 1 — محاذاة الآيات
    verse_alignment = []
    whisper_pos = 0
    used_positions = set()

    for vi, ref_v in enumerate(ref_verses_norm):
        ref_v_words = ref_v.split()
        v_len       = len(ref_v_words)
        unique_ws   = verse_unique_words[vi]

        if whisper_pos >= len(whisper_words_clean):
            verse_alignment.append((vi, False, (-1, -1), whisper_pos, whisper_pos))
            continue

        best_score, best_start = 0.0, whisper_pos
        search_end = len(whisper_words_clean)

        for start in range(whisper_pos, search_end):
            if start in used_positions:
                continue

            end   = min(start + v_len + 4, len(whisper_words_clean))
            chunk = ' '.join(w['word'] for w in whisper_words_clean[start:end])
            sc    = verse_sim(ref_v, chunk)

            if sc > best_score:
                best_score, best_start = sc, start
                if sc >= 0.99:
                    break

        if v_len <= 3:
            window_tokens = [
                w['word'] for w in whisper_words_clean[
                    whisper_pos: min(whisper_pos + v_len + 5, len(whisper_words_clean))
                ]
            ]
            unique_found = sum(
                1 for uw in unique_ws
                if token_exists_fuzzy(uw, window_tokens, threshold=68)
            )
            found = unique_found >= 1
            print(f"  آية {vi+1} ({ref_v}): window={window_tokens!r} unique={unique_ws} found={found}")
        else:
            ref_tokens = ref_v.split()
            search_tokens = [
                w['word'] for w in whisper_words_clean[
                    best_start: min(best_start + v_len + 5, len(whisper_words_clean))
                ]
            ]
            fuzzy_cov = count_fuzzy_matches(ref_tokens, search_tokens, threshold=70) / max(len(ref_tokens), 1)
            found = max(best_score, fuzzy_cov) >= 0.55
            print(f"  آية {vi+1} ({ref_v}): score={best_score:.2f} fuzzy_cov={fuzzy_cov:.2f} found={found}")

        if found:
            end_pos = min(best_start + v_len, len(whisper_words_clean))
            gap_start = whisper_pos
            gap_end   = best_start

            for p in range(best_start, end_pos):
                used_positions.add(p)

            verse_alignment.append((vi, True, (best_start, end_pos), gap_start, gap_end))
            whisper_pos = end_pos
        else:
            verse_alignment.append((vi, False, (-1, -1), whisper_pos, whisper_pos))

    # المستوى 2 — محاذاة الكلمات
    def nw_words(ref_ws, rec_ws):
        GAP = -1

        def s(a, b):
            r = fuzz.ratio(a, b) / 100
            return 2 if r >= 0.95 else (1 if r >= 0.70 else -1)

        n, m = len(ref_ws), len(rec_ws)
        dp = [[0] * (m + 1) for _ in range(n + 1)]

        for i in range(n + 1):
            dp[i][0] = i * GAP
        for j in range(m + 1):
            dp[0][j] = j * GAP

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                dp[i][j] = max(
                    dp[i - 1][j - 1] + s(ref_ws[i - 1], rec_ws[j - 1]),
                    dp[i - 1][j] + GAP,
                    dp[i][j - 1] + GAP,
                )

        aln = []
        i, j = n, m
        while i > 0 or j > 0:
            if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + s(ref_ws[i - 1], rec_ws[j - 1]):
                aln.append(('match', i - 1, j - 1))
                i -= 1
                j -= 1
            elif i > 0 and dp[i][j] == dp[i - 1][j] + GAP:
                aln.append(('ref_gap', i - 1, -1))
                i -= 1
            else:
                aln.append(('rec_gap', -1, j - 1))
                j -= 1

        aln.reverse()
        return aln

    corrected = []

    for vi, found, (ws, we), gap_start, gap_end in verse_alignment:
        ref_v_words = ref_verses_norm[vi].split()

        # الكلمات الموجودة قبل بداية هذه الآية
        if found and gap_end > gap_start:
            gap_words = whisper_words_clean[gap_start:gap_end]
            next_expected = ref_v_words[0] if ref_v_words else ''

            for gw in gap_words:
                word = gw['word']
                conf = gw.get('confidence', 0)
                if conf <= 0.4:
                    continue

                prev_word = corrected[-1]['word'] if corrected else ''

                near_ref_words = []
                if vi > 0:
                    near_ref_words += ref_verses_norm[vi - 1].split()
                near_ref_words += ref_v_words
                if vi + 1 < len(ref_verses_norm):
                    near_ref_words += ref_verses_norm[vi + 1].split()

                if _is_local_repeat(word, prev_word=prev_word, next_word=next_expected):
                    continue

                # إذا الكلمة من نفس مفردات السورة أصلًا
                # فاعتبريها انزياح محاذاة وليس زيادة
                if _matches_any_word(word, list(surah_vocab), threshold=78):
                    continue

                # وإذا كانت قريبة من سياق الآيات المجاورة أيضًا
                if _matches_any_word(word, near_ref_words, threshold=78):
                    continue

                corrected.append({
                    'word'      : word,
                    'start'     : gw['start'],
                    'end'       : gw['end'],
                    'confidence': conf,
                    'source'    : 'extra',
                    'corrected' : False,
                    'missing'   : False,
                    'extra'     : True,
                    'ayah'      : vi + 1,
                })

        if not found:
            ref_v_words_set = set(ref_verses_norm[vi].split())
            other_words     = set()

            for oi, ov in enumerate(ref_verses_norm):
                if oi != vi:
                    other_words.update(ov.split())

            unique_words = ref_v_words_set - other_words
            if not unique_words:
                unique_words = {w for w in ref_v_words_set if len(w) > 3}

            w2v_text_joined = ' '.join(w2v_words)
            unique_found    = sum(
                1 for w in unique_words
                if token_exists_fuzzy(w, w2v_text_joined.split(), threshold=70)
            )
            unique_ratio = unique_found / len(unique_words) if unique_words else 0
            ts = corrected[-1]['end'] if corrected else 0.0

            local_tokens = [
                w['word'] for w in whisper_words_clean[
                    whisper_pos: min(whisper_pos + len(ref_v_words) + 5, len(whisper_words_clean))
                ]
            ]
            local_cov = count_fuzzy_matches(ref_v_words, local_tokens, threshold=68) / max(len(ref_v_words), 1)

            if unique_ratio >= 0.6 or local_cov >= 0.5:
                for rw in ref_v_words:
                    corrected.append({
                        'word'      : rw,
                        'start'     : ts,
                        'end'       : ts,
                        'confidence': round(max(unique_ratio, local_cov), 3),
                        'source'    : 'recovered',
                        'corrected' : True,
                        'original'  : '',
                        'ayah'      : vi + 1,
                        'missing'   : False,
                    })
            else:
                for rw in ref_v_words:
                    corrected.append({
                        'word'      : rw,
                        'start'     : ts,
                        'end'       : ts,
                        'confidence': 0.0,
                        'source'    : 'missing',
                        'corrected' : False,
                        'missing'   : True,
                        'ayah'      : vi + 1,
                    })
            continue

        rec_slice       = whisper_words_clean[ws:we]
        rec_ws          = [w['word'] for w in rec_slice]
        w2v_start       = max(0, ws - 1)
        w2v_chunk       = w2v_words[w2v_start: w2v_start + len(ref_v_words) + 4]
        rec_chunk_text  = ' '.join(rec_ws)
        set_sim_score   = verse_sim(ref_verses_norm[vi], rec_chunk_text)
        order_sim_score = fuzz.ratio(ref_verses_norm[vi], rec_chunk_text) / 100
        verse_quality   = (set_sim_score + order_sim_score) / 2

        # إذا الآية القصيرة متضررة لكن قريبة من المرجع
        if verse_quality < 0.50 and len(ref_v_words) <= 6:
            ts_start = rec_slice[0]['start'] if rec_slice else (corrected[-1]['end'] if corrected else 0.0)
            ts_end   = rec_slice[-1]['end'] if rec_slice else ts_start
            step     = (ts_end - ts_start) / max(len(ref_v_words), 1)

            for k, rw in enumerate(ref_v_words):
                corrected.append({
                    'word'      : rw,
                    'start'     : round(ts_start + k * step, 2),
                    'end'       : round(ts_start + (k + 1) * step, 2),
                    'confidence': round(verse_quality, 3),
                    'source'    : 'db_verse',
                    'original'  : rec_ws[k] if k < len(rec_ws) else '',
                    'corrected' : True,
                    'missing'   : False,
                    'ayah'      : vi + 1,
                })
            continue

        aln = nw_words(ref_v_words, rec_ws)

        for aln_idx, (op, ri, ci) in enumerate(aln):
            ref_w = ref_v_words[ri] if ri >= 0 else ''
            rec_w = rec_slice[ci] if ci >= 0 else None
            ts_s  = rec_w['start'] if rec_w else (corrected[-1]['end'] if corrected else 0.0)
            ts_e  = rec_w['end'] if rec_w else ts_s

            if op == 'match':
                whisper_w   = rec_w['word']
                conf        = rec_w['confidence']
                exact_match = _same_word(whisper_w, ref_w)
                len_diff    = abs(len(whisper_w) - len(ref_w))
                ms          = fuzz.ratio(whisper_w, ref_w)
                w2v_ms      = fuzz.ratio(w2v_chunk[ci], ref_w) if (w2v_chunk and ci < len(w2v_chunk)) else 0

                echo_repeat = is_probable_echo_repeat(
                    whisper_w,
                    corrected,
                    current_time=ts_s,
                    current_ayah=vi + 1
                )

                use_db = not exact_match and not echo_repeat and (
                    (w2v_ms > ms and w2v_ms >= 60) or
                    (conf < 0.75) or
                    (len_diff >= 1 and ms < 98) or
                    (len_diff == 0 and ms < 90) or
                    (len(whisper_w) >= max(1, len(ref_w)) * 1.5 and ms < 85)
                )

                if echo_repeat:
                    # نعتبرها تكرار صدى ونهملها بدل ما تتحول لتحريف
                    continue

                if exact_match or not use_db:
                    corrected.append({
                        **rec_w,
                        'corrected': False,
                        'missing'  : False,
                        'ayah'     : vi + 1,
                    })
                else:
                    asr_noise = (
                        ms >= 60 or
                        w2v_ms >= 70 or
                        (len_diff <= 2 and ms >= 55)
                    )

                    corrected.append({
                        'word'      : ref_w,
                        'start'     : ts_s,
                        'end'       : ts_e,
                        'confidence': max(round(w2v_ms / 100, 3), conf),
                        'source'    : 'db_corrected',
                        'original'  : whisper_w,
                        'corrected' : True,
                        'missing'   : False,
                        'ayah'      : vi + 1,
                        'asr_noise' : asr_noise,
                    })

            elif op == 'ref_gap':
                ts       = corrected[-1]['end'] if corrected else 0.0
                w2v_wide = w2v_words[max(0, w2v_start - 3): w2v_start + len(ref_v_words) + 7]
                w2v_sc   = max((fuzz.ratio(ref_w, w) for w in w2v_wide), default=0)

                if w2v_sc >= 55:
                    corrected.append({
                        'word'      : ref_w,
                        'start'     : ts,
                        'end'       : ts,
                        'confidence': round(w2v_sc / 100, 3),
                        'source'    : 'recovered',
                        'corrected' : True,
                        'original'  : '',
                        'missing'   : False,
                        'ayah'      : vi + 1,
                    })
                else:
                    corrected.append({
                        'word'      : ref_w,
                        'start'     : ts,
                        'end'       : ts,
                        'confidence': 0.0,
                        'source'    : 'missing',
                        'corrected' : False,
                        'missing'   : True,
                        'ayah'      : vi + 1,
                    })

            elif op == 'rec_gap':
                if rec_w and rec_w.get('confidence', 0) > 0.7:
                    word = rec_w['word']
                    prev_word = corrected[-1]['word'] if corrected else ''

                    next_word = ''
                    for future_idx in range(aln_idx + 1, len(aln)):
                        op2, ri2, ci2 = aln[future_idx]
                        if ri2 >= 0:
                            next_word = ref_v_words[ri2]
                            break

                    if _is_local_repeat(word, prev_word=prev_word, next_word=next_word):
                        continue

                    if is_probable_echo_repeat(
                        word,
                        corrected,
                        current_time=rec_w['start'],
                        current_ayah=vi + 1
                    ):
                        continue

                    near_ref_words = ref_v_words[:]
                    if vi > 0:
                        near_ref_words += ref_verses_norm[vi - 1].split()
                    if vi + 1 < len(ref_verses_norm):
                        near_ref_words += ref_verses_norm[vi + 1].split()

                    if _matches_any_word(word, list(surah_vocab), threshold=78):
                        continue

                    if _matches_any_word(word, near_ref_words, threshold=78):
                        continue

                    corrected.append({
                        'word'      : word,
                        'start'     : rec_w['start'],
                        'end'       : rec_w['end'],
                        'confidence': rec_w['confidence'],
                        'source'    : 'extra',
                        'corrected' : False,
                        'missing'   : False,
                        'extra'     : True,
                        'ayah'      : vi + 1,
                    })

    # الكلمات الزائدة في النهاية
    last_ayah = len(surah_verses)
    if whisper_pos < len(whisper_words_clean):
        for w in whisper_words_clean[whisper_pos:]:
            word = w['word']
            prev_word = corrected[-1]['word'] if corrected else ''

            if _is_local_repeat(word, prev_word=prev_word):
                continue

            if w.get('confidence', 0) > 0.5:
                corrected.append({
                    'word'      : word,
                    'start'     : w['start'],
                    'end'       : w['end'],
                    'confidence': w['confidence'],
                    'source'    : 'extra',
                    'corrected' : False,
                    'missing'   : False,
                    'extra'     : True,
                    'ayah'      : last_ayah,
                })

    return corrected

def _progress(progress_callback, percent: int, step: str, label: str):
    if progress_callback:
        try:
            progress_callback(percent, step, label)
        except Exception:
            pass
def detect_early_audio_failure(text: str) -> dict:
    norm = normalize(text)
    words = norm.split()
    basmala = normalize('بسم الله الرحمن الرحيم')

    if not norm:
        return {
            'stop_early': True,
            'audio_issue': True,
            'audio_issue_reason': 'empty_transcript',
            'audio_issue_message': 'تعذر استخراج نص من التسجيل. قد يكون الصوت غير واضح أو منخفضًا جدًا أو يحتوي على صدى/تشويش.',
        }

    if len(words) <= 4 and basmala in norm:
        return {
            'stop_early': True,
            'audio_issue': True,
            'audio_issue_reason': 'basmala_only',
            'audio_issue_message': 'تعذر تحليل التلاوة لأن التسجيل المستخرج يحتوي فقط على البسملة أو نص قصير جدًا. يرجى رفع تسجيل أوضح.',
        }

    if len(words) <= 6:
        return {
            'stop_early': True,
            'audio_issue': True,
            'audio_issue_reason': 'very_short_transcript',
            'audio_issue_message': 'تعذر استخراج نص كافٍ من التسجيل. قد يحتوي التسجيل على صدى أو تشويش أو أن الصوت منخفض/بعيد.',
        }

    return {
        'stop_early': False,
        'audio_issue': False,
        'audio_issue_reason': '',
        'audio_issue_message': '',
    }

def detect_suspicious_short_surah_case(wh1_text: str, detected_surah: dict) -> dict:
    """
    كشف الحالات المشبوهة فقط في السور القصيرة جدًا، لكن بدون ظلم
    التلاوات الصحيحة أو التلاوات الناقصة فعلاً.
    """

    text = normalize(wh1_text)
    words = text.split()

    detected_name = normalize(detected_surah.get('name', ''))
    ayahcount = int(detected_surah.get('ayahcount', 0) or 0)

    short_surah_names = {
        normalize("الناس"),
        normalize("الفلق"),
        normalize("الإخلاص"),
        normalize("المسد"),
        normalize("النصر"),
        normalize("الكافرون"),
        normalize("الكوثر"),
        normalize("الماعون"),
        normalize("قريش"),
        normalize("الفيل"),
        normalize("العصر"),
    }

    # نطبق الفحص فقط إذا السورة قصيرة فعلًا
    if not (ayahcount <= 11 or detected_name in short_surah_names):
        return {
            'audio_issue': False,
            'audio_issue_reason': '',
            'audio_issue_message': '',
        }

    basmala_text = normalize("بسم الله الرحمن الرحيم")
    istiatha_words = {
        normalize("اعوذ"),
        normalize("بالله"),
        normalize("من"),
        normalize("الشيطان"),
        normalize("الرجيم"),
    }

    has_basmala = basmala_text in text
    basmala_count = text.count("بسم")
    istiatha_count = sum(1 for w in words if w in istiatha_words)

    # عدد الكلمات الحقيقية بعد حذف كلمات الاستعاذة والبسملة
    filler_words = set(basmala_text.split()) | istiatha_words
    content_words = [w for w in words if w not in filler_words]

    # 1) إذا النص كله تقريبًا استعاذة/بسملة وما فيه محتوى قرآني حقيقي
    if len(content_words) <= 2 and (has_basmala or istiatha_count >= 2):
        return {
            'audio_issue': True,
            'audio_issue_reason': 'suspicious_short_surah_intro_only',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    # 2) إذا النص قصير جدًا جدًا
    if len(words) <= 4:
        return {
            'audio_issue': True,
            'audio_issue_reason': 'suspicious_short_surah_too_short',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    # 3) إذا كان النص أغلبه فقط مقدمة بدون كلمات تلاوة كافية
    if len(words) <= 8 and len(content_words) <= 3 and (has_basmala or istiatha_count >= 2):
        return {
            'audio_issue': True,
            'audio_issue_reason': 'suspicious_short_surah_low_content',
            'audio_issue_message': 'نتيجة التحليل تشير إلى أن التسجيل غير واضح أو يحتوي على صدى أو تشويش شديد.',
        }

    return {
        'audio_issue': False,
        'audio_issue_reason': '',
        'audio_issue_message': '',
    }

# ─────────────────────────────────────────────
# العملية الكاملة
# ─────────────────────────────────────────────
def process_recitation(source: str, db_surahs: dict, progress_callback=None) -> dict:
    _progress(progress_callback, 20, "prepare_audio", "جاري تجهيز الصوت...")
    wav = prepare_audio(source)

    # المرحلة الأولى: تفريغ عام
    _progress(progress_callback, 35, "whisper_first", "جاري تحويل التلاوة إلى نص...")
    wh1 = run_whisper(wav, prompt=get_whisper_prompt())
    early_audio_check = detect_early_audio_failure(wh1['text'])
    if early_audio_check['stop_early']:
        try:
            os.remove(wav)
        except Exception:
            pass

        return {
            'stop_early': True,
            'surah': None,
            'words': [],
            'text': wh1['text'],
            'audio_issue': early_audio_check['audio_issue'],
            'audio_issue_reason': early_audio_check['audio_issue_reason'],
            'audio_issue_message': early_audio_check['audio_issue_message'],
        }
    try:
        _progress(progress_callback, 48, "wav2vec2", "جاري التحليل الإضافي للتلاوة...")
        w2v_text = run_wav2vec2(wav)
    except Exception:
        w2v_text = ''

    # كشف أولي
    _progress(progress_callback, 58, "detect_surah", "جاري تحديد السورة...")
    surah = detect_surah(wh1['text'], db_surahs)

    suspicious_case = detect_suspicious_short_surah_case(wh1['text'], surah)
    if suspicious_case['audio_issue']:
        try:
            os.remove(wav)
        except Exception:
            pass

        return {
            'stop_early': True,
            'surah': surah,
            'words': [],
            'text': wh1['text'],
            'audio_issue': True,
            'audio_issue_reason': suspicious_case['audio_issue_reason'],
            'audio_issue_message': suspicious_case['audio_issue_message'],
        }
    # المرحلة الثانية: تفريغ موجّه للسورة المكتشفة
    _progress(progress_callback, 68, "whisper_second", "جاري تحسين التحليل بناءً على السورة...")
    surah_prompt = build_surah_prompt(db_surahs, surah['number'])
    wh2 = run_whisper(wav, prompt=surah_prompt)

    # إعادة كشف السورة بعد تحسين التفريغ
    _progress(progress_callback, 76, "redetect_surah", "جاري تأكيد السورة المكتشفة...")
    surah = detect_surah(wh2['text'], db_surahs)

    _progress(progress_callback, 86, "align", "جاري مطابقة التلاوة مع المرجع...")
    surah_verses = db_surahs[surah['number']]['verses']

    corrected = align_and_correct(
        wh2['words'],
        w2v_text,
        surah_verses
    )

    try:
        os.remove(wav)
    except Exception:
        pass

    _progress(progress_callback, 91, "cleanup", "جاري تنقية النتائج...")
    corrected = cleanup_duplicate_extras(corrected)
    corrected = remove_echo_repetitions(corrected)
    corrected = fix_initial_extras_position(corrected)  # 👈 الجديد
    corrected = fix_shift_errors(corrected)
    corrected = fix_false_missing_at_ayah_start(corrected)
    surah_type = classify_surah_type(surah['ayahcount'])
    corrected = soften_false_missing_words(corrected, surah_type)

    _progress(progress_callback, 94, "audio_check", "جاري التحقق من جودة التسجيل...")
    audio_issue_info = detect_audio_issue(
        wh1_text=wh1['text'],
        wh2_text=wh2['text'],
        corrected=corrected,
        surah_info=surah,
    )

    if not audio_issue_info.get('audio_issue'):
        mid_echo_issue = detect_mid_echo_collapse(
            wh1_text=wh1['text'],
            wh2_text=wh2['text'],
            corrected=corrected,
            surah_info=surah,
        )
        if mid_echo_issue.get('audio_issue'):
            audio_issue_info = mid_echo_issue

    text = ' '.join(w['word'] for w in corrected if not w.get('missing'))

    return {
        'surah': surah,
        'words': corrected,
        'text': text,
        'audio_issue': audio_issue_info['audio_issue'],
        'audio_issue_reason': audio_issue_info['audio_issue_reason'],
        'audio_issue_message': audio_issue_info['audio_issue_message'],
        'stop_early': bool(audio_issue_info.get('audio_issue')),
    }

def cleanup_duplicate_extras(words: list) -> list:
    """
    تنظيف الزيادات الوهمية:
    - يحذف extra إذا ظهرت نفس الكلمة بعدها قريبًا بشكل صحيح
    - يحذف extra إذا كانت تكرارًا محليًا أو كلمة قصيرة متكررة في نفس السياق
    """
    cleaned = []

    for i, w in enumerate(words):
        if not w.get('extra'):
            cleaned.append(w)
            continue

        current_word = normalize(w.get('word', ''))
        current_ayah = w.get('ayah', 0)
        current_time = float(w.get('start', 0) or 0)

        prev_word = normalize(cleaned[-1]['word']) if cleaned else ''
        next_word = ''

        for j in range(i + 1, min(i + 6, len(words))):
            nxt_word = normalize(words[j].get('word', ''))
            if nxt_word:
                next_word = nxt_word
                break

        if _is_local_repeat(current_word, prev_word=prev_word, next_word=next_word):
            continue

        should_drop = False

        for j in range(i + 1, min(i + 6, len(words))):
            nxt = words[j]
            nxt_word = normalize(nxt.get('word', ''))
            nxt_ayah = nxt.get('ayah', 0)
            nxt_time = float(nxt.get('start', 0) or 0)

            if (
                current_word
                and nxt_word
                and fuzzy_ratio(current_word, nxt_word) >= 88
                and abs(nxt_ayah - current_ayah) <= 1
                and abs(nxt_time - current_time) <= 2.0
                and not nxt.get('extra')
                and not nxt.get('missing')
            ):
                should_drop = True
                break

        if should_drop:
            continue

        if len(current_word) <= 3:
            near_same = 0
            for j in range(max(0, i - 4), min(len(words), i + 5)):
                if j == i:
                    continue
                ww = normalize(words[j].get('word', ''))
                if fuzzy_ratio(current_word, ww) >= 90:
                    near_same += 1

            if near_same >= 1:
                continue

        cleaned.append(w)

    return cleaned

def remove_echo_repetitions(words: list) -> list:
    """
    حذف التكرارات الناتجة من الصدى:
    - إذا تكررت نفس الكلمة قريبًا زمنيًا بعد ظهورها الصحيح
    - إذا ظهرت extra لكنها مجرد إعادة لكلمة قريبة قبلها
    - إذا ظهر تكرار متأخر قليلًا بسبب echo
    """
    cleaned = []

    for i, w in enumerate(words):
        current_word = normalize(w.get('word', ''))
        current_start = float(w.get('start', 0) or 0)
        current_ayah = w.get('ayah', 0)

        if not current_word:
            continue

        should_drop = False

        # نرجع للخلف عدة كلمات ونشوف هل هي مجرد تكرار صدى
        for prev in reversed(cleaned[-8:]):
            prev_word = normalize(prev.get('word', ''))
            prev_start = float(prev.get('start', 0) or 0)
            prev_ayah = prev.get('ayah', 0)

            if not prev_word:
                continue

            same_or_close = fuzzy_ratio(current_word, prev_word) >= 90
            close_time = abs(current_start - prev_start) <= 2.2
            close_ayah = abs((current_ayah or 0) - (prev_ayah or 0)) <= 1

            if same_or_close and close_time and close_ayah:
                # إذا الحالية extra أو corrected أو حتى نفس الكلمة بسبب echo
                should_drop = True
                break

        # لو الكلمة تكرار مباشر جدًا للكلمة السابقة
        if not should_drop and cleaned:
            prev_word = normalize(cleaned[-1].get('word', ''))
            prev_start = float(cleaned[-1].get('start', 0) or 0)

            if fuzzy_ratio(current_word, prev_word) >= 92 and abs(current_start - prev_start) <= 1.5:
                should_drop = True

        if should_drop:
            continue

        cleaned.append(w)

    return cleaned

def fix_initial_extras_position(words: list) -> list:
    """
    تثبيت الكلمات الزائدة في بداية التلاوة:
    - أي كلمات extra قبل أول كلمة صحيحة
    - نعطيها ayah = 0 بدل ما تنرمي داخل السورة
    """

    fixed = []
    seen_real_word = False

    for w in words:
        status = None

        if w.get('missing'):
            status = 'missing'
        elif w.get('extra'):
            status = 'extra'
        else:
            status = 'normal'

        # إذا وصلنا أول كلمة حقيقية (مو extra ولا missing)
        if status == 'normal':
            seen_real_word = True

        # لو لسه ما بدأنا السورة
        if not seen_real_word:
            if w.get('extra'):
                w['ayah'] = 0  # 👈 أهم سطر
        fixed.append(w)

    return fixed

def fix_shift_errors(words: list) -> list:
    """
    إصلاح الانزياح البسيط:
    إذا ظهرت missing ثم ظهرت بعدها extra قريبة جدًا لفظيًا وزمنيًا
    نعتبرها shift وليس خطأين منفصلين.
    """
    fixed = []
    skip_indices = set()

    for i, w in enumerate(words):
        if i in skip_indices:
            continue

        if w.get('missing'):
            missing_word = normalize(w.get('word', ''))
            missing_ayah = w.get('ayah', 0)
            missing_time = float(w.get('start', 0) or 0)

            matched_extra_idx = None

            for j in range(i + 1, min(i + 6, len(words))):
                nxt = words[j]
                if nxt.get('extra'):
                    extra_word = normalize(nxt.get('word', ''))
                    extra_ayah = nxt.get('ayah', 0)
                    extra_time = float(nxt.get('start', 0) or 0)

                    if (
                        abs(extra_ayah - missing_ayah) <= 1
                        and abs(extra_time - missing_time) <= 2.5
                        and fuzzy_ratio(extra_word, missing_word) >= 72
                    ):
                        matched_extra_idx = j
                        break

            if matched_extra_idx is not None:
                fixed.append({
                    **w,
                    'missing': False,
                    'corrected': False,
                    'source': 'shift_fix'
                })
                skip_indices.add(matched_extra_idx)
                continue

        fixed.append(w)

    return fixed

def fix_false_missing_at_ayah_start(words: list) -> list:
    """
    إصلاح النقص الوهمي في أول الآية:
    إذا كانت أول كلمة في الآية معلّمة كناقص،
    وبعدها مباشرة كلمات صحيحة من نفس الآية،
    نعتبرها مشكلة محاذاة ونلغي هذا النقص.
    """
    fixed = []

    for i, w in enumerate(words):
        if not w.get('missing'):
            fixed.append(w)
            continue

        ayah = w.get('ayah')
        prev_ayah = words[i - 1].get('ayah') if i > 0 else None
        next_item = words[i + 1] if i + 1 < len(words) else None

        is_start_of_ayah = (prev_ayah != ayah)

        if is_start_of_ayah and next_item and next_item.get('ayah') == ayah:
            if not next_item.get('missing') and not next_item.get('extra'):
                # هذا غالبًا نقص وهمي بسبب بداية الآية
                fixed.append({
                    **w,
                    'missing': False,
                    'corrected': True,
                    'source': 'ayah_start_fix'
                })
                continue

        fixed.append(w)

    return fixed
# ─────────────────────────────────────────────
# تحميل السور من قاعدة البيانات
# ─────────────────────────────────────────────
def load_surahs_from_db(db_session) -> dict:
    from app.models import QuranSurah, QuranAyah

    surahs = db_session.query(QuranSurah).order_by(QuranSurah.surahid).all()
    result = {}

    for s in surahs:
        verses = (
            db_session.query(QuranAyah.ayahtext, QuranAyah.ayahid)
            .filter(QuranAyah.surahid == s.surahid)
            .order_by(QuranAyah.ayahnumber)
            .all()
        )

        if verses:
            result[s.surahid] = {
                'name'      : s.surahname,
                'ayahcount' : s.ayahcount,
                'verses'    : [v.ayahtext for v in verses],
                'ayah_ids'  : [v.ayahid for v in verses],
            }

    return result
def soften_false_missing_words(words: list, surah_type: str = 'medium') -> list:
    """
    تخفيف النقص الوهمي بحسب نوع السورة:
    - short  : شبه بدون تسامح (مهم للسور القصيرة)
    - medium : تسامح بسيط
    - long   : تسامح أكبر
    """
    softened = []

    for w in words:
        if w.get('missing'):
            word = normalize(w.get('word', ''))

            # ───────────────
            # السور القصيرة ❗
            # ───────────────
            if surah_type == 'short':
                # لا تتسامح مع الكلمات القصيرة أبداً
                softened.append(w)
                continue

            # ───────────────
            # السور المتوسطة
            # ───────────────
            elif surah_type == 'medium':
                # فقط كلمات قصيرة جدًا جدًا
                if len(word) <= 2:
                    softened.append({
                        **w,
                        'missing': False,
                        'corrected': True,
                        'source': 'soft_missing_fix'
                    })
                    continue

                # كلمات طويلة تنتهي بـ ا (أقل تسامح)
                if word.endswith(("ا", "اً")) and len(word) >= 5:
                    softened.append({
                        **w,
                        'missing': False,
                        'corrected': True,
                        'source': 'soft_missing_fix'
                    })
                    continue

            # ───────────────
            # السور الطويلة
            # ───────────────
            elif surah_type == 'long':
                if len(word) <= 3:
                    softened.append({
                        **w,
                        'missing': False,
                        'corrected': True,
                        'source': 'soft_missing_fix'
                    })
                    continue

                if word.endswith(("ا", "اً")):
                    softened.append({
                        **w,
                        'missing': False,
                        'corrected': True,
                        'source': 'soft_missing_fix'
                    })
                    continue

        softened.append(w)

    return softened