#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_to_package.py
تعطيه فيديو -> يستخرج الصوت -> يحول الكلام لنص -> يكتب برومبت كامل -> يحط كلشي بملف ZIP واحد

الاستخدام:
    python video_to_package.py myvideo.mp4
    python video_to_package.py myvideo.mp4 --lang ar --model medium
    python video_to_package.py myvideo.mp4 --frames 6 --out results

المتطلبات:
    1) ffmpeg  (https://ffmpeg.org)  لازم يكون منصّب وموجود بالـ PATH
    2) pip install faster-whisper      (مفضّل - أسرع)
       أو  pip install openai-whisper
    3) اختياري: متغير البيئة ANTHROPIC_API_KEY حتى Claude يكتب برومبت ذكي ومفصّل
       (بدونه البرنامج يسوي برومبت جاهز من قالب)
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


# ---------------------------------------------------------------- أدوات مساعدة
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"فشل الأمر: {' '.join(cmd)}\n{r.stderr[-800:]}")
    return r.stdout


def fmt_time(sec, srt=False):
    sec = max(0.0, float(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if srt:
        ms = int(round((s - int(s)) * 1000))
        if ms == 1000:
            ms = 999
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"


def check_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"❌ {tool} مو منصّب. نزّله من https://ffmpeg.org وضيفه للـ PATH")


# ---------------------------------------------------------------- 1) معلومات الفيديو
def video_info(video):
    data = json.loads(run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video)
    ]))
    info = {"file": video.name,
            "duration_sec": float(data["format"].get("duration", 0) or 0),
            "size_mb": round(int(data["format"].get("size", 0)) / 1_048_576, 2),
            "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and "width" not in info:
            info["width"], info["height"] = s.get("width"), s.get("height")
            info["video_codec"] = s.get("codec_name")
            num, _, den = (s.get("avg_frame_rate") or "0/1").partition("/")
            try:
                info["fps"] = round(float(num) / float(den or 1), 2)
            except ZeroDivisionError:
                info["fps"] = 0
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
            info["audio_codec"] = s.get("codec_name")
    info["duration"] = fmt_time(info["duration_sec"])
    return info


# ---------------------------------------------------------------- 2) استخراج الصوت
def extract_audio(video, out_dir):
    mp3 = out_dir / "audio.mp3"
    wav = out_dir / "_audio_16k.wav"   # نسخة مؤقتة للتفريغ
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "libmp3lame",
         "-q:a", "2", str(mp3)])
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         str(wav)])
    return mp3, wav


# ---------------------------------------------------------------- 3) لقطات من الفيديو
def extract_frames(video, out_dir, duration, count):
    if count <= 0 or duration <= 0:
        return []
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        p = frames_dir / f"frame_{i+1:02d}_{fmt_time(t).replace(':', '-')}.jpg"
        try:
            run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3", str(p)])
            paths.append(p)
        except RuntimeError:
            pass
    return paths


# ---------------------------------------------------------------- 4) تحويل الكلام لنص
def transcribe(wav, lang, model_name):
    language = None if lang == "auto" else lang
    try:
        from faster_whisper import WhisperModel
        print(f"   ↳ faster-whisper (موديل {model_name})")
        model = WhisperModel(model_name, device="auto", compute_type="auto")
        segs, info = model.transcribe(str(wav), language=language,
                                      vad_filter=True, beam_size=5)
        segments = [{"start": s.start, "end": s.end, "text": s.text.strip()}
                    for s in segs]
        return segments, info.language
    except ImportError:
        pass
    try:
        import whisper
        print(f"   ↳ openai-whisper (موديل {model_name})")
        model = whisper.load_model(model_name)
        res = model.transcribe(str(wav), language=language)
        segments = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                    for s in res["segments"]]
        return segments, res.get("language", lang)
    except ImportError:
        sys.exit("❌ ماكو مكتبة تفريغ. نفّذ:  pip install faster-whisper")


def save_transcript(segments, out_dir):
    plain = " ".join(s["text"] for s in segments).strip()
    (out_dir / "transcript.txt").write_text(plain + "\n", encoding="utf-8")

    timed = "\n".join(f"[{fmt_time(s['start'])} - {fmt_time(s['end'])}] {s['text']}"
                      for s in segments)
    (out_dir / "transcript_timestamps.txt").write_text(timed + "\n", encoding="utf-8")

    srt = []
    for i, s in enumerate(segments, 1):
        srt.append(f"{i}\n{fmt_time(s['start'], True)} --> "
                   f"{fmt_time(s['end'], True)}\n{s['text']}\n")
    (out_dir / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
    return plain, timed


# ---------------------------------------------------------------- 5) البرومبت
def template_prompt(info, language, timed, frames):
    return f"""# برومبت كامل عن الفيديو: {info['file']}

## معلومات تقنية
- المدة: {info['duration']}
- الدقة: {info.get('width')}x{info.get('height')}  |  {info.get('fps')} إطار/ثانية
- لغة الكلام: {language}
- عدد اللقطات المستخرجة: {len(frames)} (موجودة بمجلد frames)

## المطلوب
أنت محلل محتوى فيديو محترف. اعتماداً على النص الكامل بالأسفل (مع التوقيتات):
1. اكتب ملخص واضح للفيديو بـ 5-7 أسطر.
2. استخرج الأفكار والنقاط الرئيسية بالترتيب مع توقيت كل نقطة.
3. حدد الموضوع العام، الجمهور المستهدف، وأسلوب المتحدث (رسمي/عفوي/تعليمي...).
4. اقترح 5 عناوين جذابة للفيديو ووصف مناسب لليوتيوب/السوشيال ميديا مع هاشتاكات.
5. اقترح أهم المقاطع (Clips) القصيرة اللي تصلح ريلز/شورتس مع توقيت البداية والنهاية.
6. صحح أي أخطاء واضحة بالتفريغ النصي إذا وجدت.

## النص الكامل مع التوقيتات
{timed}
"""


def claude_prompt(info, language, timed, api_key):
    instruction = f"""هذا تفريغ نصي (مع التوقيتات) لفيديو اسمه "{info['file']}"، مدته {info['duration']}، دقته {info.get('width')}x{info.get('height')}، ولغة الكلام فيه {language}.

اكتب "برومبت" كامل ومفصّل باللغة العربية يصف هذا الفيديو، بحيث لو أعطيته لأي ذكاء اصطناعي يفهم الفيديو بالكامل ويقدر يعيد إنتاجه أو يشتغل عليه. البرومبت لازم يحتوي:
- ملخص المحتوى والفكرة الرئيسية
- تسلسل المشاهد/الأفكار بالترتيب مع التوقيتات
- أسلوب المتحدث ونبرة الفيديو والجمهور المستهدف
- الكلمات المفتاحية والمواضيع
- اقتراحات عناوين ووصف وهاشتاكات
- أفضل المقاطع القصيرة (ريلز/شورتس) مع توقيتاتها
اكتب البرومبت بصيغة Markdown فقط بدون مقدمات.

التفريغ:
{timed}"""
    body = json.dumps({
        "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": instruction}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data["content"])


# ---------------------------------------------------------------- 6) التجميع
def make_zip(folder):
    zip_path = folder.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(folder.parent))
    return zip_path


def main():
    ap = argparse.ArgumentParser(description="فيديو -> صوت + نص + برومبت + ملف ZIP")
    ap.add_argument("video", help="مسار الفيديو")
    ap.add_argument("--lang", default="auto", help="لغة الكلام: ar / en / auto")
    ap.add_argument("--model", default="small",
                    help="موديل Whisper: tiny/base/small/medium/large-v3 (أكبر = أدق وأبطأ)")
    ap.add_argument("--frames", type=int, default=6, help="عدد اللقطات (0 = بدون)")
    ap.add_argument("--out", default="output", help="مجلد النتائج")
    ap.add_argument("--no-zip", action="store_true", help="لا تسوي ملف ZIP")
    a = ap.parse_args()

    check_ffmpeg()
    video = Path(a.video).expanduser().resolve()
    if not video.exists():
        sys.exit(f"❌ الملف مو موجود: {video}")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(a.out) / f"{video.stem}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("1/6 قراءة معلومات الفيديو...")
    info = video_info(video)
    if not info["has_audio"]:
        sys.exit("❌ الفيديو ما بيه صوت.")
    print(f"   ↳ المدة {info['duration']}  |  {info.get('width')}x{info.get('height')}")

    print("2/6 استخراج الصوت...")
    mp3, wav = extract_audio(video, out_dir)

    print("3/6 استخراج لقطات من الفيديو...")
    frames = extract_frames(video, out_dir, info["duration_sec"], a.frames)

    print("4/6 تحويل الكلام إلى نص (ممكن ياخذ وقت)...")
    segments, language = transcribe(wav, a.lang, a.model)
    wav.unlink(missing_ok=True)
    if not segments:
        print("   ⚠️ ما انلگى كلام واضح بالفيديو.")
    plain, timed = save_transcript(segments, out_dir)

    print("5/6 كتابة البرومبت...")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    prompt, source = None, "template"
    if api_key and segments:
        try:
            prompt, source = claude_prompt(info, language, timed, api_key), "claude"
        except Exception as e:
            print(f"   ⚠️ فشل الاتصال بـ Claude ({e}) - راح استخدم القالب.")
    if not prompt:
        prompt = template_prompt(info, language, timed, frames)
    (out_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    info.update({"language": language, "segments": len(segments),
                 "words": len(plain.split()), "prompt_source": source,
                 "created": stamp})
    (out_dir / "info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    print("6/6 تجميع الملف النهائي...")
    zip_path = None if a.no_zip else make_zip(out_dir)

    print("\n✅ خلص!")
    print(f"   المجلد: {out_dir}")
    if zip_path:
        print(f"   ملف ZIP: {zip_path}")
    print("   المحتويات: audio.mp3 | transcript.txt | transcript_timestamps.txt |"
          " subtitles.srt | prompt.md | info.json | frames/")


if __name__ == "__main__":
    main()
