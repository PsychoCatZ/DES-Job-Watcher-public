"""Один снимок HH: страница поиска и описание одной вакансии, без оценки."""

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
import time

import httpx


ROOT = Path(__file__).resolve().parents[1]
SEARCH_URL = "https://hh.ru/search/vacancy"
SEARCH_PARAMS = {
    "text": "чат поддержка",
    "area": "113",
    "work_format": "REMOTE",
    "order_by": "publication_time",
    "page": "0",
}


def load_search_plan():
    path = ROOT / "config" / "search_plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise ValueError("Неизвестная версия плана поиска.")
    profiles = plan.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"support", "developer", "ai_data"}:
        raise ValueError("В плане должны быть три согласованных профиля.")
    for profile in profiles.values():
        if not isinstance(profile, dict) or not isinstance(profile.get("label"), str):
            raise ValueError("У профиля отсутствует название.")
        queries = profile.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ValueError("У профиля должен быть непустой список запросов.")
        ids = set()
        for query in queries:
            if not isinstance(query, dict) or any(
                not isinstance(query.get(key), str) or not query[key].strip()
                for key in ("id", "text", "purpose")
            ):
                raise ValueError("Запрос должен содержать id, text и purpose.")
            if query["id"] in ids:
                raise ValueError("Идентификаторы запросов внутри профиля должны различаться.")
            ids.add(query["id"])
    return plan


def select_query(plan, profile_id, query_id=None):
    profile = plan["profiles"][profile_id]
    queries = profile["queries"]
    if query_id is None:
        query = queries[0]
    else:
        query = next((item for item in queries if item["id"] == query_id), None)
        if query is None:
            raise ValueError(f"Запрос {query_id!r} не найден в профиле {profile_id}.")
    # Копия: меняем параметры выбранного запуска, не общие настройки.
    params = SEARCH_PARAMS.copy()
    params["text"] = query["text"]
    return query, params


class StateParser(HTMLParser):
    """Читать только содержимое template с состоянием страницы."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.found = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "template" and dict(attrs).get("id") == "HH-Lux-InitialState":
            self.active = True
            self.found = True

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "template":
            self.active = False


class DescriptionParser(HTMLParser):
    """Сохранить текст и границы абзацев/списков, исключить script и style."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipped = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skipped += 1
        if not self.skipped and tag in {"p", "div", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skipped = max(0, self.skipped - 1)
        elif not self.skipped and tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipped:
            self.parts.append(data)


def extract_state(html):
    parser = StateParser()
    parser.feed(html)
    if not parser.found:
        raise ValueError(
            "HH-Lux-InitialState отсутствует: структура изменилась или пришла "
            "другая страница. Это не пустая выдача."
        )
    state = json.loads("".join(parser.parts))
    if not isinstance(state, dict):
        raise ValueError("Состояние страницы должно быть JSON-объектом.")
    return state


def description_to_text(html):
    parser = DescriptionParser()
    parser.feed(html)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    if not text:
        raise ValueError("Описание не содержит читаемого текста.")
    return text


def fetch_state(client, url, params=None):
    response = client.get(url, params=params)
    print(f"HTTP {response.status_code}: {response.url.path}")
    if response.is_redirect:
        raise ValueError(
            "Сайт перенаправляет запрос. Проверка остановлена; "
            "переходы на капчу или вход автоматически не выполняются."
        )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        raise ValueError("Вместо HTML получен другой тип содержимого.")
    return extract_state(response.text), str(response.url)


def extract_search(state, params=None):
    if params is None:
        params = SEARCH_PARAMS
    try:
        result = state["vacancySearchResult"]
        criteria = result["criteria"]
        vacancies = result["vacancies"]
        if not isinstance(vacancies, list):
            raise ValueError("vacancies должен быть списком.")
        # Подтверждаем, что сайт действительно применил условия запроса.
        expected = {"area": [int(params["area"])], "work_format": [params["work_format"]],
                    "order_by": params["order_by"], "page": int(params["page"]),
                    "text": params["text"]}
        if any(criteria.get(key) != value for key, value in expected.items()):
            raise ValueError("Сайт не подтвердил ожидаемые параметры поиска.")
        items = []
        for vacancy in vacancies:
            vacancy_id = str(vacancy["vacancyId"])
            if not vacancy_id.isascii() or not vacancy_id.isdecimal():
                raise ValueError("Неожиданный идентификатор вакансии.")
            if not isinstance(vacancy["name"], str):
                raise ValueError("Название вакансии должно быть строкой.")
            company = vacancy.get("company") or {}
            items.append({
                "id": vacancy_id,
                "name": vacancy["name"],
                "employer": {key: company[key] for key in ("id", "name", "visibleName")
                             if key in company},
                "url": f"https://hh.ru/vacancy/{vacancy_id}",
                "area": vacancy.get("area"),
                "salary": vacancy.get("compensation"),
                "work_formats": vacancy.get("workFormats"),
                "published_at": vacancy.get("publicationTime"),
                "source_changed_at": vacancy.get("lastChangeTime"),
            })
        return {"criteria": {key: criteria[key] for key in expected},
                "total_found": result["totalResults"], "items": items}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Неожиданная структура поисковой выдачи HH.") from error


def extract_detail(state, expected_id):
    try:
        vacancy = state["vacancyView"]["vacancyFull"]["vacancy"]
        if str(vacancy["vacancyId"]) != expected_id:
            raise ValueError("Карточка содержит другой ID вакансии.")
        html = vacancy["description"]
        if not isinstance(html, str):
            raise ValueError("Описание должно быть строкой HTML.")
        return {"id": expected_id, "description_html": html,
                "description_text": description_to_text(html),
                "archived": vacancy.get("status", {}).get("archived"),
                "work_formats": vacancy.get("workFormats")}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Неожиданная структура карточки HH.") from error


def save_snapshot(snapshot):
    directory = ROOT / "data" / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    target = directory / f"hh_{stamp}.json"
    # Сначала пишем временный файл; готовым снимком он станет после замены имени.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temp_path.replace(target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contact", default=os.environ.get("HH_CONTACT_EMAIL"),
                        help="Контактная почта для User-Agent (или HH_CONTACT_EMAIL)")
    parser.add_argument("--profile", choices=("support", "developer", "ai_data"),
                        default="support", help="Профиль поиска")
    parser.add_argument("--query", help="ID запроса внутри профиля; по умолчанию первый")
    parser.add_argument("--list-queries", action="store_true",
                        help="Показать план и выйти без запросов к HH")
    args = parser.parse_args()

    try:
        plan = load_search_plan()
        if args.list_queries:
            for profile_id, profile in plan["profiles"].items():
                print(f"\n{profile_id}: {profile['label']}")
                for query in profile["queries"]:
                    print(f"  {query['id']}: {query['text']} — {query['purpose']}")
            return 0
        query, params = select_query(plan, args.profile, args.query)
        if not args.contact or "@" not in args.contact or any(c.isspace() for c in args.contact):
            parser.error("Укажите контакт: --contact ваша-почта")
        print(f"Профиль поиска: {args.profile}; запрос: {query['text']}")
        print("Один проход: поиск и максимум одна карточка. Без повторов и оценки.")
        headers = {"User-Agent": f"DES-Job-Watcher/0.1 ({args.contact})",
                   "Accept": "text/html"}
        with httpx.Client(timeout=25, headers=headers, follow_redirects=False) as client:
            state, search_url = fetch_state(client, SEARCH_URL, params)
            search = extract_search(state, params)
            print(f"Найдено: {search['total_found']}; на странице: {len(search['items'])}")
            for item in search["items"][:10]:
                print(f"  [{item['id']}] {item['name']}")
            detail = None
            if search["items"]:
                selected = search["items"][0]
                time.sleep(4)  # Учебная пауза, не подтверждённый лимит HH.
                state, detail_url = fetch_state(client, selected["url"])
                detail = extract_detail(state, selected["id"])
                detail["url"] = detail_url
                print(f"Карточка: [{selected['id']}] {selected['name']}")
                print(f"Описание: {len(detail['description_text'])} символов текста")
        snapshot = {"schema_version": 2, "source": "hh_html",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "search_url": search_url, "search": search, "detail": detail,
                    "discovery": {"plan_version": plan["version"],
                                  "profile_id": args.profile, "query_id": query["id"],
                                  "query_text": query["text"]}}
        path = save_snapshot(snapshot)
        print(f"Сохранено: {path}")
        print("Это снимок кандидатов. Голос, Data Light и резюме ещё не проверяются.")
    except httpx.HTTPStatusError as error:
        print(f"Остановка: HTTP {error.response.status_code}. Повторов нет.")
        if error.response.status_code == 429:
            print("Retry-After:", error.response.headers.get("retry-after", "не указан"))
        return 1
    except httpx.RequestError:
        print("Остановка: сетевая ошибка (DNS, соединение, TLS или таймаут).")
        return 1
    except (OSError, ValueError) as error:
        print(f"Остановка: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
