"""Create a local Telethon session for Telegram channel ingestion."""

from getpass import getpass

from utils import clean_token

try:
    from telethon.sync import TelegramClient
except ImportError:  # pragma: no cover - helper script path
    TelegramClient = None


def main():
    if TelegramClient is None:
        raise SystemExit("Telethon is not installed. Run: pip install -r requirements.txt")

    api_id = clean_token(input("Telegram API ID: "))
    api_hash = clean_token(getpass("Telegram API Hash: "))
    session_name = clean_token(input("Session name [telegram_news_session]: ")) or "telegram_news_session"
    if not api_id or not api_hash:
        raise SystemExit("Telegram API ID and API Hash are required.")

    with TelegramClient(session_name, int(api_id), api_hash) as client:
        client.start()
        if not client.is_user_authorized():
            raise SystemExit("Telegram login was not completed.")

    print(f"Telegram session created: {session_name}.session")


if __name__ == "__main__":
    main()
