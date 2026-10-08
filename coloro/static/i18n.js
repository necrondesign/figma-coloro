/* Interface language: English (as written in app.js) or Russian.

   The interface is written in English. In Russian every text that reaches the screen goes
   through a dictionary: whole phrases first, then sentence by sentence and part by part
   (" · "), then rules for phrases with numbers. Counted words ("2 colors") get the right
   Russian ending in app.js through I18N.plural, so the rules only move them in place.
   What people wrote — layer names, texts of the designs, comments, file names — is marked
   with data-u (or sits in code, .mono, .msg) and is never translated. */

"use strict";

const I18N = (() => {
  let lang = "en";
  try { lang = localStorage.getItem("coloro.lang") === "ru" ? "ru" : "en"; } catch (e) { /* optional */ }
  // «#/colors?lang=ru» — язык из ссылки, запоминается.
  const fromLink = (location.hash.split("?")[1] || "").match(/(?:^|&)lang=(en|ru)\b/);
  if (fromLink) {
    lang = fromLink[1];
    try { localStorage.setItem("coloro.lang", lang); } catch (e) { /* optional */ }
  }

  // Russian plural forms: one (1, 21), few (2–4, 22–24), many (5–20, 25…).
  const P = {
    color: ["цвет", "цвета", "цветов"], token: ["токен", "токена", "токенов"], text: ["текст", "текста", "текстов"],
    layer: ["слой", "слоя", "слоёв"], component: ["компонент", "компонента", "компонентов"], file: ["файл", "файла", "файлов"],
    screen: ["экран", "экрана", "экранов"], place: ["место", "места", "мест"], use: ["применение", "применения", "применений"],
    instance: ["инстанс", "инстанса", "инстансов"], image: ["картинка", "картинки", "картинок"],
    gradient: ["градиент", "градиента", "градиентов"], effect: ["эффект", "эффекта", "эффектов"],
    variable: ["переменная", "переменные", "переменных"], match: ["совпадение", "совпадения", "совпадений"],
    page: ["страница", "страницы", "страниц"], thread: ["обсуждение", "обсуждения", "обсуждений"],
    "open thread": ["открытое обсуждение", "открытых обсуждения", "открытых обсуждений"],
    "old thread": ["давнее обсуждение", "давних обсуждения", "давних обсуждений"],
    reply: ["ответ", "ответа", "ответов"], person: ["человек", "человека", "человек"],
    surface: ["поверхность", "поверхности", "поверхностей"], variant: ["вариант", "варианта", "вариантов"],
    value: ["значение", "значения", "значений"], mode: ["тема", "темы", "тем"],
    collection: ["коллекция", "коллекции", "коллекций"], snapshot: ["замер", "замера", "замеров"],
    spelling: ["написание", "написания", "написаний"], stop: ["стоп", "стопа", "стопов"],
    filter: ["фильтр", "фильтра", "фильтров"], day: ["день", "дня", "дней"],
    "text style": ["текстовый стиль", "текстовых стиля", "текстовых стилей"],
    "unused token": ["неиспользуемый токен", "неиспользуемых токена", "неиспользуемых токенов"],
    "unstyled text": ["текст без стиля", "текста без стиля", "текстов без стиля"],
    "rare color": ["редкий цвет", "редких цвета", "редких цветов"],
    "near-token color": ["цвет почти как токен", "цвета почти как токен", "цветов почти как токен"],
    "off-system color": ["цвет вне системы", "цвета вне системы", "цветов вне системы"],
    "opacity mismatch": ["расхождение прозрачности", "расхождения прозрачности", "расхождений прозрачности"],
    "possibly detached copy": ["возможно отвязанная копия", "возможно отвязанные копии", "возможно отвязанных копий"],
    "repeated text": ["повторяющийся текст", "повторяющихся текста", "повторяющихся текстов"],
    "set or component": ["набор или компонент", "набора или компонента", "наборов или компонентов"],
    "matching color value": ["подходящее значение цвета", "подходящих значения цвета", "подходящих значений цвета"],
    "spacing value": ["значение отступа", "значения отступа", "значений отступа"],
    "radius value": ["значение скругления", "значения скругления", "значений скругления"],
    "stroke value": ["значение обводки", "значения обводки", "значений обводки"],
    measurement: ["замер", "замера", "замеров"], unit: ["единица", "единицы", "единиц"],
  };
  const SINGULAR = { colors: "color", tokens: "token", texts: "text", layers: "layer", components: "component", files: "file",
    screens: "screen", places: "place", uses: "use", instances: "instance", images: "image", gradients: "gradient",
    effects: "effect", variables: "variable", matches: "match", pages: "page", threads: "thread", replies: "reply",
    people: "person", surfaces: "surface", variants: "variant", values: "value", modes: "mode", days: "day",
    snapshots: "snapshot", spellings: "spelling", stops: "stop" };
  const form = (n, forms) => {
    const a = Math.abs(n);
    if (!Number.isInteger(a)) return forms[1];
    const d = a % 10, h = a % 100;
    return d === 1 && h !== 11 ? forms[0] : d >= 2 && d <= 4 && (h < 12 || h > 14) ? forms[1] : forms[2];
  };
  /** The word for a count: plural("color", 3) → "цвета" in Russian, null when there is no entry. */
  function plural(n, one) {
    if (lang !== "ru") return null;
    const forms = P[one] || P[SINGULAR[one]];
    return forms ? form(n, forms) : null;
  }

  const MONTHS = { en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    ru: ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"] };

  // ---------------------------------------------------------------- whole phrases
  const D = {
    // panels and common
    "Stealer": "Stealer", "Projects": "Проекты", "New project": "Новый проект", "Files": "Файлы", "Add files": "Добавить файлы",
    "Options": "Параметры", "Update": "Обновить", "Updating…": "Обновление…", "Stop": "Остановить", "Include": "Учитывать",
    "Reset": "Сбросить", "Show": "Показать", "Show values": "Показать значения", "Settings": "Настройки", "Cancel": "Отмена",
    "Save": "Сохранить", "Close": "Закрыть", "Rename": "Переименовать", "Delete": "Удалить", "Delete project": "Удалить проект",
    "Rename project": "Переименовать проект", "Create project": "Создать проект", "Project name": "Название проекта",
    "Project created": "Проект создан", "Project deleted": "Проект удалён", "Saved": "Сохранено", "Copied": "Скопировано",
    "Loaded": "Загружено", "Loading…": "Загрузка…", "Loading layers…": "Загрузка слоёв…", "Summary": "Сводка",
    "Recommendations": "Рекомендации", "Nothing here": "Здесь ничего нет", "Nothing found": "Ничего не найдено",
    "No items match the current options and filters.": "Под текущие параметры и фильтры ничего не подходит.",
    "Nothing to fix here under the current filters.": "При текущих фильтрах здесь нечего исправлять.",
    "Collapse all three blocks": "Свернуть все три блока", "Toggle theme": "Сменить тему", "Projects and files": "Проекты и файлы",
    "View options": "Параметры просмотра", "Content type": "Тип контента",
    "Settings: Figma access, token library, updates": "Настройки: доступ к Figma, справочник токенов, обновления",
    "Create a new project": "Создать новый проект", "Add Figma files to this project": "Добавить файлы Figma в этот проект",
    "Download the report: one HTML file to share": "Скачать отчёт: один HTML-файл, чтобы поделиться",
    "Remove from project": "Убрать из проекта", "Open in Figma": "Открыть в Figma", "Open in Figma ↗": "Открыть в Figma ↗",
    "Open ↗": "Открыть ↗", "Figma ↗": "Figma ↗", "Screen in Figma ↗": "Экран в Figma ↗", "Open settings": "Открыть настройки",
    "Not loaded": "Не загружен", "Not loaded yet": "Ещё не загружен", "Needs an update": "Нужно обновить", "Untitled": "Без названия",
    "this project": "этот проект", "Hidden layers": "Скрытые слои", "Archived pages": "Архивные страницы",
    "Layers inside instances": "Слои внутри инстансов", "Page name contains": "Название страницы содержит",
    "Exclude sections containing": "Исключить секции, содержащие", "Layers added since": "Слои, добавленные с",
    "Files modified since": "Файлы, изменённые с", "All pages": "Все страницы", "None": "Ничего",
    "Only pages whose name contains": "Только страницы, в названии которых есть",
    "Reload from scratch": "Загрузить заново", "Pages": "Страницы", "Limit pages": "Ограничить страницы",
    "just now": "только что", "yesterday": "вчера", "never": "никогда",
    // types
    "Colors": "Цвета", "Tokens": "Токены", "Typography": "Типографика", "Text": "Тексты", "Spacing": "Отступы",
    "Spacing & radius": "Отступы и скругления", "Effects": "Эффекты", "Images": "Картинки", "Comments": "Комментарии",
    "Components": "Компоненты", "Search": "Поиск", "Gradients": "Градиенты", "Contrast": "Контраст", "Surfaces": "Поверхности",
    // search
    "Search text, layer or component names": "Текст, названия слоёв или компонентов", "Search by color": "Поиск по цвету",
    "Clear search": "Очистить поиск", "Width": "Ширина", "Height": "Высота", "Search text in": "Где искать текст",
    "Text layers": "Текстовые слои", "Layer and frame names": "Названия слоёв и фреймов", "Component names": "Названия компонентов",
    "Page and file names": "Названия страниц и файлов", "Match": "Совпадение", "Any word form": "Любая форма слова",
    "Exact phrase": "Точная фраза", "Whole words only": "Только целые слова", "Forgive typos": "Прощать опечатки",
    "Other keyboard layout and transliteration": "Другая раскладка и транслит", "Size tolerance, px": "Допуск размера, px",
    "Type": "Тип", "Component": "Компонент", "Page": "Страница", "Copy list": "Скопировать список",
    "Copy layers with links": "Скопировать слои со ссылками", "Color tolerance": "Допуск цвета", "Match opacity": "Учитывать прозрачность",
    "Opacity": "Прозрачность", "Search color": "Искать цвет", "Remove color": "Убрать цвет", "Pick a color from the screen": "Взять цвет с экрана",
    "Choose at least one place to search": "Выберите хотя бы одно место поиска", "Enter a color as #RRGGBB": "Введите цвет как #RRGGBB",
    "The words in this order, as written. Case and ё are ignored.": "Слова в этом порядке, как написано. Регистр и ё не важны.",
    "All words in any form and any order: “buy coins” finds “Buy 100 coins”.": "Все слова в любой форме и в любом порядке: «купить монеты» найдёт «Купить 100 монет».",
    "Not as part of a longer word.": "Не как часть более длинного слова.",
    "A word must be a form of the query word: “cat” finds “cats”, not “catalog”.": "Слово должно быть формой слова из запроса: «кот» найдёт «кота», но не «котлету».",
    "Also finds the query inside longer words.": "Находит запрос и внутри более длинных слов.",
    "Try other words, a larger tolerance, or include hidden layers and archived pages.": "Попробуйте другие слова, больший допуск или включите скрытые слои и архивные страницы.",
    "Try another query or relax the filters.": "Попробуйте другой запрос или ослабьте фильтры.",
    "Frames and groups": "Фреймы и группы", "Instances": "Инстансы", "Shapes": "Фигуры", "Other": "Другое", "Vectors": "Векторы",
    "No screen": "Без экрана", "Open the screen in Figma": "Открыть экран в Figma", "Select parent": "Выбрать родителя",
    // colors
    "Near token": "Почти токен", "Opacity mismatch": "Другая прозрачность", "Off-system": "Вне системы", "Unbound": "Не привязан",
    "Rare": "Редкие", "All": "Все", "Token": "Токен", "Near style": "Почти стиль", "Style or variable": "Стиль или переменная",
    "Where it is used": "Где используется", "Fills, strokes and gradients": "Заливки, обводки и градиенты",
    "Fills and strokes only": "Только заливки и обводки", "Gradients only": "Только градиенты", "Both": "И там, и там",
    "Sort by": "Сортировка", "Most used": "Чаще всего", "Number of files": "По числу файлов", "Lightness": "По светлоте",
    "Color family": "Семейство цвета", "Rare means used at most": "Редкий — использован не больше", "2 times": "2 раз",
    "5 times": "5 раз", "10 times": "10 раз", "Find in the list": "Найти в списке", "Hex, token or file name": "Hex, токен или файл",
    "Compare with theme": "Сравнивать с темой", "All themes": "Все темы", "Colors from the system": "Цвета из системы",
    "Stray colors": "Цвета мимо системы", "Set by hand": "Вручную", "Colors in use": "Цветов в макетах",
    "of color uses go through a token or style": "применений цвета — через токен или стиль",
    "of color uses have no token or style": "применений цвета — без токена и стиля",
    "a token library is required": "нужен справочник токенов", "fills and strokes": "заливки и обводки",
    "Every color in use.": "Все цвета в макетах.", "Every color in use": "Все цвета в макетах",
    "Looks the same as a token. Replace it with the token.": "На глаз не отличить от токена. Замените на токен.",
    "A token’s color with another opacity. Add a token with this opacity or use an existing one.": "Цвет токена с другой прозрачностью. Добавьте токен с такой прозрачностью или используйте существующий.",
    "Far from every token. Add it to the system or replace it.": "Далеко от всех токенов. Добавьте в систему или замените.",
    "Equal to a token but set by hand somewhere. Bind the variable: nothing changes visually.": "Равен токену, но где-то набран вручную. Привяжите переменную — на экране ничего не изменится.",
    "Used only a few times. Often a typo or a leftover.": "Использован всего несколько раз. Часто опечатка или остаток.",
    "They look the same as a token": "На глаз не отличить от токена", "Swap them for the closest token.": "Замените на ближайший токен.",
    "Used once or twice. Often a typo or a leftover.": "Использован один-два раза. Часто опечатка или остаток.",
    "Load the token library": "Загрузить справочник токенов", "Load a token library": "Загрузить справочник токенов",
    "Without it Stealer cannot tell which colors are outside the design system.": "Без него Stealer не отличит цвета вне дизайн-системы.",
    "Load the token library for exact names": "Загрузить справочник ради точных имён",
    "The system is now taken from styles and variables in the files. A library adds variable names and catches tokens nobody uses yet.": "Сейчас система берётся из стилей и переменных в файлах. Справочник добавит имена переменных и покажет токены, которые ещё нигде не используются.",
    "Where it is worst · stray colors": "Где хуже всего · цвета мимо системы", "How it changed": "Как менялось",
    "No change": "Без изменений", "Closest": "Ближайший", "set by hand": "вручную", "No token library": "Нет справочника токенов",
    "No token library and no colors from styles or variables in these files, so there is nothing to compare with.": "Нет справочника токенов и нет цветов из стилей или переменных — сравнивать не с чем.",
    "White": "Белый", "Black": "Чёрный", "Neutral": "Нейтральный", "Red": "Красный", "Orange": "Оранжевый", "Yellow": "Жёлтый",
    "Green": "Зелёный", "Teal": "Бирюзовый", "Blue": "Синий", "Purple": "Фиолетовый", "Magenta": "Пурпурный",
    // gradients
    "Gradient recipes": "Рецепты градиентов", "Uses": "Применений", "recipes without a style or variable": "рецептов без стиля и переменной",
    "They are set by hand. A gradient style keeps every use identical.": "Они набраны вручную. Стиль градиента делает все применения одинаковыми.",
    "One-off recipes are often variations of an existing gradient.": "Разовые рецепты — часто вариации существующего градиента.",
    "Each recipe (type and stops in order) is one row": "Каждый рецепт (вид и стопы по порядку) — одна строка",
    "Stop color hex": "Hex цвета стопа", "Linear": "Линейный", "Radial": "Радиальный", "Angular": "Угловой", "Diamond": "Ромбовидный",
    // contrast and surfaces
    "Fails WCAG": "Не проходит WCAG", "Check by eye": "Проверить глазами", "Texts checked": "Проверено текстов",
    "Fail WCAG": "Не проходят WCAG", "Unusual placements": "Необычные места", "on images, gradients, plate edges": "на картинках, градиентах, краях плашек",
    "Fails": "Не проходит", "large text": "крупный текст", "normal text": "обычный текст", "outlined": "с обводкой",
    "Text that is hard to read: below 4.5:1, or 3:1 for large text (24 px, or 18.66 px bold).": "Текст, который трудно прочесть: ниже 4,5:1, или 3:1 для крупного текста (24 px или 18,66 px жирный).",
    "Text on an image, a gradient or the edge of a plate. The contrast depends on the spot, so check it by eye.": "Текст на картинке, градиенте или на краю плашки. Контраст зависит от места — проверьте глазами.",
    "Readable: passes AA, not AAA.": "Читается: проходит AA, но не AAA.", "Passes AAA: 7:1, or 4.5:1 for large text.": "Проходит AAA: 7:1, или 4,5:1 для крупного текста.",
    "Every text color against its surface.": "Каждый цвет текста против его фона.",
    "The surface is what a layer lies on: the fill of the nearest frame or of a plate under it. Translucent fills are mixed with what is below, as the eye sees them.": "Поверхность — то, на чём лежит слой: заливка ближайшего фрейма или подложки под ним. Полупрозрачное смешивается с тем, что ниже, — как видит глаз.",
    "Every background in the files and what is placed on it: text colors with their contrast and components. Open a row to see the list.": "Все фоны в макетах и что на них стоит: цвета текста с контрастом и компоненты. Откройте строку, чтобы увидеть список.",
    "Hex, token, style or component": "Hex, токен, стиль или компонент", "Text on this surface": "Текст на этой поверхности",
    "Components on this surface": "Компоненты на этой поверхности", "All places": "Все места", "Image": "Картинка",
    "Gradient": "Градиент", "Partly on a plate": "Частично на плашке", "No background": "Без фона", "variable": "переменная",
    "style": "стиль", "token value set by hand": "значение токена вручную", "light": "светлый", "dark": "тёмный",
    "image": "картинка", "gradient": "градиент", "partly on a plate": "частично на плашке", "no background": "без фона",
    "Below the WCAG AA minimum: hard to read for many people, and in sunlight for everyone. Use a darker or lighter text token for this surface.": "Ниже минимума WCAG AA: многим трудно читать, а на солнце — всем. Возьмите для этого фона более тёмный или светлый токен текста.",
    "The component almost always stands on light (or dark) and here it does not. Usually another variant is meant.": "Компонент почти всегда стоит на светлом (или тёмном), а здесь — нет. Обычно тут нужен другой вариант.",
    "On images, gradients or the edge of a plate the contrast depends on the spot. A scrim or a whole plate under the text makes it safe.": "На картинках, градиентах и краях плашек контраст зависит от места. Затемнение или целая плашка под текстом решают это.",
    "Surfaces are not computed yet": "Поверхности ещё не посчитаны",
    "Stealer finds what each layer lies on while loading a file. Files loaded with an older version need one update.": "Stealer находит, на чём лежит каждый слой, во время загрузки файла. Файлам, загруженным старой версией, нужно одно обновление.",
    // tokens
    "Variables": "Переменные", "Numbers": "Числа", "Unused in the files": "Не используются в файлах", "Name": "Название",
    "Bound": "Привязано", "Typed by hand": "Вручную", "Used": "Используется", "Unused": "Не используется",
    "Also typed by hand": "Ещё и вручную", "All variables": "Все переменные", "No group": "Без группы", "Usage": "Использование",
    "Used in files": "Используются в файлах", "Change with theme": "Меняются с темой", "No value": "Без значения",
    "Group and name": "По группе и имени", "Find": "Найти", "Name or value": "Имя или значение", "Color": "Цвет", "Number": "Число",
    "String": "Строка", "Boolean": "Логическое", "Shadow": "Тень", "In files": "В файлах", "Not in the library": "Нет в библиотеке",
    "from name": "из имени", "No tokens": "Нет токенов", "No tokens match the options.": "Под параметры не подходит ни один токен.",
    "How many times layers are bound to this variable": "Сколько раз слои привязаны к этой переменной",
    "How many times its value is typed in by hand": "Сколько раз её значение набрано вручную",
    "How many times its value appears in the files": "Сколько раз её значение встречается в файлах",
    "Their values appear in the files typed in manually.": "Их значения встречаются в файлах, набранные вручную.",
    "No color or number in the selected files equals these tokens. They may be obsolete, or the files drifted from the system.": "Ни один цвет или число в выбранных файлах не равен этим токенам. Возможно, они устарели или файлы ушли от системы.",
    "Variables in the files": "Переменные в файлах", "Styles in the files": "Стили в файлах",
    "Bound in the files, not in the library": "Привязаны в файлах, но нет в библиотеке",
    "Figma does not give variable names on this plan. Load the token library to name them.": "На этом тарифе Figma не отдаёт имена переменных. Загрузите справочник токенов, чтобы назвать их.",
    "Layers use variables this library does not contain: another library, local variables or deleted ones.": "Слои используют переменные, которых нет в этом справочнике: из другой библиотеки, локальные или удалённые.",
    "The export has names but no values for them, so they cannot be compared. Export the variables with values to include them.": "В выгрузке есть имена, но нет значений, поэтому сравнить нельзя. Выгрузите переменные со значениями.",
    "No value in the file": "Нет значения в файле",
    // typography
    "Unstyled text": "Текст без стиля", "Texts without a style": "Тексты без стиля", "Text styles in the system": "Текстовые стили в системе",
    "Off-system combinations": "Сочетания вне системы", "of text placed by hand": "текста, положенного вручную",
    "Font, size and line height already match a style exactly. Nothing changes visually.": "Шрифт, размер и интерлиньяж уже точно как в стиле. На экране ничего не изменится.",
    "Same font and weight, size or line height differ by about a pixel. Often scaled text.": "Тот же шрифт и начертание, размер или интерлиньяж отличаются примерно на пиксель. Часто это отмасштабированный текст.",
    "No such combination in the system. Decide whether a new style is needed or use an existing one.": "Такого сочетания нет в системе. Решите, нужен ли новый стиль, или используйте существующий.",
    "The most common font combination of each style.": "Самое частое сочетание шрифта у каждого стиля.",
    "Matches": "Совпадает с", "Where it is worst · unstyled text": "Где хуже всего · текст без стиля", "Status": "Статус",
    "Font, size and line height match a text style, but the style is not applied. Apply it: nothing changes visually.": "Шрифт, размер и интерлиньяж совпадают с текстовым стилем, но стиль не назначен. Назначьте — на экране ничего не изменится.",
    "Same font and weight, slightly different size or line height. Often scaled text. Replace it with the style.": "Тот же шрифт и начертание, чуть другой размер или интерлиньяж. Часто это отмасштабированный текст. Замените стилем.",
    "Font weights or sizes that no style uses.": "Начертания или размеры, которых нет ни в одном стиле.",
    "Only text placed by hand is counted.": "Учитывается только текст, положенный вручную.",
    // text
    "Texts": "Текстов", "Repeated": "Повторяются", "Written differently": "По-разному написаны", "Without a style": "Без стиля",
    "Used once": "В одном месте", "Find text": "Найти текст", "Word or phrase": "Слово или фраза", "Most used first": "Сначала частые",
    "Number of screens": "По числу экранов", "Longest first": "Сначала длинные", "A to Z": "По алфавиту",
    "Styled or in instances": "Со стилем или в инстансах",
    "Every text in the files. The same text in different places is one row.": "Все тексты макетов. Одинаковый текст в разных местах — одна строка.",
    "Texts used in more than one place. Good candidates for a shared component or a copy deck.": "Тексты, которые встречаются больше чем в одном месте. Хорошие кандидаты в общий компонент или в копидек.",
    "Texts used in one place only.": "Тексты, которые встречаются в одном месте.",
    "The same text with different capitalization or spacing, such as “Buy now” and “Buy Now”.": "Одинаковый текст с разным регистром или пробелами, например «Купить сейчас» и «Купить Сейчас».",
    "Texts placed by hand without a text style in at least one place.": "Тексты, хотя бы в одном месте положенные вручную без текстового стиля.",
    "Texts are equal when they match ignoring case, ё and spaces.": "Тексты считаются одинаковыми без учёта регистра, ё и пробелов.",
    "The same words with different capitalization or spacing, such as “Buy now” and “Buy Now”.": "Одни и те же слова с разным регистром или пробелами, например «Купить сейчас» и «Купить Сейчас».",
    "Placed by hand without a text style in at least one place.": "Хотя бы в одном месте положен вручную без текстового стиля.",
    "Texts used on many screens are easier to keep consistent in a copy deck or a component.": "Тексты, которые стоят на многих экранах, проще держать одинаковыми в копидеке или компоненте.",
    // spacing and effects
    "Radius": "Скругления", "Stroke": "Обводки", "Off-scale": "Мимо шкалы", "Near the scale": "Рядом со шкалой",
    "Off the scale": "Мимо шкалы", "Bound to variables": "Привязано к переменным", "Near scale": "Почти по шкале",
    "On the grid": "По сетке", "On the scale": "По шкале", "of spacing, radius and stroke values": "отступов, скруглений и обводок",
    "Where it is worst · off-scale values": "Где хуже всего · значения мимо шкалы",
    "No spacing variables": "Нет переменных для отступов", "No radius variables": "Нет переменных для скруглений",
    "No stroke variables": "Нет переменных для обводок",
    "Spacing values are compared with a standard grid. Variables for the scale make the check exact.": "Отступы сравниваются со стандартной сеткой. Переменные шкалы сделают проверку точной.",
    "Radius values are compared with a standard grid. Variables for the scale make the check exact.": "Скругления сравниваются со стандартной сеткой. Переменные шкалы сделают проверку точной.",
    "Stroke values are compared with a standard grid. Variables for the scale make the check exact.": "Обводки сравниваются со стандартной сеткой. Переменные шкалы сделают проверку точной.",
    "Within a pixel of the scale.": "В пределах пикселя от шкалы.", "No such value in the scale. Replace with the closest value or add it to the scale.": "Такого значения нет в шкале. Замените ближайшим или добавьте в шкалу.",
    "On the scale but typed as numbers": "По шкале, но набрано числом", "Only layers placed by hand are counted.": "Учитываются только слои, положенные вручную.",
    "padding": "поле", "gap": "промежуток", "radius": "скругление", "stroke": "обводка",
    "With a style": "Со стилем", "Effect styles": "Стили эффектов", "Effects in styles": "Эффекты в стилях",
    "Drop shadow": "Внешняя тень", "Inner shadow": "Внутренняя тень", "Layer blur": "Размытие слоя", "Background blur": "Размытие фона",
    "No style has this effect. Add a style or use an existing one.": "Такого эффекта нет ни в одном стиле. Добавьте стиль или используйте существующий.",
    "The shadow or blur already matches a style exactly.": "Тень или размытие уже точно как в стиле.",
    "Offset or blur differ by a pixel or two.": "Смещение или размытие отличаются на пиксель-другой.",
    // images
    "Places": "Мест", "Repeated images": "Повторы", "Placeholders": "Заглушки",
    "One-off images are often placeholders or leftovers.": "Картинки в одном месте — часто заглушки или остатки.",
    "Each is placed 20 or more times. A component or a shared asset keeps every copy in sync.": "Каждая стоит 20 и больше раз. Компонент или общий ассет держит все копии одинаковыми.",
    "fill": "заливка", "fit": "вписать", "crop": "обрезка", "tile": "плитка", "stretch": "растянуть",
    // comments
    "Open": "Открытые", "No reply yet": "Без ответа", "Open over 30 days": "Открыты дольше 30 дней", "Resolved": "Закрытые",
    "Newest first": "Сначала новые", "Oldest first": "Сначала старые", "Longest without a reply": "Дольше всех без ответа",
    "Most replies": "Больше всего ответов", "Person": "Человек", "Everyone": "Все", "File": "Файл", "All files": "Все файлы",
    "Group by screen": "Группировать по экранам", "Find in comments": "Найти в комментариях", "Text, person, screen": "Текст, человек, экран",
    "Typical time to resolve": "Обычно закрывают за", "same day": "в тот же день", "waiting too long": "ждут слишком долго",
    "half of the threads close faster": "половина обсуждений закрывается быстрее",
    "Open questions without a single reply. Someone is waiting.": "Открытые вопросы без единого ответа. Кто-то ждёт.",
    "Open for more than 30 days: either done and forgotten, or blocked.": "Открыты дольше 30 дней: либо сделано и забыто, либо застряло.",
    "Screens with the most open threads: the design there is still unsettled.": "Экраны, где больше всего открытых обсуждений: там дизайн ещё не устоялся.",
    "No reply": "Без ответа", "Open, old": "Открыто давно", "Open thread": "Открыто", "Not pinned to a screen": "Не привязаны к экрану",
    "on the empty canvas or on a deleted layer": "на пустом холсте или на удалённом слое", "open": "открыто", "closed in": "закрыли за",
    "Comments are not loaded yet": "Комментарии ещё не загружены",
    "Stealer takes them from Figma on every update. One update is enough.": "Stealer забирает их из Figma при каждом обновлении. Достаточно одного.",
    "No threads match the current options.": "Под текущие параметры не подходит ни одно обсуждение.",
    // components
    "Sets and components": "Наборы и компоненты", "Overridden": "Переопределены", "of instances": "инстансов",
    "Unnamed layers": "Безымянные слои", "frames and groups like Frame 12": "фреймы и группы вроде Frame 12",
    "Possibly detached": "Возможно, отвязаны", "On an unusual surface": "На необычном фоне", "Component or set name": "Название компонента или набора",
    "All components": "Все компоненты", "Show previews": "Показывать превью",
    "Figma draws each variant. The first time takes a few seconds.": "Figma рисует каждый вариант. В первый раз это занимает несколько секунд.",
    "Components in use": "Компоненты в макетах", "Overridden instances": "Переопределённые инстансы",
    "Components on an unusual surface": "Компоненты на необычном фоне", "Not overridden": "Не переопределены",
    "Library": "Библиотека", "Local": "Локальный", "No variants": "Без вариантов", "Unusual": "Необычно", "Stands on": "Стоит на",
    "Frames named like a component but not instances. Re-link them so library updates reach them.": "Фреймы с названием компонента, но не инстансы. Перепривяжите, чтобы до них доходили обновления библиотеки.",
    "More than half of their instances are overridden. A missing variant is often the reason.": "Больше половины их инстансов переопределены. Часто не хватает варианта.",
    "Frame 12 or Group 7 placed by hand. Clear names help developers and search.": "Frame 12 или Group 7, положенные вручную. Понятные имена помогают разработке и поиску.",
    "Almost always on light (or dark), and in a few places not. Usually another variant is meant there.": "Почти всегда на светлом (или тёмном), а в нескольких местах — нет. Обычно там нужен другой вариант.",
    "Where it is worst · unnamed layers": "Где хуже всего · безымянные слои", "Nothing found": "Ничего не найдено",
    "No frames look like detached instances.": "Нет фреймов, похожих на отвязанные инстансы.",
    "All variants in use": "Все используемые варианты", "No variant with this combination is used in the selected files.": "Вариант с таким сочетанием в выбранных файлах не используется.",
    "This variant is used only inside other components, so Figma cannot draw it on its own.": "Этот вариант используется только внутри других компонентов, поэтому Figma не может нарисовать его отдельно.",
    "Figma is drawing the component…": "Figma рисует компонент…", "Figma could not draw this layer": "Figma не смогла нарисовать этот слой",
    "Auto layout": "Автолейаут", "Size": "Размер", "Position": "Положение", "Fill": "Заливка", "Font": "Шрифт",
    "Padding": "Поля", "Align": "Выравнивание", "Sizing": "Размеры", "Corner radius": "Скругление", "Effect": "Эффект",
    "Layers": "Слои", "Code": "Код", "Copy CSS": "Скопировать CSS", "Section": "Секция",
    // settings and dialogs
    "Interface language": "Язык интерфейса", "Figma access": "Доступ к Figma", "Token library": "Справочник токенов",
    "Updates": "Обновления", "Files downloaded at the same time": "Файлов загружается одновременно",
    "More is faster but closer to the Figma rate limit. 4 is a safe default.": "Больше — быстрее, но ближе к лимиту Figma. 4 — безопасное значение.",
    "Normally an update downloads only files and pages that changed. Use this if the data looks wrong.": "Обычно обновление скачивает только изменившиеся файлы и страницы. Используйте это, если данные выглядят неверно.",
    "Paste a new token to replace it": "Вставьте новый токен, чтобы заменить", "Replace": "Заменить", "Load": "Загрузить",
    "Figma access token": "Токен доступа Figma", "Figma file links": "Ссылки на файлы Figma", "Add and load": "Добавить и загрузить",
    "Add file": "Добавить файл", "Add a link to a Figma file.": "Добавьте ссылку на файл Figma.", "No files yet": "Файлов пока нет",
    "Paste the token first": "Сначала вставьте токен", "Files are not loaded yet": "Файлы ещё не загружены",
    "The links are added. Load the files from Figma to see the results.": "Ссылки добавлены. Загрузите файлы из Figma, чтобы увидеть результаты.",
    "Paste a link to a file. Stealer loads it and shows what follows the design system and what does not.": "Вставьте ссылку на файл. Stealer загрузит его и покажет, что сделано по дизайн-системе, а что мимо неё.",
    "Optional. Files can also be added later with + in the left panel.": "Необязательно. Файлы можно добавить и потом, кнопкой в левой панели.",
    "For example, ready or release. Separate several words with commas.": "Например, ready или release. Несколько слов — через запятую.",
    "For example, ready or release. Separate several words with commas. Can be changed later for each file.": "Например, ready или release. Несколько слов — через запятую. Потом можно поменять для каждого файла.",
    "Add a Figma access token to load the files": "Добавьте токен доступа Figma, чтобы загрузить файлы",
    "Choose a token library file": "Выберите файл справочника токенов",
    "Load the project’s token library, or use styles and variables in the files": "Загрузите справочник токенов проекта или используйте стили и переменные из файлов",
    "Server error": "Ошибка сервера", "Could not copy to the clipboard": "Не удалось скопировать в буфер обмена",
    "Update started": "Обновление запущено", "Done": "Готово",
    "Include this file": "Учитывать этот файл", "Show only this file": "Показать только этот файл", "Update this file": "Обновить этот файл",
    "More": "Ещё", "default filters": "фильтры по умолчанию", "on": "на", "Number of stops": "По числу стопов", "Most used in files": "Чаще в файлах",
    "No style": "Без стиля", "Searching…": "Ищу…", "fail": "не проходят", "texts": "текстов", "components": "компонентов",
    "“Onbaording” finds “Onboarding”; misspelled names in the files are found too": "«Onbaording» найдёт «Onboarding»; опечатки в самих макетах тоже найдутся",
    "“ghbdtn” finds “привет”, “knopka” finds “кнопка”, “онбординг” finds “onboarding”": "«ghbdtn» найдёт «привет», «knopka» — «кнопка», «онбординг» — «onboarding»",
    "“Bound” counts layers bound to the variable itself, matched by the variable key; “Typed by hand” counts the same value set without a variable.": "«Привязано» — слои, привязанные к самой переменной, по её ключу; «Вручную» — то же значение без переменной.",
    "Every font combination in text without a style.": "Каждое сочетание шрифта в тексте без стиля.",
    "Shadows and blurs set by hand, compared with effect styles inferred from the files.": "Тени и размытия, набранные вручную, против стилей эффектов, выведенных из файлов.",
    "One image in several places is one row, so repeats and leftover placeholders stand out.": "Одна картинка в нескольких местах — одна строка: повторы и забытые заглушки видно сразу.",
    "Discussions in the files with the screen each one is pinned to.": "Обсуждения в файлах с экраном, к которому каждое приколото.",
    "Open a thread to read it.": "Откройте обсуждение, чтобы прочитать.",
    "Open a row to filter by variant properties, see where they are used and on which surfaces.": "Откройте строку, чтобы отфильтровать по свойствам вариантов и увидеть, где и на каких фонах они стоят.",
    "The component almost always stands on light (or on dark), and in a few places it does not.": "Компонент почти всегда стоит на светлом (или на тёмном), а в нескольких местах — нет.",
    "Usually another variant is meant there.": "Обычно там нужен другой вариант.",
    "Open a row and pick the surface to see those places.": "Откройте строку и выберите фон, чтобы увидеть эти места.",
    "Frames and groups named like a component of the file but not instances.": "Фреймы и группы с названием компонента файла, но не инстансы.",
    "A detached instance keeps the component name.": "Отвязанный инстанс сохраняет название компонента.",
    "This is a hint, not a verdict: a regular frame can have the same name.": "Это подсказка, а не приговор: у обычного фрейма может быть такое же название.",
    "Looks the same as a token.": "На глаз не отличить от токена.", "Replace it with the token.": "Замените на токен.",
    "A token’s color with another opacity.": "Цвет токена с другой прозрачностью.",
    "Add a token with this opacity or use an existing one.": "Добавьте токен с такой прозрачностью или используйте существующий.",
    "Far from every token.": "Далеко от всех токенов.", "Add it to the system or replace it.": "Добавьте в систему или замените.",
    "Equal to a token but set by hand somewhere.": "Равен токену, но где-то набран вручную.",
    "Bind the variable: nothing changes visually.": "Привяжите переменную — на экране ничего не изменится.",
    "Used only a few times.": "Использован всего несколько раз.", "Often a typo or a leftover.": "Часто опечатка или остаток.",
    "Every text in the files.": "Все тексты макетов.", "The same text in different places is one row.": "Одинаковый текст в разных местах — одна строка.",
    "Connected.": "Подключено.", "Not connected.": "Не подключено.", "Not loaded.": "Не загружен.",
    "The token is stored only on this computer, in a file readable by your account only.": "Токен хранится только на этом компьютере, в файле, доступном только вашей учётной записи.",
    "Stealer cannot load files without a token.": "Без токена Stealer не может загрузить файлы.",
    "A link only says which file to read.": "Ссылка говорит только, какой файл читать.",
    "Figma gives the file’s data through its API only with a personal access token, the same way it checks your access when you open the file.": "Данные файла Figma отдаёт через API только по персональному токену — так же, как проверяет ваш доступ, когда вы открываете файл.",
    "Stealer reads files with your token; it never changes them.": "Stealer читает файлы с вашим токеном и никогда их не меняет.",
    "Create one in Figma: Settings → Security → Personal access tokens, with read access to file content and comments.": "Создайте его в Figma: Settings → Security → Personal access tokens, с правом чтения содержимого файлов и комментариев.",
    "The design system’s color tokens.": "Цветовые токены дизайн-системы.",
    "Stealer compares every color in the files with them to find near-token, off-system and unbound colors.": "Stealer сравнивает с ними каждый цвет в файлах и находит цвета почти как токен, вне системы и непривязанные.",
    "Each project has its own library.": "У каждого проекта свой справочник.",
    "W3C Design Tokens, Tokens Studio, a variables export or a CSV with name and value columns.": "W3C Design Tokens, Tokens Studio, выгрузка переменных или CSV с колонками имени и значения.",
    "Optional.": "Необязательно.", "Files can also be added later with + in the left panel.": "Файлы можно добавить и потом, в левой панели.",
    "The design system’s color tokens: W3C Design Tokens, Tokens Studio, a variables export or a CSV with name and value columns.": "Цветовые токены дизайн-системы: W3C Design Tokens, Tokens Studio, выгрузка переменных или CSV с колонками имени и значения.",
    "With it, Stealer finds colors outside the system.": "С ним Stealer находит цвета вне системы.",
    "For example, Mobile app": "Например, Мобильное приложение",
    "A link to a file, a page or a frame.": "Ссылка на файл, страницу или фрейм.", "The whole file is loaded; the filters decide what to count.": "Загружается весь файл, а что считать — решают фильтры.",
    "For example, ready or release.": "Например, ready или release.", "Separate several words with commas.": "Несколько слов — через запятую.",
    "Can be changed later for each file.": "Потом можно поменять для каждого файла.", "Paste at least one link": "Вставьте хотя бы одну ссылку",
    "English": "English", "Light": "Light", "Dark": "Dark",
  };

  // ---------------------------------------------------------------- phrases with numbers and names
  // $1, $2 are kept as they are: they hold numbers with Russian words already, or names.
  const R = [
    [/^(.+) bound in the files have no names$/, "Привязаны в файлах без имён: $1"],
    [/^(.+) bound in the files are missing from the library$/, "Привязаны в файлах, но нет в справочнике: $1"],
    [/^(.+) without a value in the library file$/, "Без значения в файле справочника: $1"],
    [/^Apply effect styles to (.+)$/, "Назначить стили эффектов: $1", true],
    [/^Apply text styles to (.+)$/, "Назначить текстовые стили: $1", true],
    [/^Apply styles to (.+)$/, "Назначить стили: $1", true],
    [/^Bind variables to (.+)$/, "Привязать к переменным: $1", true],
    [/^Bind (.+) where they are set by hand$/, "Привязать там, где набрано вручную: $1", true],
    [/^Check (.+) by eye$/, "Проверить глазами: $1", true],
    [/^Check (.+) on an unusual surface$/, "Проверить на необычном фоне: $1", true],
    [/^Check (.+) used once$/, "Проверить использованные один раз: $1", true],
    [/^Check (.+)$/, "Проверить: $1", true],
    [/^Close or move (.+)$/, "Закрыть или перенести: $1", true],
    [/^Consider variants for (.+)$/, "Подумать о вариантах: $1", true],
    [/^Fix the contrast of (.+)$/, "Исправить контраст: $1", true],
    [/^Keep (.+) in one place$/, "Держать в одном месте: $1", true],
    [/^Make (.+) reusable$/, "Сделать переиспользуемыми: $1", true],
    [/^Most discussed: (.+)$/, "Больше всего обсуждают: $1", true],
    [/^Rename (.+) with default names$/, "Переименовать слои с именами по умолчанию: $1", true],
    [/^Replace (.+) with the closest style$/, "Заменить ближайшим стилем: $1", true],
    [/^Replace (.+)$/, "Заменить: $1", true],
    [/^Reply to (.+) nobody answered$/, "Ответить, где никто не ответил: $1", true],
    [/^Resolve (.+)$/, "Разобрать: $1", true],
    [/^Review (.+) off the scale$/, "Проверить мимо шкалы: $1", true],
    [/^Review (.+) off the system$/, "Проверить вне системы: $1", true],
    [/^Review (.+)$/, "Проверить: $1", true],
    [/^Round (.+) to the scale$/, "Округлить до шкалы: $1", true],
    [/^Turn (.+) into styles$/, "Сделать стилями: $1", true],
    [/^Unify (.+) written in different ways$/, "Привести к одному написанию: $1", true],
    [/^They already equal a token but are set by hand in (.+) places?\. Nothing changes visually\.$/, "Они уже равны токену, но набраны вручную в $1 местах. На экране ничего не изменится."],
    [/^They look the same as a token \((.+)\)\. Swap them for the closest token\.$/, "На глаз не отличить от токена ($1). Замените на ближайший токен."],
    [/^A token’s color with another opacity \((.+)\)\. Add tokens with these opacities or use existing ones\.$/, "Цвет токена с другой прозрачностью ($1). Добавьте токены с такой прозрачностью или используйте существующие."],
    [/^Far from every token(?:, mostly (.+))?\. Add the needed ones to the system and replace the rest\.$/, (m, a) => `Далеко от всех токенов${a ? ", в основном " + a.replace(/[A-Z][a-z]+/g, (w) => D[w] || w) : ""}. Нужные добавьте в систему, остальные замените.`],
    [/^, mostly (.+)$/, ", в основном $1"],
    [/^Used once or twice\. Often a typo or a leftover\.$/, "Использован один-два раза. Часто опечатка или остаток."],
    [/^Used at most (.+) times\. Often a typo or a leftover\.$/, "Использован не больше $1 раз. Часто опечатка или остаток."],
    [/^since (.+)$/, "с $1"], [/^Updated (.+)$/, "Обновлено $1"], [/^loaded (.+)$/, "загружен $1"],
    [/^How it changed · (.+) since (.+)$/, "Как менялось · $1 с $2"],
    [/^Where it is worst · (.+)$/, "Где хуже всего · $1"],
    [/^(\d[\d\s.,]*) min ago$/, "$1 мин назад"], [/^(\d[\d\s.,]*) h ago$/, "$1 ч назад"],
    [/^on (.+)$/, (m, a) => "на " + (D[a] || a)], [/^of (.+) placed$/, "из $1"], [/^of (.+)$/, "из $1"], [/^by (.+)$/, "от $1"],
    [/^near (.+)$/, "почти $1"], [/^opacity (.+)$/, "прозрачность $1"], [/^off (.+)$/, "вне $1"],
    [/^([\d\s]+) with no reply$/, "$1 без ответа"], [/^([\d\s]+) resolved$/, "$1 закрыто"], [/^([\d\s]+) this week$/, "$1 за неделю"],
    [/^([\d\s]+) new$/, "$1 новых"], [/^([\d\s]+) open$/, "$1 открыто"], [/^last reply (.+)$/, "последний ответ $1"],
    [/^([\d\s,.%]+) of texts$/, "$1 текстов"], [/^on ([\d\s]+ .+)$/, "на $1"],
    [/^([\d\s]+) set by hand$/, "$1 вручную"], [/^([\d\s]+) fill$/, "$1 в заливках"], [/^([\d\s]+) of ([\d\s]+)$/, "$1 из $2"],
    [/^(.+) off the scale$/, "$1 мимо шкалы"], [/^([\d\s]+ .+) set by hand$/, "$1 вручную"],
    [/^(light|dark|image|gradient|partly on a plate|no background) (\d+%)$/, (m, a, b) => D[a] + " " + b],
    [/^(padding|gap|corner|stroke) (.+)$/, (m, a, b) => ({ padding: "поле", gap: "промежуток", corner: "угол", stroke: "обводка" }[a]) + " " + b],
    [/^Within a pixel of the scale, for example (.+)\.$/, "В пределах пикселя от шкалы, например $1."],
    [/^No (spacing|radius|stroke) variables in the files: compared with a (.+) grid \(and (.+)\)\.$/, (m, a, g, b) => `В файлах нет переменных для ${{ spacing: "отступов", radius: "скруглений", stroke: "обводок" }[a]}: сравнение с сеткой ${g} (и ${b}).`],
    [/^No (spacing|radius|stroke) variables in the files: compared with a (.+) grid\.$/, (m, a, g) => `В файлах нет переменных для ${{ spacing: "отступов", radius: "скруглений", stroke: "обводок" }[a]}: сравнение с сеткой ${g}.`],
    [/^No radius variables in the files: even values count as on the grid\.$/, "В файлах нет переменных для скруглений: чётные значения считаются по сетке."],
    [/^No stroke variables in the files: (.+) count as on the grid\.$/, (m, a) => `В файлах нет переменных для обводок: ${a.replace(" and ", " и ")} считаются по сетке.`],
    [/^Bound: (.+)$/, "Привязано: $1"], [/^Set by hand: (.+)$/, "Вручную: $1"],
    [/^Pills \(radius of half the side\): (.+)$/, "Пилюли (скругление в половину стороны): $1"],
    [/^With a style: (.+)$/, "Со стилем: $1"],
    [/^(.+) in (.+); (.+) used once\.$/, "$1 в $2; в одном месте — $3."],
    [/^(.+) in this collection, (.+)$/, "В этой коллекции $1, $2"], [/^(.+) in this collection$/, "В этой коллекции $1"],
    [/^The system is inferred from the files: (.+)$/, "Система выведена из файлов: $1"],
    [/^([\d\s]+ .+) changed$/, "изменено: $1"],
    [/^(.+), the first (.+) shown$/, "$1, показаны первые $2"],
    [/^also searched: (.+)$/, "ещё искалось: $1"],
    [/^([\d\s]+ \S+) on ([\d\s]+ \S+)$/, "$1 на $2"],
    [/^(https:\/\/\S+)\nOne link per line$/, "$1\nПо одной ссылке в строке"],
    [/^Add files to (.+)$/, "Добавить файлы в «$1»"], [/^([\d\s]+ .+) added$/, "Добавлено: $1"],
    [/^Text contrast$/, "Контраст текста"],
    [/^needs (.+)$/, "нужно $1"],
    [/^closest (.+)$/, "ближайший $1"],
    [/^size ([+−-].+)$/, "размер $1"],
    [/^blur (.+)$/, "размытие $1"], [/^spread (.+)$/, "разлёт $1"],
    [/^(Drop shadow|Inner shadow|Layer blur|Background blur)(.*)$/, (m, a, b) => D[a] + b],
    [/^(Linear|Radial|Angular|Diamond) · (.+)$/, (m, a, b) => D[a] + " · " + b],
    [/^(\d+) stops$/, (m, n) => `${n} ${form(+n, P.stop)}`],
    [/^up to (.+)$/, "до $1"],
    [/^(.+) inside instances$/, "$1 внутри инстансов"],
    [/^Add a Figma file to (.+)$/, "Добавьте файл Figma в «$1»"],
    [/^Token library for (.+)$/, "Справочник токенов «$1»"],
    [/^Reload all files of (.+) from scratch$/, "Загрузить все файлы «$1» заново"],
    [/^Delete the project “(.+)”\?(.*)$/, "Удалить проект «$1»?$2"],
    [/^The Figma token cannot read the comments of (.+)\. Create a token with read access to comments\.$/, "Токен Figma не может читать комментарии: $1. Создайте токен с правом чтения комментариев."],
    [/^(\d+) (days?|places?|uses?|screens?|files?|texts?|instances?|layers?|colors?|components?|tokens?|matches|match|pages?|variants?|images?|threads?|replies|reply|people|person|surfaces?|values?|gradients?|effects?)$/,
      (m, n, w) => `${n} ${plural(+n, w) || w}`],
  ];

  const SKIP = "code,.mono,.msg,.tmsg p,.path,[data-u],script,style,textarea,#projName";
  const LATIN = /[A-Za-z]{2}/;
  const missed = new Set();

  function phrase(s, isWhole = true) {
    if (Object.prototype.hasOwnProperty.call(D, s)) return D[s];
    const dot = s.match(/^([\s\S]*?)([.:…]?)$/);
    if (dot[2] && Object.prototype.hasOwnProperty.call(D, dot[1])) return D[dot[1]] + dot[2];
    for (const [rx, to, whole] of R) {
      if (whole && !isWhole) continue;
      if (rx.test(s)) return s.replace(rx, to);
    }
    return null;
  }
  /** One piece of text: whole, then by sentences, then by " · ". */
  function tr(s) {
    const m = s.match(/^(\s*)([\s\S]*?)(\s*)$/);
    const core = m[2].replace(/\s+/g, " ");
    if (!core || !LATIN.test(core) || /^#?[0-9A-F]{6}([0-9A-F]{2})?\b/i.test(core)) return s;
    let out = phrase(core);
    if (out == null) {
      const parts = core.split(/(?<=[.!?])\s+(?=[A-Z“"0-9])/);
      if (parts.length > 1) {
        const t = parts.map((p) => phrase(p) ?? bits(p));
        if (t.some((x, i) => x !== parts[i])) out = t.join(" ");
      }
    }
    if (out == null) {
      const b = bits(core);
      if (b !== core) out = b;
    }
    if (out == null) { if (!/[А-Яа-яЁё]/.test(core)) missed.add(core); return s; }
    return m[1] + out + m[3];
  }
  function bits(s) {
    if (!s.includes("·")) return s;
    // Pieces of a meta line often are names (labels of layers, files): only safe rules apply.
    return s.split(/(\s*·\s*)/).map((p) => (LATIN.test(p) && !p.includes("·") ? phrase(p.trim(), false) ?? p : p)).join("");
  }

  // One odd text must never stop the rest of the page from being translated.
  function safe(s) {
    try { return tr(s); } catch (e) { return s; }
  }

  function walk(root) {
    if (lang !== "ru" || !root) return;
    if (root.nodeType === 3) {
      const p = root.parentElement;
      if (p && !p.closest(SKIP)) { const v = safe(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; }
      return;
    }
    if (root.nodeType !== 1 || root.closest(SKIP)) return;
    const els = [root, ...root.querySelectorAll("[title],[placeholder],[aria-label]")];
    for (const el of els) {
      if (el.closest(SKIP)) continue;
      for (const a of ["title", "placeholder", "aria-label"]) {
        const v = el.getAttribute(a);
        if (v && LATIN.test(v)) { const t = safe(v); if (t !== v) el.setAttribute(a, t); }
      }
    }
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (w.nextNode()) nodes.push(w.currentNode);
    for (const n of nodes) {
      const p = n.parentElement;
      if (!p || p.closest(SKIP)) continue;
      const v = safe(n.nodeValue);
      if (v !== n.nodeValue) n.nodeValue = v;
    }
  }

  function start() {
    document.documentElement.lang = lang;
    if (lang !== "ru") return;
    walk(document.body);
    new MutationObserver((list) => {
      for (const m of list) {
        if (m.type === "characterData") walk(m.target);
        else for (const n of m.addedNodes) walk(n);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function setLang(v) {
    try { localStorage.setItem("coloro.lang", v); } catch (e) { /* optional */ }
    location.reload();
  }

  return { get lang() { return lang; }, plural, tr: (s) => (lang === "ru" ? tr(s) : s), months: () => MONTHS[lang], start, setLang, missed };
})();
