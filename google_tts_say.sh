#!/bin/zsh
# Google Cloud Text-to-Speech で読み上げる。
# 使い方: google_tts_say.sh <話者> <テキスト>
#   話者: leda（女声・既定） / charon（男声） / aoede（女声2） / kore（女声3）
#         または ja-JP-… のフルネーム
# 失敗したら Mac 内蔵の say -v Kyoko に自動で切り替える。
#
# 話者が交代する会話を続けて読むときは、このスクリプトを何回も呼ばず
# google_tts_queue.sh を使う（次の声の合成を、今の声の再生中に裏で終わらせられる）。

SCRIPT_DIR="${0:A:h}"
VOICE_KEY="${1:-leda}"
shift
TEXT="$*"
[[ -z "$TEXT" ]] && { echo "ERROR: テキストが空" >&2; exit 1 }

MP3=$("$SCRIPT_DIR/google_tts_synth.sh" "$VOICE_KEY" "$TEXT")
if [[ -z "$MP3" || ! -s "$MP3" ]]; then
  echo "WARN: Google TTS 失敗。Kyoko で読み上げます" >&2
  exec say -v Kyoko "$TEXT"
fi

afplay "$MP3"
rm -f "$MP3"
