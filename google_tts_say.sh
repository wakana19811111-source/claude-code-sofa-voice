#!/bin/zsh
# Google Cloud Text-to-Speech で読み上げる
# 使い方: google_tts_say.sh <話者> <テキスト>
# 合成に失敗した分だけ、Mac 内蔵の say -v Kyoko で読む

SCRIPT_DIR="${0:A:h}"
SYNTH="$SCRIPT_DIR/google_tts_synth.sh"

# 前の読み上げが再生中なら止める（あとから来たほうを読む）
STATE="${TMPDIR:-/tmp}/gtts_current.pid"
if [[ -f "$STATE" ]]; then
  OLD=$(cat "$STATE" 2>/dev/null)
  if [[ -n "$OLD" && "$OLD" != "$$" ]] && kill -0 "$OLD" 2>/dev/null; then
    pkill -P "$OLD" 2>/dev/null   # 子（afplay・say・合成）を先に止める
    kill "$OLD" 2>/dev/null
  fi
fi
pkill -x afplay 2>/dev/null       # 親がいなくなって再生が続いている分も止める
echo $$ > "$STATE"
# 控えを消すのは、中身が自分の PID のときだけ（あとから来たものの控えを消さない）
trap '[[ "$(cat "$STATE" 2>/dev/null)" == "$$" ]] && rm -f "$STATE" 2>/dev/null' EXIT

VOICE_KEY="${1:-leda}"
shift
TEXT="$*"
[[ -z "$TEXT" ]] && { echo "ERROR: テキストが空" >&2; exit 1 }

# 文を分ける：1つ目は、文の切れ目で25文字を超えたら閉じる（最初の声を早く出すため）
# 2つ目からは400文字ずつ。最後の1つが20文字未満なら、1つ前にくっつける
CHUNK_STR=$(TEXT="$TEXT" python3 - <<'PYEOF'
import os, re
t = os.environ["TEXT"].replace("\n", " ")
sents = [s for s in re.findall(r"[^。！？]*[。！？]?", t) if s.strip()]
chunks, buf = [], ""
cur_limit = 25
for s in sents:
    buf += s
    if len(buf) >= cur_limit:
        chunks.append(buf)
        buf = ""
        cur_limit = 400
if buf:
    chunks.append(buf)
if len(chunks) >= 2 and len(chunks[-1]) < 20:
    chunks[-2] += chunks[-1]
    chunks.pop()
print("\x1f".join(chunks))
PYEOF
)
typeset -a CHUNKS
CHUNKS=("${(@ps.\x1f.)CHUNK_STR}")

play_or_say() {  # $1=mp3のパス $2=元の文
  if [[ -n "$1" && -s "$1" ]]; then
    afplay "$1"
    rm -f "$1"
  else
    echo "WARN: Google TTS 失敗。Kyoko で読み上げます" >&2
    say -v Kyoko "$2"
  fi
}

N=${#CHUNKS}
MP3=$("$SYNTH" "$VOICE_KEY" "${CHUNKS[1]}")
i=1
while (( i <= N )); do
  # いまの1つを再生している間に、次の1つを裏で合成する
  if (( i < N )); then
    NEXT_OUT=$(mktemp -t gtts_next)
    ( "$SYNTH" "$VOICE_KEY" "${CHUNKS[i+1]}" > "$NEXT_OUT" 2>/dev/null ) &
    NEXT_PID=$!
  fi
  play_or_say "$MP3" "${CHUNKS[i]}"
  if (( i < N )); then
    wait $NEXT_PID
    MP3=$(cat "$NEXT_OUT" 2>/dev/null)
    rm -f "$NEXT_OUT"
  fi
  (( i++ ))
done
