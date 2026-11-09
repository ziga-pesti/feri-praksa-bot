#!/bin/bash
DIR="/Users/zigapesti/Desktop/feri_praksa_bot"
PID_FILE="$DIR/bot.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID"
        rm -f "$PID_FILE"
        echo "FERI Praksa Notifier Bot (PID: $PID) je bil uspesno ustavljen."
        exit 0
    fi
    rm -f "$PID_FILE"
fi

# Fallback kill po imenu
pkill -f "praksa_bot.py" 2>/dev/null && echo "Bot je bil ustavljen." || echo "Bot ni bil zagnan."
