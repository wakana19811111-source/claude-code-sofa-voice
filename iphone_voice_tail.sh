#!/bin/bash
# iPhone から届いた音声入力テキストを、手前にある VS Code のフォルダに合うときだけ出す。
#
# 使い方: iphone_voice_tail.sh <フォルダ名>
#
# Claude Code の Monitor から呼ぶ。複数セッションが同じログを見ていても、
# しゃべる直前にクリックしたウィンドウのセッションだけが拾う。

FOLDER="$1"
LOG="$HOME/Library/Logs/iphone_voice.log"

if [ -z "$FOLDER" ]; then
    echo "使い方: $0 <フォルダ名>"
    exit 1
fi

front_window() {
    # 最前面アプリが VS Code のときだけ、その手前のウィンドウ名を返す
    osascript <<'AS' 2>/dev/null
tell application "System Events"
    set frontApp to name of first process whose frontmost is true
    if frontApp is not "Code" then return ""
    tell process "Code"
        try
            return name of (first window whose value of attribute "AXMain" is true)
        on error
            return ""
        end try
    end tell
end tell
AS
}

tail -n 0 -f "$LOG" | while IFS= read -r line; do
    case "$line" in
        *"【iPhone音声】"*) ;;
        *) continue ;;
    esac
    win=$(front_window)
    case "$win" in
        *"$FOLDER"*) echo "$line" ;;
        *) : ;;  # 手前が別フォルダ・別アプリなら黙る
    esac
done
