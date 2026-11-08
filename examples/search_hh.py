"""Первый учебный пример: JSON и один запрос HH, без оценки вакансий."""

import argparse
import json
import os
from pathlib import Path

import httpx


def fetch_vacancies():
    """Получить одну страницу. Токен и контакт не хранятся в коде."""
    token = os.environ.get("HH_ACCESS_TOKEN", "").strip()
    user_agent = os.environ.get("HH_USER_AGENT", "").strip()
    if not token or not user_agent:
        raise ValueError(
            "Для --live задайте HH_ACCESS_TOKEN и HH_USER_AGENT. "
            "Без регистрации используйте учебный режим."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "HH-User-Agent": user_agent,
    }
    params = {
        "text": "чат поддержка",
        "area": "113",
        "work_format": "REMOTE",
        "order_by": "publication_time",
        "page": 0,
        "per_page": 3,
        "host": "hh.ru",
        "locale": "RU",
    }

    # with закрывает соединения даже при исключении внутри блока.
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            "https://api.hh.ru/vacancies", params=params, headers=headers
        )
        response.raise_for_status()
        return response.json()


def print_vacancies(data):
    """Проверить нужные поля и вывести краткий список кандидатов."""
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект с результатами поиска.")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("В ответе отсутствует список items.")

    # Сначала проверяем всю страницу, чтобы не вывести частичный результат.
    for vacancy in items:
        if not isinstance(vacancy, dict):
            raise ValueError("Элемент items должен быть объектом вакансии.")
        if not all(isinstance(vacancy.get(key), str) for key in ("id", "name")):
            raise ValueError("У вакансии отсутствуют строковые id или name.")
        employer = vacancy.get("employer")
        if employer is not None and not isinstance(employer, dict):
            raise ValueError("Поле employer должно быть объектом или null.")

    print(f"Найдено по запросу: {data.get('found', 'не указано')}")
    print(f"В этой странице: {len(items)}")
    for vacancy in items:
        employer = vacancy.get("employer") or {}
        print(f"\n[{vacancy['id']}] {vacancy['name']}")
        print(f"Работодатель: {employer.get('name') or 'не указан'}")
        print(f"Ссылка: {vacancy.get('alternate_url') or 'не указана'}")
    print("\nЭто кандидаты из поиска, а не проверенные рекомендации.")
    print("Фильтры голоса, работодателя и сравнение с резюме ещё не реализованы.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Один запрос к HH API")
    args = parser.parse_args()

    try:
        if args.live:
            print("СЕТЕВОЙ РЕЖИМ: одна страница HH, без повторных запросов.")
            data = fetch_vacancies()
        else:
            print("УЧЕБНЫЙ РЕЖИМ: вымышленные данные, без обращения к HH.")
            sample = Path(__file__).with_name("sample_search.json")
            data = json.loads(sample.read_text(encoding="utf-8"))
        print_vacancies(data)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        hints = {
            400: "Проверьте параметры запроса.",
            401: "Проверьте токен авторизации.",
            403: "Доступ запрещён: возможны ограничения доступа или капча.",
            429: "Лимит запросов. Автоматического повтора в примере нет.",
        }
        print(f"HH вернул HTTP {status}. {hints.get(status, 'Запрос не выполнен.')}")
        return 1
    except httpx.RequestError:
        # Не печатаем объект запроса и заголовки с токеном.
        print("Сетевая ошибка: соединение, DNS, TLS или ожидание ответа. Проверьте сеть.")
        return 1
    except (OSError, ValueError) as error:
        print(f"Ошибка данных или настройки: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
