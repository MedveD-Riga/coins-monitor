"""
Мониторинг цен и ассортимента монет на rns.lv с уведомлениями в Telegram.

Запуск:
    python monitor.py test   - проверка: шлёт тестовое сообщение и показывает, сколько товаров найдено
    python monitor.py        - постоянная работа (проверка каждые INTERVAL_MIN минут)
"""
import json
import os
import re
import sys
import time
import traceback

import requests
from bs4 import BeautifulSoup

# ====== НАСТРОЙКИ: вставьте свои значения между кавычками ======
TG_TOKEN = os.environ.get("TG_TOKEN") or "ВСТАВЬТЕ_ТОКЕН_СЮДА"
TG_CHAT = os.environ.get("TG_CHAT") or "ВСТАВЬТЕ_CHAT_ID_СЮДА"
INTERVAL_MIN = 10  # как часто проверять сайт (в минутах)
# ===============================================================

URLS = [
    "https://rns.lv/monetas/latvijas-monetas/1992-2013?limit=100",
    "https://rns.lv/monetas/latvijas-monetas/1992-2013?limit=100&page=2",
    "https://rns.lv/monetas/latvijas-monetas/apgrozibas-1-lata-monetas?limit=100",
    "https://rns.lv/monetas/latvijas-monetas/1922-1939?limit=100",
]

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal price monitor)"}

KODS_RE = re.compile(r"Preces\s*kods", re.I)
SKU_RE = re.compile(r"Preces\s*kods\s*:?\s*(\S+)", re.I)
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*€")


def notify(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": text},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        print("Не удалось отправить сообщение в Telegram:", e)


def scrape():
    items = {}
    for url in URLS:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        before = len(items)
        for node in soup.find_all(string=KODS_RE):
            # поднимаемся вверх до карточки товара: в ней есть цена, один код и ссылка
            box = node.parent
            while box is not None:
                text = box.get_text(" ", strip=True)
                if (
                    SKU_RE.search(text)
                    and PRICE_RE.search(text)
                    and len(KODS_RE.findall(text)) == 1
                    and box.find("a", href=True)
                ):
                    break
                box = box.parent
            if box is None:
                continue
            text = box.get_text(" ", strip=True)
            sku = SKU_RE.search(text).group(1)
            link = next(
                (a for a in box.find_all("a", href=True) if a.get_text(strip=True)),
                None,
            )
            items[sku] = {
                "name": link.get_text(strip=True) if link else sku,
                "price": PRICE_RE.search(text).group(1),
                "url": link["href"] if link else url,
            }
        print(
            f"  ...{url[-40:]}: код ответа {resp.status_code}, "
            f"размер страницы {len(html)}, найдено товаров {len(items) - before}"
        )
        if len(items) == before:
            # ничего не нашли: сохраняем страницу, чтобы можно было разобраться
            with open(os.path.join(HERE, "debug.html"), "w", encoding="utf-8") as f:
                f.write(html)
        time.sleep(2)  # небольшая пауза, чтобы не нагружать сайт
    return items


def check():
    new = scrape()
    if not new:
        print("Товары не найдены (сайт недоступен или изменилась вёрстка). Пропускаю.")
        return
    try:
        with open(STATE, encoding="utf-8") as f:
            old = json.load(f)
    except FileNotFoundError:
        old = None

    if old is None:
        notify(f"✅ Мониторинг запущен. Найдено товаров: {len(new)}")
    else:
        for k, v in new.items():
            if k not in old:
                notify(f"🆕 Новый товар: {v['name']} — {v['price']}€\n{v['url']}")
            elif old[k]["price"] != v["price"]:
                notify(
                    f"💰 {v['name']}: {old[k]['price']}€ → {v['price']}€\n{v['url']}"
                )
        for k, v in old.items():
            if k not in new:
                notify(f"❌ Пропал товар: {v['name']} ({v['price']}€)")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print(time.strftime("%H:%M:%S"), "проверка выполнена, товаров:", len(new))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        notify("Тестовое сообщение: бот подключён ✅")
        found = scrape()
        print("Найдено товаров на сайте:", len(found))
        for sku, v in list(found.items())[:5]:
            print(" ", sku, v["name"], v["price"], "€")
        sys.exit()

    if len(sys.argv) > 1 and sys.argv[1] == "once":
        # режим для облака (GitHub Actions): одна проверка и выход
        check()
        with open(os.path.join(HERE, "heartbeat.txt"), "w") as f:
            f.write(time.strftime("%Y-%m-%d", time.gmtime()))
        sys.exit()

    print(f"Мониторинг запущен. Проверка каждые {INTERVAL_MIN} мин. Окно не закрывайте.")
    while True:
        try:
            check()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_MIN * 60)
