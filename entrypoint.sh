#!/bin/sh
set -e

# 少し待機 (Xvfbが起動する時間を確保)
sleep 2

# Fluxboxの設定ファイルを上書きしてパネルと背景を消す（非rootユーザー用）
mkdir -p $HOME/.fluxbox
cat <<EOF > $HOME/.fluxbox/init
session.screen0.toolbar.visible: false
session.screen0.rootCommand: xsetroot -solid black
session.menuFile: /dev/null
EOF

# 設定内容をログに出力
echo "==== $HOME/.fluxbox/init ===="
cat $HOME/.fluxbox/init
echo "============================="

# スマートKeep-aliveプロセス: アクティブセッションがある時のみFly.io自動停止を防ぐ
# Fly.ioは自動停止の機能があり、節約のために常時実行していない。そのためBrowser-useの起動時のみ実行しつづける必要がある。
(
  while true; do
    sleep 15  # より良い応答性のためにより頻繁なチェック
    # Browser-useのアイドリング中に止まらないように、アクティブセッション検出を行う。
    # AgentオブジェクトはFastAPIプロセス内のPythonオブジェクトであり、別個のプロセスではないため検知できない。
    # 必要最小限のプロセス検出
    chromium_processes=$(pgrep -f "chromium.*--remote-debugging" 2>/dev/null | wc -l || echo 0)
    vnc_processes=$(pgrep -f "x11vnc\|Xvfb" 2>/dev/null | wc -l || echo 0)
    active_sessions=$((chromium_processes + vnc_processes))
    
    if [ "$active_sessions" -gt 0 ]; then
      echo "$(date): Active sessions: $active_sessions (chromium: $chromium_processes, vnc/display: $vnc_processes) - Keeping alive"
      # 最小限のアクティビティでFly.io自動停止を防ぐ
      dd if=/dev/zero of=/tmp/keepalive bs=512 count=1 2>/dev/null && rm -f /tmp/keepalive
    else
      # アクティブセッションがない場合は静かに待機（自動停止を許可）
      echo "$(date): No active sessions - Allowing auto-stop"
    fi
    
    # 古いXvfbとVNCプロセスをクリーンアップ
    # 例: 24時間以上アクティブでないセッションを終了など
  done
) &

# Uvicornサーバーをフォアグラウンドで実行
# exec を使うことで、uvicornがこのスクリプトのプロセスを引き継ぎ、
# Dockerからのシグナルを正しく受け取れるようにする
exec uvicorn main:app --host 0.0.0.0 --port 8081