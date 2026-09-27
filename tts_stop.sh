#!/bin/zsh
# 読み上げを止める
# 使い方: tts_stop.sh
#   いま再生している google_tts_say.sh と afplay を止める。
#   次に読む分を裏で合成している google_tts_synth.sh も一緒に止めるので、
#   止めた直後に続きの声が出ることはない。
#
# キーボード1つで止めたいときは、ショートカット.app に
# 「シェルスクリプトを実行」で $HOME/Library/Scripts/tts_stop.sh を登録し、
# そのショートカットにキーボードショートカットを割り当てる。

pkill -f "google_tts_say.sh" 2>/dev/null
pkill -f "google_tts_synth.sh" 2>/dev/null
pkill -f "google_tts_queue.sh" 2>/dev/null
pkill -x afplay 2>/dev/null
pkill -x say 2>/dev/null

# 合成の途中ファイルが残っていたら片付ける
# ⚠ zsh は「一致なし」でエラーを出すので null_glob を付ける
setopt null_glob
rm -f /tmp/gtts_next* "$TMPDIR"gtts_next* 2>/dev/null

# 走っている読み上げの控え（google_tts_say.sh が書く PID）も消す
rm -f "${TMPDIR:-/tmp}/gtts_current.pid" 2>/dev/null

exit 0
