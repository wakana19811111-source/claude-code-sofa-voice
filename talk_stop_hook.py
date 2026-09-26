#!/usr/bin/env python3
"""talk_stop_hook.py — Claude Code の Stop フックから呼ばれ、最後の返事を必ず声で読む（2026-09-26 作成）

Claude が読み上げコマンドを呼び忘れても、返事が終わるたびにこのプログラムが動き、
会話の記録（transcript）から最後の返事を取り出し、声向けに整形して
~/Library/Scripts/google_tts_say.sh leda "本文" に渡す。

動く条件
  1. ~/Library/Scripts/talk_mode.on がある（無ければ何もしない。touch で作り、rm で消す）
     ⭐ 中にセッションIDが書いてあれば、そのセッションの返事だけ読む。空なら全セッションで読む。
  2. stop_hook_active が true でない（無限ループ防止）
  3. そのターンのきっかけが「バックグラウンド通知だけ」でない。
     ただし通知の中に【iPhone音声】があれば iPhone から話した声なので必ず読む。

テスト用
  TALK_DRY_RUN=1 … 読み上げず、整形後の本文を標準出力へ出す（フラグの有無も無視）
  --transcript <path> … 標準入力の JSON を使わず、記録ファイルを直接指定する
  --text-file <path>  … 記録ではなく、ファイルの本文をそのまま整形する（整形だけの確認用）

絶対に守ること
  どんな例外でも exit 0。標準出力には（ドライラン以外）何も出さない。
  エラーは ~/Library/Logs/talk_stop_hook.log に日時つきで1行足す。
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

HOME = os.path.expanduser("~")
SCRIPTS_DIR = os.path.join(HOME, "Library", "Scripts")
FLAG_PATH = os.path.join(SCRIPTS_DIR, "talk_mode.on")
FIXES_PATH = os.path.join(SCRIPTS_DIR, "talk_reading_fixes.json")
TTS_PATH = os.path.join(SCRIPTS_DIR, "google_tts_say.sh")
LOG_PATH = os.path.join(HOME, "Library", "Logs", "talk_stop_hook.log")
VOICE = "leda"

MAX_CHARS = 3000
WAIT_TOTAL_SEC = 1.5
WAIT_STEP_SEC = 0.2

VOICE_MARK = "【iPhone音声】"
SPEAK_MARK = "🔊"
OMITTED_NOTE = "ユーアールエルやコードは、画面に出しました。"
TRUNCATED_NOTE = "以降は画面をご覧ください。"

DRY_RUN = os.environ.get("TALK_DRY_RUN", "") not in ("", "0")


# ---------------------------------------------------------------- ログ
def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ---------------------------------------------------------------- 記録の読み取り
def _text_of_blocks(content):
    """message.content から、最上位の text ブロックだけをつないで返す（tool_result の中身は見ない）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "\n".join(parts)
    return ""


def _has_block(content, kind):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == kind for b in content
    )


def load_events(path):
    """記録 JSONL を、会話の流れの並び（イベント列）にする。
    ("user", 本文) … 利用者の入力・通知（attachment の queued_command を含む）
    ("assistant", 本文) … Claude の文章
    ("tool", "") … ツール呼び出し・ツール結果（返事がまだ書かれていないかの判定に使う）
    ("interrupt", "") … 利用者による中断
    """
    events = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            t = d.get("type")
            if t == "user":
                msg = d.get("message") or {}
                content = msg.get("content")
                text = _text_of_blocks(content)
                if text.strip():
                    if text.lstrip().startswith("[Request interrupted"):
                        events.append(("interrupt", ""))
                    else:
                        events.append(("user", text))
                elif _has_block(content, "tool_result"):
                    events.append(("tool", ""))
            elif t == "assistant":
                msg = d.get("message") or {}
                content = msg.get("content")
                text = _text_of_blocks(content)
                if text.strip():
                    events.append(("assistant", text))
                elif _has_block(content, "tool_use"):
                    events.append(("tool", ""))
            elif t == "attachment":
                a = d.get("attachment")
                if isinstance(a, dict) and a.get("type") == "queued_command":
                    p = a.get("prompt")
                    if isinstance(p, str) and p.strip():
                        events.append(("user", p))
    return events


def pick_turn(events):
    """最後のターンの（きっかけの本文たち, 最終返事の本文）を返す。返事が無ければ (trigger, None)"""
    last_user = None
    for i in range(len(events) - 1, -1, -1):
        if events[i][0] == "user":
            last_user = i
            break
    if last_user is None:
        return [], None

    # きっかけ＝前のターンの返事より後ろにある user 行すべて
    start = 0
    for i in range(last_user - 1, -1, -1):
        if events[i][0] == "assistant":
            start = i + 1
            break
    triggers = [e[1] for e in events[start:last_user + 1] if e[0] == "user"]

    final = None
    for i in range(last_user + 1, len(events)):
        if events[i][0] == "assistant":
            final = events[i][1]
    return triggers, final


def wait_for_turn(path):
    """書き込みの遅れに備え、最大 WAIT_TOTAL_SEC のあいだ 0.2 秒おきに読み直す"""
    deadline = time.monotonic() + WAIT_TOTAL_SEC
    triggers, final = [], None
    while True:
        try:
            events = load_events(path)
            triggers, final = pick_turn(events)
            if final is not None:
                return triggers, final
        except FileNotFoundError:
            pass
        if time.monotonic() >= deadline:
            return triggers, final
        time.sleep(WAIT_STEP_SEC)


# ---------------------------------------------------------------- 読むターンかの判定
_SYSREM_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_TASKNOTE_RE = re.compile(r"<task-notification>.*?</task-notification>", re.S)


def should_speak(triggers):
    """(読むか, 理由)"""
    if not triggers:
        return False, "きっかけの入力が見つからない"
    joined = "\n".join(triggers)
    if VOICE_MARK in joined:
        return True, "iPhone音声"
    for t in triggers:
        rest = _SYSREM_RE.sub("", t)
        rest = _TASKNOTE_RE.sub("", rest)
        if "[SYSTEM NOTIFICATION" in rest:
            continue
        if rest.strip():
            return True, "文字入力"
    return False, "通知だけのターン"


# ---------------------------------------------------------------- 整形
_PATH_EXTS = (
    "md txt py sh zsh json jsonl html htm css js ts pdf docx xlsx pptx csv log png jpg jpeg gif svg "
    "mp3 mp4 wav yaml yml toml zip tar gz swift plist on off bak pid tmp jsx tsx rb go rs sql xml ipynb"
).split()
_EXT_RE = re.compile(r"^[^\s]+\.(?:%s)$" % "|".join(_PATH_EXTS), re.I)
_URL_RE = re.compile(r"(?:https?|ftp)://[^\s、。，「」『』（）()<>\"']+|www\.[^\s、。，「」『』（）()<>\"']+")
_TOKEN_SPLIT_RE = re.compile(r"([\s、。，,！？!?「」『』（）()【】：；;])")
_FENCE_RE = re.compile(r"```.*?(?:```|\Z)", re.S)
_TILDE_FENCE_RE = re.compile(r"^~~~.*?(?:^~~~[ \t]*$|\Z)", re.S | re.M)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# スラッシュで始まる語の扱い：
#   /compact や /hooks のようなスラッシュコマンドは、ファイルの場所ではないので読む（スラッシュは読まず、名前だけ読む）。
#   インラインコードも、単語1つだけ（例 `/hooks` `Stop`）なら中身を読む。ファイル名・式・長いものは今までどおり外す。
_SIMPLE_CODE_RE = re.compile(r"/?[A-Za-z][A-Za-z0-9_-]*")
_SLASH_CMD_RE = re.compile(r"(?<![A-Za-z0-9_/.~-])/([A-Za-z][A-Za-z0-9_-]*)(?![A-Za-z0-9_/.-])")
# 月/日 → 「8月23日」に直してから辞書（月の読み）へ渡す（そのままだと 8/23 が分数として読まれる）
_YMD_SLASH_RE = re.compile(r"(?<![0-9A-Za-z/._-])(20[0-9]{2})/(1[0-2]|0?[1-9])/(3[01]|[12][0-9]|0?[1-9])(?![0-9/]|\.[A-Za-z0-9])")
_MD_SLASH_RE = re.compile(r"(?<![0-9A-Za-z/._-])(1[0-2]|0?[1-9])/(3[01]|[12][0-9]|0?[1-9])(?![0-9/]|\.[A-Za-z0-9])")


def _slash_dates(text):
    text = _YMD_SLASH_RE.sub(lambda m: "%d年%d月%d日" % (int(m.group(1)), int(m.group(2)), int(m.group(3))), text)
    return _MD_SLASH_RE.sub(lambda m: "%d月%d日" % (int(m.group(1)), int(m.group(2))), text)

_IMG_LINK_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD2_RE = re.compile(r"__(.+?)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_BULLET_RE = re.compile(r"^\s*(?:[-*+](?=\s)|[•・◦▪▸►]|[①-⑳]|\d{1,3}[.．)）](?=\s)|[a-zA-Z][.)](?=\s)|\(\d{1,3}\))\s*")
_CHECKBOX_RE = re.compile(r"^\s*\[(?: |x|X|✓|✔)\]\s*")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_ARROW_RE = re.compile(r"\s*[→⇒➡⟶⇨]\s*")
_KEEP_SYMBOLS = {"○", "◎", "◯", "×"}
_TERMINALS = "。！？!?"

# 絵文字・記号の範囲（○◎◯× は残す）
def _is_symbol(ch):
    if ch in _KEEP_SYMBOLS:
        return False
    o = ord(ch)
    return (
        0x1F000 <= o <= 0x1FAFF
        or 0x2600 <= o <= 0x27BF
        or 0x2B00 <= o <= 0x2BFF
        or 0x2300 <= o <= 0x23FF
        or 0x25A0 <= o <= 0x25FF
        or 0x2190 <= o <= 0x21FF
        or 0x2900 <= o <= 0x297F
        or o in (0xFE0F, 0x200D, 0x203B, 0x2122, 0x00A9, 0x00AE, 0x20E3, 0x3030, 0x303D)
        or 0xE000 <= o <= 0xF8FF
    )


def _strip_symbols(s):
    return "".join(ch for ch in s if not _is_symbol(ch))


class Shaper:
    def __init__(self):
        self.omitted = False

    # --- 1行の中の処理（表のセル・箇条書きの1項目・普通の行に共通）
    def inline(self, s):
        if _URL_RE.search(s):
            self.omitted = True
            s = _URL_RE.sub("", s)
        if _IMG_LINK_RE.search(s) or _LINK_RE.search(s):
            self.omitted = True
            s = _IMG_LINK_RE.sub(r"\1", s)
            s = _LINK_RE.sub(r"\1", s)
        if _INLINE_CODE_RE.search(s):
            s = _INLINE_CODE_RE.sub(self._inline_code, s)
        s = _HTML_TAG_RE.sub("、", s)
        s = _BOLD_RE.sub(r"\1", s)
        s = _BOLD2_RE.sub(r"\1", s)
        s = _STRIKE_RE.sub(r"\1", s)
        s = _ITALIC_RE.sub(r"\1", s)
        s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", r"\1", s)
        s = _slash_dates(s)   # 8/23 → 8月23日（パス判定より先に）
        s = _SLASH_CMD_RE.sub(r"\1", s)
        s = self._drop_paths(s)
        s = _ARROW_RE.sub("、", s)
        s = _strip_symbols(s)
        # 中身が消えて空になった括弧
        s = re.sub(r"[（(]\s*[）)]|「\s*」|『\s*』|【\s*】|\[\s*\]", "", s)
        s = re.sub(r"[ \t　]+", " ", s).strip()
        return s

    def _inline_code(self, m):
        body = m.group(0)[1:-1].strip()
        if _SIMPLE_CODE_RE.fullmatch(body):
            return body          # 単語1つ・スラッシュコマンドは読む
        self.omitted = True      # それ以外（ファイル名・式・長いもの）は外す
        return ""

    def _drop_paths(self, s):
        parts = _TOKEN_SPLIT_RE.split(s)
        out = []
        for tok in parts:
            if tok and not _TOKEN_SPLIT_RE.fullmatch(tok) and self._looks_like_path(tok):
                self.omitted = True
                continue
            out.append(tok)
        return "".join(out)

    @staticmethod
    def _looks_like_path(tok):
        t = tok.strip().rstrip("。、,.")
        if not t:
            return False
        if t.startswith(("~/", "./", "../", "/")) or t.endswith("/"):
            return True
        if _EXT_RE.match(t):
            return True
        if "/" in t:
            if t.count("/") >= 2:
                return True
            if re.search(r"[A-Za-z_]", t):
                return True
        return False

    @staticmethod
    def _sentence(s):
        s = s.strip()
        if not s:
            return ""
        if s.endswith(("：", ":")):
            s = s[:-1].rstrip() + "。"
        elif s.endswith("、"):
            pass
        elif s[-1] not in _TERMINALS:
            s += "。"
        return s

    def _table_row(self, line):
        body = line.strip()
        if body.startswith("|"):
            body = body[1:]
        if body.endswith("|"):
            body = body[:-1]
        cells = [self.inline(c) for c in body.split("|")]
        cells = [c for c in cells if c]
        if not cells:
            return ""
        joined = "、".join(c.rstrip("。") for c in cells)
        return joined + "。"

    # --- 本文全体
    def shape(self, text):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if _FENCE_RE.search(text):
            self.omitted = True
            text = _FENCE_RE.sub("\n", text)
        if _TILDE_FENCE_RE.search(text):
            self.omitted = True
            text = _TILDE_FENCE_RE.sub("\n", text)

        sentences = []
        for raw in text.split("\n"):
            line = raw.rstrip()
            if not line.strip():
                continue
            if _HR_RE.match(line):
                continue
            stripped = line.strip()
            if stripped.startswith("|") or (stripped.count("|") >= 2 and not stripped.startswith("`")):
                if _TABLE_SEP_RE.match(stripped):
                    continue
                s = self._table_row(stripped)
                if s:
                    sentences.append(s)
                continue
            line = _QUOTE_RE.sub("", line)
            line = _HEADING_RE.sub("", line)
            line = _CHECKBOX_RE.sub("", _BULLET_RE.sub("", line))
            line = _CHECKBOX_RE.sub("", line)
            s = self.inline(line)
            s = self._sentence(s)
            if s:
                sentences.append(s)

        out = "".join(sentences)
        out = self._tidy(out)
        return out

    @staticmethod
    def _tidy(s):
        for _ in range(3):
            s = s.replace("、。", "。").replace("。、", "。").replace("、、", "、").replace("。。", "。")
            s = re.sub(r"(?<=[。！？])\s*、", "", s)
        s = re.sub(r"^[、。\s]+", "", s)
        s = re.sub(r"[ \t　]+", " ", s)
        return s.strip()


def pick_speak_paragraph(text):
    """返事の最後のほうに「🔊」で始まる段落があれば、その段落の本文だけを返す。無ければ None"""
    paras = re.split(r"\n\s*\n", text)
    for p in reversed(paras):
        first = p.strip()
        first = re.sub(r"^[>\s*_\-]+", "", first)
        if first.startswith(SPEAK_MARK):
            body = first[len(SPEAK_MARK):]
            body = re.sub(r"^[\s:：]+", "", body)
            return body if body.strip() else None
    return None


def truncate(text):
    if len(text) <= MAX_CHARS:
        return text, False
    head = text[:MAX_CHARS]
    cut = max(head.rfind("。"), head.rfind("！"), head.rfind("？"))
    if cut >= MAX_CHARS // 2:
        head = head[:cut + 1]
    return head, True


# ---------------------------------------------------------------- 読み間違え辞書
def load_fixes():
    try:
        with open(FIXES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        log("辞書の読み込みに失敗（辞書なしで続行）: %r" % (e,))
        return []
    pairs = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            if isinstance(v, dict):
                for a, b in v.items():
                    if isinstance(a, str) and isinstance(b, str) and a:
                        pairs[a] = b
    return sorted(pairs.items(), key=lambda kv: len(kv[0]), reverse=True)


def _fix_pattern(key):
    pat = re.escape(key)
    first, last = key[0], key[-1]
    if re.match(r"[A-Za-z]", first):
        pat = r"(?<![A-Za-z])" + pat
    elif re.match(r"[0-9０-９]", first):
        pat = r"(?<![0-9０-９])" + pat
    if re.match(r"[A-Za-z]", last):
        pat = pat + r"(?![a-z])"
    elif re.match(r"[0-9０-９]", last):
        pat = pat + r"(?![0-9０-９])"
    return re.compile(pat)


def apply_fixes(text, pairs):
    for key, val in pairs:
        try:
            text = _fix_pattern(key).sub(val, text)
        except Exception as e:
            log("辞書の語で失敗（飛ばす）: %r %r" % (key, e))
    return text


# ---------------------------------------------------------------- 本文を声の形にする（入口）
_DEFAULT_EXCLUDE_LINES = [r"^\s*iPhone音声の受け取りを(?:仕掛け直した|仕掛けた).*$"]


def _drop_excluded_lines(text):
    """声から外す行。
    辞書 JSON の「声から外す行」（正規表現のリスト）に足せば、コードを直さずに増やせる。"""
    pats = _DEFAULT_EXCLUDE_LINES
    try:
        with open(FIXES_PATH, "r", encoding="utf-8") as f:
            extra = json.load(f).get("声から外す行")
        if isinstance(extra, list) and extra:
            pats = [p for p in extra if isinstance(p, str)]
    except Exception:
        pass
    for pat in pats:
        try:
            text = re.sub(pat, "", text, flags=re.M)
        except re.error:
            continue
    return text


def build_speech(reply_text):
    """返事の本文 → 声に渡す本文。読むものが無ければ空文字"""
    reply_text = _drop_excluded_lines(reply_text)
    target = pick_speak_paragraph(reply_text)
    if target is None:
        target = reply_text
    shaper = Shaper()
    body = shaper.shape(target)
    body = apply_fixes(body, load_fixes())
    body, truncated = truncate(body)
    if not body.strip():
        return ""
    if truncated:
        body += TRUNCATED_NOTE
    if shaper.omitted:
        body += OMITTED_NOTE
    return body


def speak(text):
    subprocess.Popen(
        [TTS_PATH, VOICE, text],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


# ---------------------------------------------------------------- main
def _parse_args(argv):
    opts = {"transcript": None, "text_file": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--transcript" and i + 1 < len(argv):
            opts["transcript"] = argv[i + 1]
            i += 2
        elif a == "--text-file" and i + 1 < len(argv):
            opts["text_file"] = argv[i + 1]
            i += 2
        else:
            i += 1
    return opts


def _flag_allows(session_id):
    """talk_mode.on が無ければ False。中にセッションIDが書いてあれば一致したときだけ True"""
    try:
        with open(FLAG_PATH, "r", encoding="utf-8") as f:
            want = f.read().strip()
    except FileNotFoundError:
        return False
    except Exception:
        return True
    if want and session_id and want != session_id:
        return False
    return True


def main():
    opts = _parse_args(sys.argv[1:])

    # 整形だけの確認（記録を使わない）
    if opts["text_file"]:
        with open(opts["text_file"], "r", encoding="utf-8") as f:
            out = build_speech(f.read())
        if DRY_RUN:
            sys.stdout.write(out + "\n")
        elif out:
            speak(out)
        return

    hook_input = {}
    if opts["transcript"]:
        transcript = opts["transcript"]
    else:
        # フラグが無ければ、標準入力を読む前に即終了（起動を軽くする）
        if not DRY_RUN and not os.path.exists(FLAG_PATH):
            return
        try:
            raw = sys.stdin.read()
            hook_input = json.loads(raw) if raw.strip() else {}
        except Exception as e:
            log("入力 JSON を読めない: %r" % (e,))
            return
        if not isinstance(hook_input, dict):
            return
        transcript = hook_input.get("transcript_path")

    if hook_input.get("stop_hook_active"):
        return
    if not DRY_RUN and not _flag_allows(hook_input.get("session_id")):
        return
    if not transcript:
        log("transcript_path が無い")
        return

    triggers, final = wait_for_turn(transcript)
    if final is None:
        if not os.path.exists(transcript):
            log("記録ファイルが無い: %s" % transcript)
        else:
            log("最終返事が見つからない（待ち %.1f 秒）: %s" % (WAIT_TOTAL_SEC, os.path.basename(transcript)))
        return

    ok, why = should_speak(triggers)
    if not ok:
        if DRY_RUN:
            sys.stdout.write("（読まない: %s）\n" % why)
        else:
            log("読まない: %s" % why)
        return

    out = build_speech(final)
    if not out:
        log("整形後が空（読まない）")
        return
    if DRY_RUN:
        sys.stdout.write(out + "\n")
        return
    speak(out)
    log("読み上げ %d 文字（%s）" % (len(out), why))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except Exception as e:
        log("例外: %r" % (e,))
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
    os._exit(0)
