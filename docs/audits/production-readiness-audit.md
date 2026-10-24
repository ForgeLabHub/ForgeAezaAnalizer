# Аудит production-готовности Aéza Sentinel

Дата: 2026-10-24. Ветка: `feat/deployment-readiness` (HEAD `0225f12`).
Публичный стенд: `https://aeza-sentinel.pixel-minds.ru/`.

Документ фиксирует **только фактически проверенное**. Всё, что не удалось
проверить, помечено явно. Формулировки «работает» и «исправлено» используются
лишь там, где есть вывод команды или результат теста.

---

## 1. Итоговый статус

**PARTIALLY VERIFIED.**

Внешняя доступность, TLS, DNS, API, авторизация и основной пользовательский
сценарий на публичном стенде проверены и работают. Эксплуатационная часть
(автозапуск после перезагрузки ВМ, резервное копирование и восстановление,
права на файл SQLite, Nginx/systemd внутри сервера) **не проверялась**:
у агента нет SSH-доступа к production-ВМ. Из этого окружения есть только
исходящий HTTPS к публичному адресу.

Причина отсутствия доступа: в окружении агента нет ни `~/.ssh`, ни ключей, ни
конфигурации SSH, ни адреса/учётных данных сервера (проверено: `ls ~/.ssh` →
каталог отсутствует; поиск ключей по файловой системе ничего не нашёл).

---

## 2. Что проверено внешними средствами (с доказательствами)

| Проверка | Команда | Результат |
| --- | --- | --- |
| A-запись `aeza-sentinel.pixel-minds.ru` | `getent hosts` | `84.201.150.227` |
| A-запись `pixel-minds.ru` | `getent hosts` | `84.201.150.227` |
| `www.pixel-minds.ru` | `getent ahostsv4/v6` | записей нет |
| HTTPS главной | `curl -w '%{http_code} %{remote_ip} %{ssl_verify_result}'` | `200`, `84.201.150.227`, `0` (цепочка доверия валидна) |
| HTTP → HTTPS | `curl http://…` | `301` → `https://aeza-sentinel.pixel-minds.ru/` |
| Сертификат | `openssl s_client` + `x509 -ext subjectAltName` | `CN=pixel-minds.ru`, issuer `Let's Encrypt YE1`, срок `24.10.2026 – 22.01.2027`, SAN: `aeza-sentinel.pixel-minds.ru`, `pixel-minds.ru` |
| Веб-сервер | заголовок ответа | `Server: nginx/1.24.0 (Ubuntu)` |
| `/health` | `curl` | `200` |
| `/api/v1/docs` | `curl` | `200` |
| `/api/v1/openapi.json` | `curl` | `200`, title `Aéza Analyzer`, version `2.0.0`, 18 путей |
| `/api/v1/customers` | `curl` без токена | `401` |
| `/api/v1/analytics/summary` | без токена | `401` |
| `/api/v1/model/settings` | без токена | `401` |
| `/metrics` | без токена | `401` (защищён) |
| `/api/v1/source/snapshot` | без токена | `401` |
| Вход | `POST /api/v1/auth/login` c `analyst@aeza.test` | `200`, выдан JWT |
| Сводка | `GET /api/v1/analytics/summary` | 60 клиентов, 115 услуг, `revenueAtRisk` 1453.09 €, поколение 4 |
| Категории риска | из сводки | low 25, medium 13, high 8, insufficient_data 5, not_applicable 9 |
| Карточка клиента | `GET /api/v1/customers/1` | risk 50.0 medium, `revenueAtRisk` 0.32 €, 3 услуги, 3 причины, 2 рекомендации |
| Приоритеты | `GET /api/v1/priority?horizonDays=30` | `200` |
| Качество данных | `GET /api/v1/quality` | `200` |
| Сценарии | `POST /api/v1/scenarios/compare` | `200` |
| Экспорт | `GET /api/v1/export/customers.csv` | `200` |
| CORS | `OPTIONS` с чужим `Origin` | `Access-Control-Allow-Origin: *` |

### 2.1. Расхождение версий: production отстаёт от ветки

Набор путей в production OpenAPI (18) **совпадает** с `origin/main`. На ветке
`feat/priority-whatif-integration` и в текущей рабочей ветке добавлены
дополнительные маршруты, которых на стенде нет:

```
GET  /api/v1/customers/{id}/recommendations
PATCH /api/v1/customers/{id}/recommendations/{code}
```

Проверка на стенде: `GET /api/v1/customers/1/recommendations` → `{"detail":"Not Found"}`.

Это не дефект стенда, а факт: **Retention Playbooks ещё не развёрнуты**.
Пункт «статус рекомендации сохраняется после перезагрузки» на публичном стенде
поэтому проверить нельзя — функциональность там отсутствует. Локально она
покрыта тестами (`backend/tests/test_playbooks.py`, 14 тестов).

---

## 3. Что исправлено в этой итерации (с доказательствами)

### 3.1. Потоковый экспорт CSV: пик памяти 3.55 GiB → 51.5 MiB

**Файл:** `backend/app/api/routes_export.py`.

Было: весь отбор собирался в `io.StringIO` до отправки. Измерение прошлой
итерации на 50 000 клиентов: ~40 с и ~3.55 GiB резидентной памяти.

Стало: страницы читаются и записываются в ответ по мере поступления.

Замер на реальном Docker-стеке (50 000 клиентов, `pageSize=500`, cgroup
`memory.current`, опрос каждые 10 мс):

```
base=186.1MiB peak=237.6MiB after=223.9MiB delta_peak=51.5MiB elapsed=23.87s
x-export-rows: 50000
x-export-generation: 6
rows: 50001 (заголовок + 50 000)
```

Пик ограничен одной страницей. **Дефект памяти подтверждённо устранён.**

Дополнительно устранён регресс, внесённый при переходе на потоковый режим:
`X-Export-Rows` брался из общей сводки и показывал число клиентов всей базы
вместо числа строк выборки. Теперь это `total` отфильтрованного набора, а
страницы прибиты к одному поколению (`X-Export-Generation`), поэтому
пересчёт в середине выгрузки не склеит два снимка.

### 3.2. Гонка при первом изменении статуса рекомендации

**Файл:** `backend/app/storage.py`, метод `set_recommendation_status`.

Было: «прочитать-и-вставить» внутри транзакции. При двух одновременных первых
записях для одной пары `(customer, code)` обе не находили строку, обе вставляли,
одна падала с нарушением уникальности (500). Воспроизводилось 12 параллельными
первыми записями: 1 из 12 → 500.

Стало: `INSERT … ON CONFLICT DO UPDATE` для SQLite и PostgreSQL, с переносимым
резервным путём для прочих диалектов. Проверка: 20 параллельных первых записей
→ 20 успешных.

### 3.3. Новые регрессионные тесты

**Файл:** `backend/tests/test_insights.py`, +6 тестов:

- тело файла совпадает со списком клиентов API;
- `X-Export-Rows` равен размеру **отфильтрованной** выборки;
- постраничная выгрузка не теряет и не дублирует строки (`pageSize` 1/2/3);
- ответ действительно потоковый (нет `Content-Length`);
- экспорт требует авторизации.

---

## 4. Таблица проблем P0/P1/P2

### P0 — блокирует эксплуатацию

| Проблема | Доказательство | Причина | Исправление | Риск изменения |
| --- | --- | --- | --- | --- |
| Нет подтверждённого доступа к серверу у агента | `ls ~/.ssh` пусто, ключей нет | окружение агента изолировано | владельцу выполнить команды из §7 | нет |
| Права на SQLite (`readonly database`) | сообщение владельца, **не воспроизведено** — нет доступа | предполагаемо права каталога/файла под пользователем процесса | проверить по §7.3 | низкий при точечном `chown` |

Блокирующих проблем **самого приложения** на публичном стенде не обнаружено:
сайт открывается, TLS валиден, вход работает, API отвечает.

### P1 — важные

| Проблема | Доказательство | Исправление | Риск |
| --- | --- | --- | --- |
| Автозапуск после перезагрузки ВМ не проверен | нет SSH | проверить `systemctl is-enabled` / `restart: unless-stopped` (§7.1) | нет |
| Резервное копирование не подтверждено | нет SSH | проверить по §7.4 | нет |
| Отсутствуют заголовки безопасности | `curl -D-` вернул только `Server` | добавить HSTS, `X-Content-Type-Options`, `X-Frame-Options`, CSP в Nginx (§7.5) | низкий |
| `Access-Control-Allow-Origin: *` | OPTIONS-запрос | сузить до домена стенда | средний (сломает чужой origin, если он используется) |
| Экспорт CSV 50k ≈ 24 с | замер | приемлемо для аналитика; при росте — вынести в фон | нет |
| Production отстаёт от ветки | сравнение OpenAPI | решить, разворачивать ли Playbooks | средний |

### P2 — улучшения

| Проблема | Доказательство | Комментарий |
| --- | --- | --- |
| `/api/v1/docs` публично | `200` без токена | оценено: даёт только схему, не данные; решение за владельцем |
| `/ready` проксируется в SPA | вернул HTML, не JSON | добавить `location = /ready` в Nginx |
| Пересчёт всей базы на каждый запрос | профилирование | узкое место при росте; кеш не внедрён без подтверждения |
| Экспорт пересчитывает `count(*)` на каждой странице | профиль: `count(*)` 0.037 с × 100 страниц | вынести в один запрос |

---

## 5. Методика и результаты измерений

Окружение: 4 vCPU, 15.6 GiB RAM, Docker 27, PostgreSQL 16, API `uvicorn`
(1 процесс), Nginx 1.27. Профиль данных: синтетический стресс-набор,
50 000 аккаунтов / 200 000 услуг / ~300 000 транзакций (сгенерирован
`backend/scripts/generate_load_profile.py`, схема и инварианты как у
организаторского набора; реальные персональные данные не использовались).

### 5.1. Задержки чтения (локальный стек)

| Сценарий | c | RPS | p50, мс | p95, мс | p99, мс | ошибки |
| --- | --- | --- | --- | --- | --- | --- |
| read | 4 | 94.6 | 22.7 | 87.3 | 306.5 | 0 |
| read | 16 | 119.4 | 116.3 | 211.4 | 241.7 | 0 |
| read | 32 | 115.1 | 257.6 | 356.2 | 372.0 | 0 |

Наблюдение: пропускная способность выходит на плато ~115–120 rps и не растёт
при увеличении параллелизма с 16 до 32, а задержка растёт линейно. Это
признак насыщения одного процесса API — соответствует одному воркеру
`uvicorn` и синхронной пересборке ответов.

### 5.2. Стоимость страниц и экспорта (50k)

| Операция | Время |
| --- | --- |
| `count(*)` | 0.037 с |
| 500 строк + сортировка | 1.32 с |
| 5 000 строк | 1.76 с |
| 50 000 строк | 19.0 с |
| загрузка всех 50 000 ORM-объектов | 17.2 с |
| выборка 50 000 `payload` без ORM | 16.9 с |
| экспорт CSV потоком | 23.9 с, пик +51.5 MiB |

Основная стоимость — десериализация 50 000 JSON-`payload` (~23 КБ каждый);
размер таблицы `analyzer_customers` — 298 МБ. Это не N+1 и не нехватка
индексов (индексы по `generation, risk_score/balance/email/total_replenished`
присутствуют).

### 5.3. Ограничения измерений

- Синтетический набор, а не реальная база; выводы о масштабировании — оценка,
  а не гарантия.
- Один процесс API; поведение нескольких воркеров не измерялось.
- `docker stats` при замерах под нагрузкой приводил к перезапуску окружения
  агента; серии на 32 потоках повторялись ограниченно.

---

## 6. Состояние тестов

| Набор | Команда | Результат |
| --- | --- | --- |
| backend | `.venv/bin/python -m pytest backend/tests -q` | **201 passed**, 0 failed, ~33 с |
| root (часть A + auth) | `.venv/bin/python -m pytest tests -q` | **69 passed**, 0 failed, ~16 с |
| frontend typecheck+build | `npm run build` (`tsc -b && vite build`) | см. `docs/audits/sentinel-implementation-report.md` |

Итого 270 backend-тестов проходят. Для root-набора требуется `PyJWT[crypto]`
(объявлен в корневом `requirements.txt`); без него сбор падает на
`ModuleNotFoundError: No module named 'jwt'` — это отсутствие зависимости в
окружении, а не дефект кода.

---

## 7. Действия владельца (нет доступа к серверу)

Команды ниже **не выполнялись**. Их нужно запустить на ВМ.

### 7.1. Автозапуск после перезагрузки

```bash
systemctl is-enabled docker nginx            # ожидаем: enabled
cd <каталог проекта> && sudo docker compose ps   # политика restart: unless-stopped
sudo docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $(sudo docker compose ps -q api)
```

### 7.2. Порты и конфликт Nginx

```bash
sudo ss -lntp | grep -E ':(80|443|8000|8080)\b'
sudo nginx -t
grep -R "server_name\|proxy_pass" /etc/nginx/sites-enabled/
```

### 7.3. Права SQLite (ошибка `readonly database`)

```bash
cd <каталог проекта>
ls -la db/ db/auth.sqlite3
ps -o user= -p $(pgrep -f 'uvicorn main:app' | head -1)
# точечно, под фактического пользователя процесса:
sudo chown <user>:<group> db/auth.sqlite3
sudo chmod 664 db/auth.sqlite3
sudo chown <user>:<group> db            # каталог: нужен для -wal/-shm
```

Не использовать `chmod -R 777`, не удалять файл, не пересоздавать базу.

### 7.4. Резервная копия и проверка восстановления

```bash
mkdir -p ~/aeza-backup && chmod 700 ~/aeza-backup
# Согласованная копия SQLite (учитывает WAL):
sudo docker compose exec -T api python - <<'PY'
import sqlite3
src = sqlite3.connect('/app/db/auth.sqlite3')
dst = sqlite3.connect('/tmp/auth.backup.sqlite3')
src.backup(dst); dst.close(); src.close()
print('ok')
PY
sudo docker compose cp api:/tmp/auth.backup.sqlite3 ~/aeza-backup/auth-$(date +%F).sqlite3
sqlite3 ~/aeza-backup/auth-$(date +%F).sqlite3 'PRAGMA integrity_check;'   # ожидаем: ok
# Проверка восстановления — в отдельный каталог, не поверх рабочей базы:
mkdir -p /tmp/restore-test && cp ~/aeza-backup/auth-*.sqlite3 /tmp/restore-test/
```

### 7.5. Заголовки безопасности в Nginx

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
location = /ready { proxy_pass http://aeza_api/ready; }
```

После правки: `sudo nginx -t && sudo systemctl reload nginx`.

---

## 8. Git

- Ветка: `feat/deployment-readiness`, HEAD `0225f12`, не запушена.
- Изменено в этой итерации: `backend/app/api/routes_export.py`,
  `backend/app/storage.py`, `backend/tests/test_insights.py`.
- Новое: `backend/scripts/generate_load_profile.py`, `backend/scripts/loadtest.py`,
  этот документ.
- `db/auth.sqlite3` изменён запуском приложения (runtime-состояние) и **не
  коммитится**; `-wal`/`-shm` также не коммитятся.
- `main` не изменялся. Push не выполнялся.

---

## 9. Открытые вопросы

1. Есть ли у владельца SSH-доступ, который можно передать агенту, или
   эксплуатационные проверки остаются за владельцем?
2. Нужно ли разворачивать Playbooks (`/recommendations`) на стенде?
3. Кто владеет DNS `pixel-minds.ru` (A-записи сейчас корректны, менять нечего)?
4. Каков целевой SLA и ожидаемое число клиентов для выбора конфигурации сервера?
