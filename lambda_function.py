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
ssm = boto3.client("ssm")


def get_secret(name):
    return ssm.get_parameter(Name=f"/maki-daily-report/{name}", WithDecryption=True)[
        "Parameter"
    ]["Value"]


# ---------- 時刻 ----------
JST = timezone(timedelta(hours=9))
today = datetime.now(JST).date().isoformat()
start = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
end = (
    datetime.now(JST).replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
)

# ---------- Clients ----------
slack = None
notion = None


def init_clients():
    global slack, notion
    slack = WebClient(token=get_secret("SLACK_TOKEN"))
    notion = NotionClient(auth=get_secret("NOTION_TOKEN"))


# ---------- GitHub ----------
def fetch_github_activity():
    url = f"https://api.github.com/users/{os.environ['GITHUB_USERNAME']}/events"
    headers = {"Authorization": f"Bearer {get_secret('GITHUB_TOKEN')}"}
    res = requests.get(url, headers=headers)
    print(f"GitHub: ステータスコード = {res.status_code}")
    events = res.json()
    print(f"GitHub: レスポンス = {json.dumps(events)[:200]}")
    print(f"GitHub: 取得イベント数 = {len(events) if isinstance(events, list) else 0}")
    print(f"GitHub: 対象日 = {today}")

    lines = []
    for e in events:
        created = e.get("created_at", "")
        if today in created:
            print(f"GitHub: マッチ = {e['type']}")
            if e["type"] == "PushEvent":
                for c in e["payload"]["commits"]:
                    lines.append(f"- Commit: {c['message']}")
            elif e["type"] == "PullRequestEvent":
                title = e["payload"]["pull_request"]["title"]
                lines.append(f"- PR: {title}")

    print(f"GitHub: 結果行数 = {len(lines)}")
    return "\n".join(lines) or "なし"


# ---------- Google Calendar ----------
def fetch_calendar_events():
    creds = service_account.Credentials.from_service_account_info(
        json.loads(get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")),
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    service = build("calendar", "v3", credentials=creds)

    # pylint: disable=no-member
    events = (
        service.events()
        .list(
            calendarId=os.environ["GOOGLE_CALENDAR_ID"],
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    lines = []
    for e in events.get("items", []):
        dt = e["start"].get("dateTime", "")
        time = dt[11:16] if dt else ""
        lines.append(f"- {time} {e.get('summary','')}")

    return "\n".join(lines) or "なし"


# ---------- Slack ----------
def fetch_slack_messages():
    # Slackの検索は日付をUnixタイムスタンプで指定（JST 0:00基準）
    after_ts = int(
        datetime.now(JST)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )
    user_id = os.environ['SLACK_USER_ID']
    query = f"from:<@{user_id}> after:{after_ts}"
    
    print(f"Slack: USER_ID = {user_id}")
    print(f"Slack: after_ts = {after_ts}")
    print(f"Slack: 検索クエリ = {query}")
    
    try:
        result = slack.search_messages(query=query)
        print(f"Slack: APIステータス = {result.get('ok', 'unknown')}")
        print(f"Slack: レスポンス全体 = {json.dumps(result.data, ensure_ascii=False)[:1000]}")
        
        messages = result.get("messages", {})
        print(f"Slack: messagesキー = {messages.keys() if messages else 'None'}")
        
        matches = messages.get("matches", [])
        print(f"Slack: マッチ数 = {len(matches)}")
        
        if matches:
            print(f"Slack: 最初のメッセージ = {json.dumps(matches[0], ensure_ascii=False)[:300]}")
        
        lines = [f"- {m['text']}" for m in matches[:10]]
        return "\n".join(lines) or "なし"
    except Exception as e:
        print(f"Slack: エラー発生 = {type(e).__name__}: {str(e)}")
        return "なし"


# ---------- Markdown ----------
def build_markdown(github, calendar, slack_msg):
    return f"""# {today} 日報

## 🛠 実装・作業（GitHub Public）
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
        properties={"title": {"title": [{"text": {"content": f"{today} 日報"}}]}},
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
    print(f"=== 日報作成開始: {today} ===")
    init_clients()
    github = fetch_github_activity()
    calendar = fetch_calendar_events()
    slack_msg = fetch_slack_messages()

    md = build_markdown(github, calendar, slack_msg)
    post_to_notion(md)
    print("=== Notion投稿完了 ===")

    return {"statusCode": 200, "body": "OK"}
