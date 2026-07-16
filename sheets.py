"""
Thin wrapper around gspread for writing leads into the existing Life Energy
Google Sheet CRM.

Expects a service-account JSON key, provided either as:
  - GOOGLE_CREDENTIALS_JSON: the full JSON key content pasted as one env var
    (used on Railway/hosting, where there's no file to upload), or
  - GOOGLE_CREDENTIALS_PATH: a path to the JSON key file (used when running
    locally with the file sitting next to bot.py).

The sheet must have a tab (default "Leads") with this header row in row 1:

  Timestamp | Telegram | Telegram ID | Ім'я | Телефон | Інтерес | Бажаний час | Статус
"""
import json
import os
from datetime import datetime
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1C8qKB-fpGvoWQyA89pAvtNIlhizuIeyRJUSLv3zKp6A"
)
SHEET_TAB = os.environ.get("SHEET_TAB", "Leads")
CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

INTEREST_LABELS = {
    "literacy": "Фінансова грамотність",
    "income": "Додатковий дохід",
    "career": "Нова професія",
    "invest": "Інвестування",
    "business": "Розвиток бізнесу",
    "unsure": "Не визначився",
}
TIME_LABELS = {
    "today": "Сьогодні",
    "tomorrow": "Завтра",
    "week": "Цього тижня",
    "text": "Текстом",
}


@lru_cache(maxsize=1)
def _worksheet():
    if CREDENTIALS_JSON:
        info = json.loads(CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    try:
        return sheet.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=SHEET_TAB, rows=1000, cols=8)
        ws.append_row(
            ["Timestamp", "Telegram", "Telegram ID", "Ім'я", "Телефон", "Інтерес", "Бажаний час", "Статус"]
        )
        return ws


def log_lead(
    telegram_username: str,
    telegram_id: int,
    name: str,
    phone: str,
    interest: str,
    preferred_time: str,
    status: str,
) -> None:
    row = [
        datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        f"@{telegram_username}" if telegram_username else "",
        str(telegram_id),
        name,
        phone,
        INTEREST_LABELS.get(interest, interest),
        TIME_LABELS.get(preferred_time, preferred_time),
        status,
    ]
    _worksheet().append_row(row)


def update_lead_status(telegram_id: int, new_status: str) -> None:
    ws = _worksheet()
    cell = ws.find(str(telegram_id), in_column=3)
    if cell:
        ws.update_cell(cell.row, 8, new_status)
