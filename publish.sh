#!/bin/bash
# Собирает чистую копию для публикации: только исходники и документация.
# Ничего не удаляет и не трогает рабочую папку — делает отдельную копию рядом.
#
# Запуск:  ./publish.sh  [путь-назначения]
set -u

SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${1:-$SRC/../color-inventory-publish}"

# Белый список: публикуется ТОЛЬКО то, что перечислено здесь.
FILES=(
  "app.py" "scan.py" "aggregate.py" "report.py" "launch.py"
  "app.html"
  "README.md" "README.ru.md" "ARCHITECTURE.ru.md" "LICENSE" ".gitignore"
  "settings.example.json" "allfiles.example.json"
  "Color Inventory.command"
  "publish.sh"
)
# Папки целиком (скриншоты для README).
DIRS=( "docs" "demo" )

printf '\033[1mCollecting a clean copy\033[0m\n'
mkdir -p "$DST"
# Чистим содержимое, но НЕ трогаем .git: иначе при каждой пересборке
# терялись бы история и настройка remote.
find "$DST" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
for f in "${FILES[@]}"; do
  if [ -e "$SRC/$f" ]; then
    cp "$SRC/$f" "$DST/$f"
    printf '  + %s\n' "$f"
  else
    printf '  \033[33m? missing: %s\033[0m\n' "$f"
  fi
done
for d in "${DIRS[@]}"; do
  if [ -d "$SRC/$d" ]; then
    cp -R "$SRC/$d" "$DST/$d"
    printf '  + %s/\n' "$d"
  fi
done

printf '\n\033[1mScanning the copy for anything private\033[0m\n'
BAD=0

check () {  # описание, регулярка
  local what="$1" re="$2"
  local hits
  hits=$(grep -rInE "$re" "$DST" 2>/dev/null | grep -v '^Binary' | head -5)
  if [ -n "$hits" ]; then
    printf '  \033[31mFOUND %s:\033[0m\n' "$what"
    printf '%s\n' "$hits" | sed 's/^/      /'
    BAD=1
  else
    printf '  ok — no %s\n' "$what"
  fi
}

check "Figma file links"   'figma\.com/(file|design|proto)/[A-Za-z0-9]{10,}'
check "Figma file keys"    '[^A-Za-z0-9]([A-Za-z0-9]{22})[^A-Za-z0-9]'
check "home paths"         '/Users/[a-z]'
check "access tokens"      'figd_[A-Za-z0-9_-]{10,}'

# Файлы с данными не должны попасть в копию вообще.
for leak in out raw token.txt settings.json sources.json tokens.json colors-report.html; do
  if [ -e "$DST/$leak" ]; then
    printf '  \033[31mFOUND data file: %s\033[0m\n' "$leak"; BAD=1
  fi
done

echo
if [ "$BAD" -ne 0 ]; then
  printf '\033[31mNot clean. Fix what is listed above before publishing.\033[0m\n'
  exit 1
fi
printf '\033[32mClean.\033[0m Ready to publish:\n\n'
printf '  cd %s\n  git init && git add . && git commit -m "Color Inventory"\n' "$DST"
printf '  git remote add origin git@github.com:<you>/color-inventory.git\n  git push -u origin main\n\n'
