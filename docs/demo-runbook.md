# Demo runbook — команди по порядку

Операторська шпаргалка для живої демонстрації: що запускати, в якому порядку
і що казати на кожному кроці. Обґрунтування й контракти — у
[`defence-checklist.md`](defence-checklist.md), [`tool-contracts.md`](tool-contracts.md)
і [`design-rationale.md`](design-rationale.md).

Копіюй по одному блоку. Усе запускається з кореня репозиторію.

---

## 0. Підготовка (до шерингу екрана)

```
rm -f demo-vault/Decisions/*.md
```

Обсидіан на `demo-vault`, плагін увімкнений. Закрий усе, де видно `.env`.

---

## 1. Сервер сам по собі — доказ окремого процесу

```
uv run funnel-calibrator
```

Мовчить. Кажеш: «MCP-сервер по stdio мовчить, доки клієнт не заговорить». Потім **control-D**. Зупиняється `control-D` — закритий канал, як у справжнього хоста. На `control-C` цей сервер не реагує.

---

## 2. Інструменти без агента

```
npx @modelcontextprotocol/inspector uv run funnel-calibrator
```

У браузері: Connect → Tools → `measure_sku_funnel` → **Output Schema** (20 полів). Закрий вкладку.

---

## 3. Показуєш вхідну нотатку

Відкрий в Обсидіані `Objective.md`.
Кажеш: «це вхід у потік, а не місце для виходу».

---

## 4. Повний прогін — головна частина

```
uv run python agent/run_agent.py
```

Тицяєш у `MCP connections discovered` → обидва `connected`.
Потім у перший виклик `vault_read`.
Наприкінці показуєш нову нотатку в Обсидіані.

---

## 5. Товари не зашиті в код

```
grep -n "21-154" agent/run_agent.py
```

Порожньо.

---

## 6. Збій чужого сервера

Вимкни плагін в Обсидіані, потім:

```
uv run python agent/run_agent.py
```

Покаже `Connection refused` з назвою адреси.
**Увімкни плагін назад.**

---

## 7. Невалідний вхід → помилка

```
uv run python -c "from funnel_calibrator import server as s; s.measure_sku_funnel('21-999')"
```

---

## 8. Порожньо ≠ помилка (це успіх)

```
uv run python -c "import json; from funnel_calibrator import server as s; print(json.dumps(s.measure_sku_funnel('21-253', window_from='2026-06-01', window_to='2026-06-02'), indent=1))"
```

`resolved_orders: 0`, `reliability: insufficient`, ставки `null`.

---

## 9. Змінений валідний вхід

```
uv run python -c "from funnel_calibrator import server as s; [print(d, s.measure_sku_funnel('21-183', maturity_days=d)['resolved_orders']) for d in (0, 21, 45)]"
```

---

## 10. Простежити $1.61 до джерела

```
uv run python -c "import json; o=json.load(open('data/snapshot.json'))['orders']; m=[r for r in o if r['sku']=='21-154' and r['created_at']<='2026-08-03']; print('bought out', sum(1 for r in m if r['status_id']==12)); print('refused', sum(1 for r in m if r['status_id'] in (28,32,35))); print(json.dumps([r for r in m if r['status_id']==12][0], ensure_ascii=False))"
```

Дає `43` і `52` — чисельник і знаменник викупу 45.3%.

---

# Якщо часу мало

Обов'язкові: **1, 2, 4, 6**. Решта — на запит викладача.

---

# Головні цифри

| | |
|---|---|
| 21-154 | платили **$1.63** при беззбитковості **$1.61** → −$0.02 на лід |
| 21-197 | апрув упав до 31.6%, але вибірка 31 → `low`, висновок попередній |
| 21-253 | економіка **краща** за прийняту (+10.9%), $6.00 — це аукціон, а не товар |

Апрув/викуп прийняті: **65% / 52.5%**. Виміряні: 59.0/45.3 · 31.6/67.7 · 66.2/55.8.

---

# Якщо впаде авторизація

`Failed to authenticate: OAuth session expired` — це **не** код.
Обидва MCP-сервери в цей момент уже підключені, видно рядком вище.
Лікується `claude auth login` (окремим рядком!).
Inspector працює **без авторизації взагалі** — демо можна дотягнути на ньому.
