#!/bin/zsh
# 話者の交代がある会話を、待ち時間を重ねて読み上げる。
# 「1つ目を読み上げている間に、2つ目の音声合成を裏で終わらせておく」仕組み。
# 読み終わるのを待ってから次の通信に行く、という無駄をなくす。
#
# 使い方: google_tts_queue.sh 話者1 本文1 話者2 本文2 ...（話者と本文のペアを並べる）
# 例:
#   google_tts_queue.sh charon "テストの結果を報告します。" leda "12件すべて通りました。"

SCRIPT_DIR="${0:A:h}"
SYNTH="$SCRIPT_DIR/google_tts_synth.sh"

typeset -a ARGS
ARGS=("$@")
PAIRS=$(( $#ARGS / 2 ))
(( PAIRS < 1 )) && { echo "ERROR: 話者と本文をペアで渡してください" >&2; exit 1 }

typeset -a FILES
i=1
# 1本目は再生前に合成が要るので、ここだけ待つ
FILES[1]=$("$SYNTH" "${ARGS[1]}" "${ARGS[2]}")
if [[ -z "${FILES[1]}" ]]; then
  echo "WARN: Google TTS 失敗。Kyoko で読み上げます（この1本のみ）" >&2
  say -v Kyoko "${ARGS[2]}"
  FILES[1]=""
fi

while (( i <= PAIRS )); do
  if [[ -n "${FILES[i]}" && "${FILES[i]}" != "__SPOKEN__" ]]; then
    afplay "${FILES[i]}" &
    PLAY_PID=$!
  else
    PLAY_PID=""
  fi

  next=$(( i + 1 ))
  if (( next <= PAIRS )); then
    # いま再生している間に、次の合成を終わらせておく
    idx=$(( (next - 1) * 2 + 1 ))
    FILES[next]=$("$SYNTH" "${ARGS[idx]}" "${ARGS[idx+1]}")
    if [[ -z "${FILES[next]}" ]]; then
      [[ -n "$PLAY_PID" ]] && wait $PLAY_PID
      echo "WARN: Google TTS 失敗。Kyoko で読み上げます（この1本のみ）" >&2
      say -v Kyoko "${ARGS[idx+1]}"
      FILES[next]="__SPOKEN__"
      PLAY_PID=""
    fi
  fi

  [[ -n "$PLAY_PID" ]] && wait $PLAY_PID
  [[ -n "${FILES[i]}" && "${FILES[i]}" != "__SPOKEN__" ]] && rm -f "${FILES[i]}"
  i=$(( i + 1 ))
done
