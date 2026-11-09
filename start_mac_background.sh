#!/bin/bash
# Zagon bota v ozadju macOS s spremljanjem PID-a
DIR="/Users/zigapesti/Desktop/feri_praksa_bot"
PID_FILE="$DIR/bot.pid"

# Preveri ce ze tece
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Bot ze tece z PID: $PID"
        exit 0
    fi
fi

# Zazeni v ozadju z nohup
nohup python3 "$DIR/praksa_bot.py" >> "$DIR/bot.log" 2>&1 &
echo $! > "$PID_FILE"

echo "FERI Praksa Notifier Bot je sedaj uspesno zagnan v ozadju (PID: $(cat "$PID_FILE"))!"
echo "Dnevnik lahko spremljas z:"
echo "tail -f $DIR/bot.log"
