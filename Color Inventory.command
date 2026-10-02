#!/bin/bash
# Double-click this file to open Color Inventory in your browser.
cd "$(dirname "$0")" || exit 1
clear
printf '\033[1m  Color Inventory\033[0m\n\n'

if ! command -v python3 >/dev/null 2>&1; then
  printf '\033[31m  python3 not found.\033[0m Install it and run this again.\n\n'
  read -r -p '  Press Enter to close '; exit 1
fi

if [ -z "$FIGMA_TOKEN" ] && [ ! -s token.txt ] \
   && [ ! -s "$HOME/.config/figma-colors/token" ] && [ ! -s "$HOME/.config/kiss/figma-token" ]; then
  printf '\033[31m  No Figma token found.\033[0m Do one of these:\n'
  printf '    - put the token in token.txt next to this file;\n'
  printf '    - or in ~/.config/figma-colors/token;\n'
  printf '    - or set the FIGMA_TOKEN environment variable.\n\n'
  printf '  Create one in Figma: Settings - Security - Personal access tokens.\n\n'
  read -r -p '  Press Enter to close '; exit 1
fi

printf '  Opening http://localhost:8800 in your browser.\n'
printf '  Keep this window open while you work. Press Ctrl+C to stop.\n\n'
python3 app.py
echo
read -r -p '  Stopped. Press Enter to close '
