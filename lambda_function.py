import os
import json
import requests
import boto3
from datetime import datetime, timezone, timedelta
from slack_sdk import WebClient
from notion_client import Client as NotionClient
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ---------- SSM ----------
ssm = boto3.client('ssm')

def get_secret(name):
    return ssm.get_parameter(Name=f'/maki-daily-report/{name}', WithDecryption=True)['Parameter']['Value']

# ---------- 時刻 ----------
JST = timezone(timedelta(hours=9))
today = datetime.now(JST).date().isoformat()
start = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
end = datetime.now(JST).replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

# ---------- Clients ----------
slack = None
notion = None

def init_clients():
    global slack, notion
    slack = WebClient(token=get_secret('SLACK_TOKEN'))
    notion = NotionClient(auth=get_secret('NOTION_TOKEN'))

# ---------- GitHub ----------
def fetch_github_activity():
    url = f"https://api.github.com/users/{os.environ['GITHUB_USERNAME']}/events"
    headers = {"Authorization": f"Bearer {get_secret('GITHUB_TOKEN')}"}
    res = requests.get(url, headers=headers)
    events = res.json()

    lines = []
    for e in events:
        created = e.get("created_at", "")
        if today in created:
            if e["type"] == "PushEvent":
                for c in e["payload"]["commits"]:
                    lines.append(f"- Commit: {c['message']}")
            elif e["type"] == "PullRequestEvent":
                title = e["payload"]["pull_request"]["title"]
                lines.append(f"- PR: {title}")

    return "\n".join(lines) or "なし"

# ---------- Google Calendar ----------
def fetch_calendar_events():
    creds = service_account.Credentials.from_service_account_info(
        json.loads(get_secret('GOOGLE_SERVICE_ACCOUNT_JSON')),
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    service = build("calendar", "v3", credentials=creds)

    events = service.events().list(
        calendarId=os.environ["GOOGLE_CALENDAR_ID"],
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    lines = []
    for e in events.get("items", []):
        dt = e["start"].get("dateTime", "")
        time = dt[11:16] if dt else ""
        lines.append(f"- {time} {e.get('summary','')}")

    return "\n".join(lines) or "なし"

# ---------- Slack ----------
def fetch_slack_messages():
    result = slack.search_messages(
        query=f"from:<@{os.environ['SLACK_USER_ID']}> after:{today}"
    )

    matches = result.get("messages", {}).get("matches", [])
    lines = [f"- {m['text']}" for m in matches[:10]]
    return "\n".join(lines) or "なし"

# ---------- Markdown ----------
def build_markdown(github, calendar, slack_msg):
    return f"""# {today} 日報

## 🛠 実装・作業（GitHub）
{github}

## 🗓 時間の使い方（Calendar）
{calendar}

## 💬 思考・議論（Slack）
{slack_msg}

## 🧠 今日の学び（手書き1行）
"""

# ---------- Notion ----------
def post_to_notion(markdown):
    notion.pages.create(
        parent={"database_id": os.environ["NOTION_DATABASE_ID"]},
        properties={
            "title": {
                "title": [{"text": {"content": f"{today} 日報"}}]
            }
        },
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                },
            }
            for line in markdown.split("\n")
        ],
    )

# ---------- Handler ----------
def lambda_handler(event, context):
    init_clients()
    github = fetch_github_activity()
    calendar = fetch_calendar_events()
    slack_msg = fetch_slack_messages()

    md = build_markdown(github, calendar, slack_msg)
    post_to_notion(md)

    return {"statusCode": 200, "body": "OK"}
