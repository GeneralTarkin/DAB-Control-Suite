#!/bin/bash

APP="app.py"
PORT=8088

start() {
    echo "▶ Starte MWI DAB Server..."
    nohup python3 "$APP" > server.log 2>&1 &
    sleep 2

    if ss -ltn | grep -q ":$PORT "; then
        echo "✅ Server läuft auf Port $PORT"
    else
        echo "❌ Server konnte nicht gestartet werden."
    fi
}

stop() {
    echo "■ Stoppe Server..."
    pkill -f "python3 $APP" 2>/dev/null || true
    sleep 1
}

restart() {
    stop
    start
}

status() {
    echo
    echo "===== Prozesse ====="
    pgrep -af "$APP" || echo "Keine"

    echo
    echo "===== Port ====="
    ss -ltnp | grep ":$PORT" || echo "Nicht geöffnet"
}

logs() {
    tail -f server.log
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    *)
        echo "MWI DAB Server Entwicklerwerkzeug"
        echo
        echo "Verwendung:"
        echo "  ./tools/dev.sh start"
        echo "  ./tools/dev.sh stop"
        echo "  ./tools/dev.sh restart"
        echo "  ./tools/dev.sh status"
        echo "  ./tools/dev.sh logs"
        ;;
esac
