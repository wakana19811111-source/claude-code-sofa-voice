#!/bin/bash
# Claude Code の SessionStart hook から呼ぶ。
# 今のセッションの作業フォルダ名を調べて、「その名前で見張りを立てろ」と Claude に伝える。
# 見張り本体は iphone_voice_tail.sh（手前のVS Codeウィンドウが一致したときだけ通す）。

FOLDER=$(basename "$PWD")

MSG="iPhoneから音声入力されたテキストを受け取れるようにするため、このターンの最初に Monitor ツールで次を仕掛けること（persistent: true, timeout_ms: 3600000）：$HOME/Library/Scripts/iphone_voice_tail.sh ${FOLDER} 。これは手前にあるVS Codeのウィンドウが「${FOLDER}」のときだけ声を拾う仕組みで、他のセッションとの取り合いを防いでいる。説明は「iPhone音声の受け取りを仕掛けた（${FOLDER}）」の1行だけにして、通常の作業を続けること。"

python3 -c "
import json, sys
msg = sys.argv[1]
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': msg,
    }
}, ensure_ascii=False))
" "$MSG"
