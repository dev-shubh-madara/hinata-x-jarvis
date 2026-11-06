#!/data/data/com.termux/files/usr/bin/bash
# Hinata Link - one-time setup on the phone (run inside Termux).
# Usage (Hinata shows this line as a QR):  curl -fsSL <this file> | bash -s <key>
set -e
KEY="$1"
REPO="https://raw.githubusercontent.com/dev-shubh-madara/hinata-x-jarvis/main/phone"
DIR="$HOME/.hinata"
say() { printf '\n\033[1;35m== %s\033[0m\n' "$*"; }

say "Hinata Link setup"
mkdir -p "$DIR"

say "Installing Python (one time, about a minute)"
yes | pkg update -y >/dev/null 2>&1 || true
pkg install -y python procps termux-tools >/dev/null

say "Downloading the Hinata helper"
curl -fsSL "$REPO/hinata_agent.py" -o "$DIR/hinata_agent.py"
if [ -n "$KEY" ]; then
  printf '{"key": "%s"}\n' "$KEY" > "$DIR/link.json"
  chmod 600 "$DIR/link.json"
fi
[ -f "$DIR/link.json" ] || { echo "No key given - scan Hinata's QR again."; exit 1; }

say "Looking for rish (exported from Shizuku)"
if [ ! -d "$HOME/storage" ]; then
  echo "Allow Termux to access storage in the popup..."
  termux-setup-storage || true
  for i in $(seq 1 30); do [ -d "$HOME/storage/shared" ] && break; sleep 1; done
fi
FOUND=""
for d in /sdcard/Documents/sh /sdcard/documents/sh /sdcard/Shizuku /sdcard/Documents/Shizuku \
         /sdcard/Download/Shizuku /sdcard/Download /sdcard/Documents /sdcard; do
  if [ -f "$d/rish" ] && [ -f "$d/rish_shizuku.dex" ]; then FOUND="$d"; break; fi
done
if [ -z "$FOUND" ]; then
  echo "Could not find rish."
  echo "In Shizuku: 'Use Shizuku in terminal apps' > 'Export files' > pick Documents/sh, then run this again."
  exit 1
fi
cp "$FOUND/rish" "$FOUND/rish_shizuku.dex" "$DIR/"
sed -i 's/PKG/com.termux/g' "$DIR/rish"
chmod 700 "$DIR/rish"
chmod 400 "$DIR/rish_shizuku.dex"      # Android 14+ refuses a writable dex
echo "rish copied from $FOUND"

say "Checking Shizuku (tap Allow if Shizuku asks)"
if sh "$DIR/rish" -c "echo shizuku-ok" 2>/dev/null | grep -q shizuku-ok; then
  echo "Shizuku is working."
else
  echo "Shizuku isn't running yet: open Shizuku > Start, then come back and run:  hinata-start"
fi

say "Making Hinata Link start by itself"
START='pgrep -f hinata_agent.py >/dev/null || (termux-wake-lock; nohup python ~/.hinata/hinata_agent.py >~/.hinata/agent.log 2>&1 &)'
grep -q hinata_agent "$HOME/.bashrc" 2>/dev/null || echo "$START" >> "$HOME/.bashrc"
mkdir -p "$HOME/.termux/boot"
printf '#!/data/data/com.termux/files/usr/bin/sh\n%s\n' "$START" > "$HOME/.termux/boot/hinata.sh"
chmod 700 "$HOME/.termux/boot/hinata.sh"
printf '#!/data/data/com.termux/files/usr/bin/sh\npkill -f hinata_agent.py; %s\necho started\n' "$START" > "$PREFIX/bin/hinata-start"
chmod 755 "$PREFIX/bin/hinata-start"

pkill -f hinata_agent.py 2>/dev/null || true
termux-wake-lock || true
nohup python "$DIR/hinata_agent.py" > "$DIR/agent.log" 2>&1 &
sleep 2
say "Done! Hinata will connect to this phone in a few seconds."
echo "Keep Termux in the background. After a phone restart: open Shizuku > Start, then open Termux."
