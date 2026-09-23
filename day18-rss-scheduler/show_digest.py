"""Print the latest saved digest for a human reader."""

from digest import latest_digest


def main():
    digest = latest_digest()["digest"]
    if not digest:
        print("Сводки пока нет. Сначала запустите сбор RSS и генерацию сводки.")
        return
    print(f"Сводка: {digest['created_at']} · источник: {digest['provider']} · публикаций: {digest['article_count']}\n")
    print(digest["body"])


if __name__ == "__main__":
    main()
