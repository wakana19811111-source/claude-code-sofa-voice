#!/bin/bash
# 音声入力の部品 DictationIM を、落ちたままにしない。
#
# なぜ要るか（実測）:
#   DictationIM は「最後にしゃべり終わってから きっかり117秒」で終了する。
#   落ちている状態で Ctrl キー2回を押すと、そのキーは起動の合図に使われて
#   マイクアイコンまで届かない（＝空振り）。もう一度押せば出るが、毎回わずらわしい。
#
# 何をするか:
#   LaunchAgent（com.example.dictation-keepalive.plist）から90秒ごとに呼ばれ、
#   DictationIM の生死を見て、落ちていたら launchctl kickstart で起こす。
#   ⛔ open -a での起動は macOS が拒否してクラッシュ報告が出る。必ず launchctl 経由にすること。
#
# 止め方: launchctl bootout gui/$(id -u)/com.example.dictation-keepalive

LOG="$HOME/Library/Logs/dictation_keepalive.log"

if ! pgrep -x DictationIM >/dev/null 2>&1; then
    launchctl kickstart "gui/$(id -u)/com.apple.DictationIM" 2>/dev/null
    sleep 2
    if pgrep -x DictationIM >/dev/null 2>&1; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 起こした（PID $(pgrep -x DictationIM | head -1)）" >> "$LOG"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠ 起こせなかった" >> "$LOG"
    fi
fi

# ログが太らないよう、1000行を超えたら古い分を捨てる
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 1000 ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
