#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
asr_build.py —— 博主科普讲解动画生成器 · 自录音频接入层（本技能新增）。

【作用】把用户**自己录制的人声 MP3** 识别成「文字 + 词级时间轴」，产出与
`tts_build.py` **完全一致**的 `audio-manifest.json`，从而无缝接入下游
`timeline_build.py → subs.py → render_video.mjs` 渲染管线（这些脚本零改动）。

【为什么需要这一层】html-explainer 原生只有「文案 → edge-tts/火山 TTS」一条配音路径。
本技能补上第二条：**直接喂自己录的口播 MP3**。ASR 把音频转成词级时间戳（boundaries），
字幕逐句对齐人声、画面节拍 B() 锚在真实吐字时刻上 —— 与 TTS 路径同源同构。

【两种模式】
  ① 按句切分（默认，--split）：ASR 识别出整段文本后，按标点切句，每句一个 segment，
     对应 narration.json 里的 id。适合「先有口播、想逐句做动画」的常规科普片。
  ② 整段（--no-split）：整条 MP3 作为一个 segment（id=voice），时间轴只有一段，
     字幕块靠 | 手动切。适合短口播 / 单镜头片。

【模型】faster-whisper（本地 CTranslate2，CPU 可跑），默认 small 模型。
首次运行自动下载模型（~500MB，缓存到 ~/.cache）。可选 --model tiny/base/small/medium。

【数据口径对齐 tts_build.py】
  - container_duration_sec  容器时长 → 帧时长（音画同步）
  - speech_end_sec          语音真实结束（裁后坐标系）→ 末块字幕收尾
  - lead_cut_sec            首裁量（ASR 首字前静音，通常为 0）
  - boundaries              [{text, offset_sec, duration_sec}] 词级时间戳

用法：
  python asr_build.py --project . --audio 我的口播.mp3 [--model small] [--no-split]
产出：
  audio/<id>.mp3（逐段）+ audio/narration-full.mp3（整条）+ audio-manifest.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 切句标点（中文句读）
_SENT_SPLIT = re.compile(r'[。！？!?；;]')
# 保留在 spoken 里的块切分（| 已由 narration.json 文本携带，ASR 不产生 |）


def ffmpeg_exe() -> str:
    from shutil import which
    p = which("ffmpeg")
    if p:
        return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def container_duration(path: str) -> float:
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path],
                       capture_output=True, text=True, errors="replace")
    for line in r.stderr.splitlines():
        if "Duration:" in line:
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            return round(int(h) * 3600 + int(m) * 60 + float(s), 3)
    return 0.0


def decode_pcm(path: str, sr: int = 16000):
    import numpy as np
    r = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", path, "-f", "f32le",
                        "-ac", "1", "-ar", str(sr), "-"], capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


def load_whisper(model_name: str):
    """懒加载 faster-whisper，给清晰的安装指引。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "✗ 缺少 faster-whisper，请先安装：\n"
            "  pip install faster-whisper\n"
            "  （首次识别会自动下载模型，small 约 500MB，缓存在 ~/.cache）",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"[asr] 加载模型 {model_name}（首次会下载）...", file=sys.stderr)
    # cpu_threads 自适应；int8 量化省内存，CPU 友好
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe(model, audio_path: str) -> list[dict]:
    """识别 → 词级时间戳列表 [{text, offset_sec, duration_sec}]。"""
    segments, info = model.transcribe(audio_path, language="zh",
                                      word_timestamps=True, vad_filter=True)
    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({
                "text": w.word.strip(),
                "offset_sec": round(float(w.start), 4),
                "duration_sec": round(max(0.01, float(w.end) - float(w.start)), 4),
            })
    return words


def split_sentences(words: list[dict]) -> list[list[dict]]:
    """按句读标点把词序列切成句，返回每句的词列表。"""
    sents: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        cur.append(w)
        if _SENT_SPLIT.search(w["text"]):
            if cur:
                sents.append(cur)
                cur = []
    if cur:
        sents.append(cur)
    return sents


def words_to_text(words: list[dict]) -> str:
    return "".join(w["text"] for w in words).strip()


def write_mp3_slice(src: str, dst: str, start_sec: float, end_sec: float):
    """从源音频切出一段 MP3（用 ffmpeg，保留 128k）。"""
    ff = ffmpeg_exe()
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{start_sec:.3f}", "-to", f"{end_sec:.3f}",
           "-i", src, "-c:a", "libmp3lame", "-b:a", "128k", dst]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="自录音频 → audio-manifest（接入 html-explainer 管线）")
    ap.add_argument("--project", default=".")
    ap.add_argument("--audio", required=True, help="自录人声 MP3 路径")
    ap.add_argument("--model", default="small",
                    help="faster-whisper 模型：tiny/base/small/medium（默认 small）")
    ap.add_argument("--no-split", action="store_true", help="整段作为一个 segment（不按句切）")
    ap.add_argument("--gap", type=float, default=-1, help="段间静音秒（默认取 project.json.gap）")
    args = ap.parse_args()

    proj = os.path.abspath(args.project)
    src = os.path.abspath(args.audio)
    if not os.path.exists(src):
        print(f"✗ 找不到音频：{src}", file=sys.stderr)
        return 1

    pj = json.load(open(os.path.join(proj, "project.json"), encoding="utf-8"))
    narration = json.load(open(os.path.join(proj, "narration.json"), encoding="utf-8"))
    if isinstance(narration, dict):
        narration = narration.get("items") or []
    order = pj.get("order") or [it["id"] for it in narration]

    # 总时长
    total = container_duration(src)
    print(f"[asr] 音频 {os.path.basename(src)} · 容器 {total:.2f}s", file=sys.stderr)

    model = load_whisper(args.model)
    words = transcribe(model, src)
    if not words:
        print("✗ ASR 未识别到任何语音（检查音频是否为人声、音量是否正常）", file=sys.stderr)
        return 1
    print(f"[asr] 识别到 {len(words)} 个词", file=sys.stderr)

    out_dir = os.path.join(proj, "audio")
    os.makedirs(out_dir, exist_ok=True)

    results: list[dict] = []
    full_text = words_to_text(words)

    if args.no_split:
        # 整段：单 segment，id 取 narration 第一个或 'voice'
        sid = order[0] if order else "voice"
        seg_words = words
        segs = [(sid, seg_words)]
    else:
        # 按句切分，与 narration.json 的 id 顺序对齐（数量不足则自动补 id）
        sents = split_sentences(words)
        segs = []
        for i, sw in enumerate(sents):
            sid = order[i] if i < len(order) else f"seg{i + 1}"
            segs.append((sid, sw))

    # 逐段写 MP3 与 manifest item
    gap = args.gap if args.gap >= 0 else float(pj.get("gap", 0.35))
    cursor = 0.0
    layout = {}
    for idx, (sid, sw) in enumerate(segs):
        if not sw:
            continue
        text = words_to_text(sw)
        # 段在整条音频里的起止秒（词边界）
        start = sw[0]["offset_sec"]
        end = sw[-1]["offset_sec"] + sw[-1]["duration_sec"]
        # 补一点句尾余量，避免切掉尾音（首句从头开始）
        seg_start = 0.0 if idx == 0 else max(0.0, start - 0.05)
        seg_end = min(total, end + 0.12)

        mp3_path = os.path.join(out_dir, f"{sid}.mp3")
        if not write_mp3_slice(src, mp3_path, seg_start, seg_end):
            print(f"✗ 切分 {sid} 失败", file=sys.stderr)
            return 1

        dur = container_duration(mp3_path)
        # 词边界换算到段内坐标系（减 seg_start）
        boundaries = [{
            "text": w["text"],
            "offset_sec": round(max(0.0, w["offset_sec"] - seg_start), 4),
            "duration_sec": w["duration_sec"],
        } for w in sw]

        results.append({
            "id": sid,
            "path": os.path.abspath(mp3_path),
            "bytes": os.path.getsize(mp3_path),
            "voice": "asr(自录音频)",
            "rate": "0%",
            "spoken_text": text,
            "original_text": text,
            "duration_sec": round(dur, 3),
            "lead_cut_sec": 0.0,
            "container_duration_sec": dur,
            "speech_start_sec": 0.0,
            "speech_end_sec": round(max(0.0, end - seg_start), 3),
            "tail_pad_sec": round(max(0.0, dur - (end - seg_start)), 3),
            "boundary_count": len(boundaries),
            "boundaries": boundaries,
        })
        layout[sid] = {"start_sec": round(cursor, 3), "duration_sec": dur}
        cursor += dur + gap

    # 写 manifest（结构对齐 tts_build.py）
    manifest = {
        "provider": "asr",
        "voice": "自录人声（faster-whisper 识别）",
        "rate": "0%",
        "trimmed": False,
        "engine": f"faster-whisper ({args.model})",
        "boundary_mode": "word-timestamps",
        "items": results,
    }
    mp = os.path.join(proj, "audio-manifest.json")
    json.dump(manifest, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 写 layout.json（timeline_build.py 也能重跑覆盖；这里先写一份供 subs.py 直接读）
    layout["_total"] = {"audio_duration_sec": round(total, 3),
                        "video_duration_sec": round(total, 3),
                        "gap_sec": gap, "fps": pj.get("fps", 30)}
    json.dump(layout, open(os.path.join(proj, "layout.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 整条音轨直接复用原 MP3（保证音画时长一致；不用 ffmpeg 二次拼接）
    full = os.path.join(out_dir, "narration-full.mp3")
    if args.no_split:
        subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                        "-i", src, "-c:a", "libmp3lame", "-b:a", "128k", full],
                       capture_output=True)
    else:
        subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                        "-i", src, "-c:a", "libmp3lame", "-b:a", "128k", full],
                       capture_output=True)

    print(f"[asr] {len(results)} 段 → audio/ + {mp}")
    print(f"[asr] 识别全文：\n{full_text}")
    print(f"\n[asr] ⚠ 请核对识别文本是否准确 —— 若有人名/术语/数字识别错误，")
    print(f"      直接改 narration.json 的对应 text（改文字不改音频时间轴，")
    print(f"      字幕会按音频时间轴对齐，文字可手动订正）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
