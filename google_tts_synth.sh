#!/bin/zsh
# Google Cloud Text-to-Speech で音声ファイルだけを作る（再生はしない）。
# 標準出力に、できた mp3 のファイルパスを1行だけ返す。
# 使い方: google_tts_synth.sh <話者> <テキスト>
# 単体で使うのではなく google_tts_say.sh・google_tts_queue.sh から呼ぶ部品。

VOICE_KEY="${1:-leda}"
shift
TEXT="$*"
[[ -z "$TEXT" ]] && { echo "ERROR: テキストが空" >&2; exit 1 }

case "$VOICE_KEY" in
  leda)   VOICE="ja-JP-Chirp3-HD-Leda" ;;
  charon) VOICE="ja-JP-Chirp3-HD-Charon" ;;
  aoede)  VOICE="ja-JP-Chirp3-HD-Aoede" ;;
  kore)   VOICE="ja-JP-Chirp3-HD-Kore" ;;
  *)      VOICE="$VOICE_KEY" ;;
esac

GCLOUD="$(command -v gcloud || echo "$HOME/google-cloud-sdk/bin/gcloud")"
PROJECT="あなたのプロジェクトID"  # gcloud projects list で確認して書き換える
MP3=$(mktemp -t gtts).mp3

# トークンは50分キャッシュする（毎回 gcloud を起動すると数秒待たされるため）
TOKEN_CACHE="${TMPDIR:-/tmp}/gtts_token_cache"
if [[ -f "$TOKEN_CACHE" && -n "$(find "$TOKEN_CACHE" -mmin -50 2>/dev/null)" ]]; then
  TOKEN=$(cat "$TOKEN_CACHE")
else
  TOKEN=$("$GCLOUD" auth print-access-token 2>/dev/null) || { echo "ERROR: gcloud認証失敗" >&2; exit 2 }
  (umask 077; echo "$TOKEN" > "$TOKEN_CACHE")
fi

TEXT="$TEXT" VOICE="$VOICE" TTS_TOKEN="$TOKEN" TTS_PROJECT="$PROJECT" python3 - <<'PYEOF' > "$MP3"
import json, base64, os, sys, urllib.request
body = json.dumps({
    "input": {"text": os.environ["TEXT"]},
    "voice": {"languageCode": "ja-JP", "name": os.environ["VOICE"]},
    "audioConfig": {"audioEncoding": "MP3"},
}).encode()
req = urllib.request.Request(
    "https://texttospeech.googleapis.com/v1/text:synthesize",
    data=body,
    headers={
        "Authorization": "Bearer " + os.environ["TTS_TOKEN"],
        "Content-Type": "application/json",
        "x-goog-user-project": os.environ["TTS_PROJECT"],
    },
)
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.load(r)
sys.stdout.buffer.write(base64.b64decode(d["audioContent"]))
PYEOF

if [[ ! -s "$MP3" ]]; then
  echo "ERROR: 音声合成失敗" >&2
  rm -f "$MP3"
  exit 3
fi

echo "$(date +%Y-%m-%d) ${#TEXT} $VOICE" >> "$HOME/Library/Scripts/google_tts_usage.log"
echo "$MP3"
