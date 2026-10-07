# hh-bot

Полуавтомат для откликов на hh.ru: собирает вакансии, пишет письма по фактам
из резюме, готовит форму в твоём браузере. Кнопку отправки нажимаешь ты.

## Установка
    python3 -m pip install -r requirements.txt
    python3 -m playwright install chromium
    cp .env.example .env   # вставить REQUESTY_API_KEY

## Использование
    python3 bot.py login                      # один раз, вход делаешь сам
    python3 bot.py collect "<URL поиска hh>"  # собрать вакансии
    python3 bot.py draft                      # написать письма
    python3 bot.py review                     # просмотр и отклик по одной

`check-selectors` запусти дважды: на URL поиска и на URL вакансии (селекторы живут на разных страницах).
URL поиска передавай без параметра `page=`.

Лимит 15 откликов в день. При капче бот останавливается и ждёт тебя.
Сломалась вёрстка: `python3 bot.py check-selectors <url>` и правка `SEL` в bot.py.
Перед отправкой читай письмо: модель может приукрасить, предупреждения
проверки показываются над текстом. Файл `resume_facts.md` держи без контактов.
