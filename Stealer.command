#!/bin/bash
# Double-click to open Stealer in your browser. Keep this window open while you work.
cd "$(dirname "$0")" || exit 1
clear
printf '\033[1m  Figma Stealer\033[0m\n\n'
if ! command -v python3 >/dev/null 2>&1; then
  printf '\033[31m  python3 not found.\033[0m Install Python 3.9 or newer and run this again.\n\n'
  read -r -p '  Press Enter to close '; exit 1
fi
printf '  Opening http://127.0.0.1:8800 in your browser. Press Ctrl+C to stop.\n\n'
python3 -m coloro serve
echo
read -r -p '  Stopped. Press Enter to close '
