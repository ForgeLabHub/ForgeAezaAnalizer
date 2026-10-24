# Консолидация в `main`

Дата: 2026-10-24. Ветка: `main`. Каждое утверждение подтверждено командой.

---

## A. Итоговый Git

| Показатель | Значение |
| --- | --- |
| Текущая ветка | `main` |
| HEAD | `089da76` |
| `main` относительно `origin/main` | **29 впереди, 0 позади** |
| Рабочее дерево | 14 незакоммиченных файлов — **принадлежат параллельному агенту**, см. ниже |
| Push | **заблокирован** (403), см. §F |

### Что было при инвентаризации (не совпало с предыдущим отчётом)

Предыдущий аудит утверждал, что локальный `main` на 14 коммитов **впереди**
`origin/main`. Фактически:

- `main` был на **4 коммита позади** `origin/main`;
- коммита `fe554bc` в репозитории нет вовсе;
- рабочее дерево было **чистым** — незакоммиченных изменений параллельного
  агента на момент старта не существовало, он их уже закоммитил.

### Коммиты, добавленные в этой сессии

```
089da76  Compute the per-renewal figures on the money slide
2305e97  Rebuild the defence decks from the engine and recapture their screenshots
e10f43c  Merge feat/deployment-readiness into main
```

---

## B. Консолидация

### Стратегия

1. Сначала `git fetch origin` (только чтение).
2. Сохранены ссылки и бандлы всех трёх состояний в `/tmp/aeza_premerge/`
   (`readiness.bundle`, `main.bundle`, `refs.txt`) — без секретов.
3. `main` переведён на `origin/main` через `--ff-only` (без потери истории).
4. Ветка слита через `--no-ff`; конфликтов не было (`git merge-tree` → exit 0).
5. Перед коммитом вручную проверено, что обе стороны на месте.

### Что вошло в `main`

| Источник | Содержимое |
| --- | --- |
| `origin/main` | анимированный логотип Aeza (`AezaLogo.tsx` вместо `AezaLogoDropdown.tsx`), правки `LoginPage`, `styles.css` |
| `feat/deployment-readiness` | потоковый экспорт CSV, guard deprecated-фактора, живое обновление, `/ready`, security headers, фавиконка Aeza, OpenAPI, аудиты, hardening аутентификации (лимитер входа, безопасный дефолт секрета, CORS) |
| эта сессия | пересборка презентации из движка + переснятые скриншоты + тесты-стражи |

### Ручное разрешение

Автоматического слияния хватило, но результат проверен вручную, потому что обе
стороны трогали `App.tsx` и `styles.css`:

- `App.tsx` содержит **и** `AezaLogo` (от `origin/main`), **и** маршруты
  `ActionCenterPage` / `WhatIfPage` (наши) — проверено `grep`;
- `styles.css` — 1606 строк, обе группы правил сохранены.

### Потерянные файлы

Три файла отсутствуют в результате, все — намеренно:

| Файл | Причина |
| --- | --- |
| `db/auth.sqlite3` | runtime-хранилище сессий; убрано из индекса и добавлено в `.gitignore` |
| `frontend/public/favicon.svg` | заменено оригинальными иконками Aeza (`favicon.png`, `favicon.ico`, `apple-touch-icon.png`) |
| `frontend/src/components/AezaLogoDropdown.tsx` | заменено на `AezaLogo.tsx` коммитом `81e28c4` из `origin/main` |

Ничего не потеряно ни из `origin/main`, ни из `feat/deployment-readiness`
(проверено `comm -23` по спискам файлов обоих родителей).

### Что осталось вне `main`

14 незакоммиченных файлов **параллельного агента** — новая AI-функция:
`backend/app/api/routes_ai.py`, `backend/app/domain/llm.py`,
`backend/tests/test_llm.py`, `frontend/src/components/AiPanel.tsx` и правки
`config.py`, `main.py`, `openapi.json`, `docker-compose.yml`, `README.md`,
`.env.example`, `frontend/src/{lib/api.ts,types.ts,styles.css}`,
`CustomerDetailPage.tsx`.

**Я их не трогал и не коммитил.** Авторство и порядок согласования неизвестны,
а правила задачи прямо запрещают коммитить чужую работу от чужого имени.
Они остаются в рабочем дереве нетронутыми.

---

## C. Контрольные значения

Воспроизведены запуском движка (`backend/app/domain/module.py:create`) на
`dataset/data.json` при `AS_OF = 2026-10-19T15:00:00Z`:

| Показатель | Значение |
| --- | --- |
| Веса | `expiry_proximity 3.0`, `auto_prolong_disabled 2.0`, `insufficient_balance 2.0`, `prolong_wait_status 2.5`, `failed_renewals 0.0`, `suspended_status 1.0`, `renewal_failure_rate 2.5` |
| Сумма весов | **13.0** |
| Клиент №10 | **71.4**, категория `high` |
| `revenueAtRisk` | **5.80 €** (580 центов) |
| Предстоящие продления | 17,03 € |
| Категории | low 0, medium 3, high 3, not_applicable 4 |
| После веса 9.0 | клиент №10 → 81.8, сумма весов 19.0, выручка 7,72 € |

`failed_renewals` в расчёт не входит (вес 0, `deprecated`). API теперь
**отклоняет** ненулевой вес этого фактора: `PATCH` с `failed_renewals: 2.0` →
422, с `0.0` → 200 (проверено).

---

## D. Презентация

### Файлы

- `docs/deck/values.py` — **новый**: считает все числа через движок;
- `docs/deck/build_deck.py` — читает из `values.py` вместо литералов;
- `docs/deck/shots/*.png` — **пересняты** (10 файлов) с локального стенда на
  официальном наборе;
- `aeza_hackathon_osen_2026.pptx`, `aeza_umirhack_defense.pptx` — пересобраны;
- `docs/deck/README.md` — описан новый источник чисел;
- `backend/tests/test_deck_values.py` — **новый**: страж против расхождения.

### Устаревшие числа

Удалены и заменены вычисляемыми: `73,3`, `5,74`, `7,48`, `81,0`, `15,0`,
`21,0`, `11,0`, `0,32/0,77/1,57/3,08`.

Проверка содержимого обоих `.pptx`:

```
aeza_hackathon_osen_2026.pptx STALE: none | FRESH: ['0,36','2,93','5,80','7,72','71,4','81,8']
aeza_umirhack_defense.pptx    STALE: none | FRESH: ['0,36','2,93','5,80','7,72','71,4','81,8']
```

Попутно исправлена **причина**, а не только следствие: график вкладов
перечислял `failed_renewals` с весом 2.0 и не показывал
`renewal_failure_rate`. Теперь список строится из `FACTORS` движка.

### Визуальная проверка

| Инструмент | Результат |
| --- | --- |
| `validate.py` | `clean: no geometry problems` |
| `qa_visual.py` | `no visual QA issues`; контраст текста 4.75–18.58:1 (порог 4.5/3.0) |
| Разрешение скриншотов | 133–2371 px/in, обрезанного текста нет |

PDF не перегенерированы: `libreoffice`/`soffice` в окружении отсутствуют.
Команда для владельца:

```bash
soffice --headless --convert-to pdf aeza_umirhack_defense.pptx aeza_hackathon_osen_2026.pptx
```

---

## E. Проверки

| Команда | Результат | Код |
| --- | --- | --- |
| `.venv/bin/python -m pytest backend/tests tests -q` | **308 passed** | 0 |
| `.venv/bin/python -m pytest backend/tests -q` (с WIP агента) | 239 passed | 0 |
| `.venv/bin/python -m pytest backend/tests/test_deck_values.py -q` | 4 passed | 0 |
| `cd frontend && npx tsc -b` | без ошибок | 0 |
| `cd frontend && npm run build` | 10 файлов, 225.26 kB JS | 0 |
| `.venv/bin/python backend/scripts/check_docs.py` | 4/4 ok | 0 |
| `sudo docker compose config` | 3 сервиса, валидно | 0 |
| `docs/deck/validate.py` | геометрия чистая | 0 |
| `docs/deck/qa_visual.py` | замечаний нет | 0 |
| Воспроизведение контрольных значений | 13.0 / 71.4 / 5.80 € | 0 |
| `git ls-files db/` | только `analytics_seed.sql`, `schema.sql` | 0 |
| Секреты в diff | не найдены | 0 |

Скачок с 279 до 308 тестов: +25 тестов параллельного агента (hardening, LLM),
+4 моих теста презентации.

---

## F. Публикация и production

| Действие | Статус |
| --- | --- |
| Push | **заблокирован**: `remote: Permission to Pixelminds-hub/aeza-analizer.git denied to Pavel1778` → 403 |
| Деплой | **не выполнялся** |

Токен принадлежит `Pavel1778`. GitHub API сообщает `permissions.push: true`, но
фактическая запись отклоняется — это fine-grained token без `contents: write`
на этот репозиторий. `push: true` в API **не является** доказательством права
записи.

### Команда публикации для владельца

Требуется токен с доступом `Contents: Read and write` на
`Pixelminds-hub/aeza-analizer`.

```bash
cd /workspace/project/471010cbdc59450fa46d59f13f633d76
git log --oneline origin/main..main        # 29 коммитов к отправке
git push https://<TOKEN>@github.com/Pixelminds-hub/aeza-analizer.git main
```

Перед push должны пройти: `pytest backend/tests tests -q` (308), `npm run build`,
`check_docs.py` (4/4). Все три пройдены на `089da76`.

Альтернатива без токена — передать бандл:

```bash
git bundle create /tmp/aeza-main.bundle main
# на машине с доступом:
git fetch /tmp/aeza-main.bundle main:refs/heads/main
```

### Что осталось проверить на сервере

1. Автозапуск после перезагрузки ВМ.
2. Резервное копирование и **проверенное** восстановление.
3. Права на файл и каталог SQLite (ошибка `readonly database`).
4. Nginx изнутри: `/ready`, заголовки безопасности, сужение CORS.
5. Какой набор данных обслуживает стенд: `db/analytics_seed.sql` сеет
   **60/115/285**, а не официальные 10/30/100 — контрольные значения 71.4 /
   5.80 € на стенде **не появятся**, пока туда не загружен `dataset/data.json`.

Команды — в `docs/audits/production-readiness-audit.md` §7 и
`docs/audits/release-gate.md` §5–6.

---

## G. Следующие действия владельца

1. **Токен с `contents: write`** либо перенос бандла — иначе 29 коммитов
   существуют только локально.
2. **Решить судьбу AI-функции** параллельного агента: 14 файлов не закоммичены.
   Нужно либо довести и закоммитить, либо откатить.
3. **Выбрать набор данных для защиты**: официальный 10/30/100 (даёт 71.4 /
   5.80 €, совпадает с презентацией) или расширенный 60/115/285. Смешивать
   нельзя — именно это и создало прежнее расхождение.
4. **Перегенерировать PDF** презентаций (`soffice`, см. §D).
5. Заполнить слайды 1 и 11: название команды, участники, контакты, QR-коды.

---

## Формулировка о балансах (Этап F)

ТЗ говорит: «Панель показывает, сколько бизнес может потерять, **с учётом
стоимости услуг, балансов аккаунтов и риска**».

Фактическая формула: `revenue_at_risk = price × score/100`. Баланс **не
входит** в денежную сумму напрямую; он влияет на **риск** через фактор
`insufficient_balance`, который и определяет `score`.

Это осознанное решение и оно задокументировано в
`docs/DATA_AND_RISK_MODEL.md` (§5, §7) и в заметках к слайду 6: «Баланс
203,79 € и пополнения 4 206,69 € — это не потерянные деньги. Мы держим три
величины раздельно». Формулу я **не менял**: сумма балансов не равна потерянной
выручке, а ТЗ не требует складывать их буквально.

Неоднозначность формулировки стоит проговорить на защите: баланс учтён как
**сигнал риска**, а не как слагаемое экспозиции.
