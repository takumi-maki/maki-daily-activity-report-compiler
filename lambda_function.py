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
NOTION_BLOCK_LIMIT = 100
SLACK_TEXT_LIMIT = 300

# ---------- Clients ----------
slack = None
notion = None


def init_clients():
    global slack, notion
    slack = WebClient(token=get_secret("SLACK_TOKEN"))
    notion = NotionClient(auth=get_secret("NOTION_TOKEN"))


def get_report_window():
    now_jst = datetime.now(JST)
    day_start_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_jst = now_jst.replace(hour=23, minute=59, second=59, microsecond=0)
    return now_jst.date().isoformat(), day_start_jst, day_end_jst


# ---------- GitHub ----------
def fetch_github_activity(today, day_start_jst, day_end_jst):
    try:
        url = f"https://api.github.com/users/{os.environ['GITHUB_USERNAME']}/events"
        headers = {"Authorization": f"Bearer {get_secret('GITHUB_TOKEN')}"}
        res = requests.get(url, headers=headers, timeout=15)
        print(f"GitHub: ステータスコード = {res.status_code}")
        events = res.json()
        print(f"GitHub: レスポンス = {json.dumps(events)[:200]}")
        print(f"GitHub: 取得イベント数 = {len(events) if isinstance(events, list) else 0}")
        print(f"GitHub: 対象日 = {today}")

        if not isinstance(events, list):
            return "なし", 0, 0

        lines = []
        matched_events = 0
        for e in events:
            created = e.get("created_at", "")
            if not created:
                continue
            try:
                created_jst = datetime.fromisoformat(
                    created.replace("Z", "+00:00")
                ).astimezone(JST)
            except ValueError:
                continue
            if day_start_jst <= created_jst <= day_end_jst:
                matched_events += 1
                event_type = e.get("type", "unknown")
                print(f"GitHub: マッチ = {event_type} at {created_jst.isoformat()}")
                if event_type == "PushEvent":
                    payload = e.get("payload", {})
                    commits = payload.get("commits", [])
                    print(f"GitHub: commits数 = {len(commits)}")
                    for c in commits:
                        lines.append(f"- Commit: {c.get('message', '')}")
                elif event_type == "PullRequestEvent":
                    title = e.get("payload", {}).get("pull_request", {}).get("title", "")
                    if title:
                        lines.append(f"- PR: {title}")

        print(f"GitHub: マッチイベント数 = {matched_events}")
        print(f"GitHub: 結果行数 = {len(lines)}")
        return "\n".join(lines) or "なし", matched_events, len(lines)
    except Exception as e:
        print(f"GitHub: エラー発生 = {type(e).__name__}: {str(e)}")
        return "⚠️ 取得エラー（ログ参照）", 0, 0


# ---------- Google Calendar ----------
def fetch_calendar_events(day_start_jst, day_end_jst):
    try:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")),
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        service = build("calendar", "v3", credentials=creds)

        calendar_ids = [
            cid.strip() for cid in os.environ["GOOGLE_CALENDAR_IDS"].split(",") if cid.strip()
        ]
        print(f"Calendar: 対象カレンダー = {calendar_ids}")

        # 全カレンダーのイベントを集約
        all_events = []
        for calendar_id in calendar_ids:
            try:
                # pylint: disable=no-member
                events = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=day_start_jst.isoformat(),
                        timeMax=day_end_jst.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
                for e in events.get("items", []):
                    dt = e.get("start", {}).get("dateTime", "")
                    if dt:
                        all_events.append({
                            "datetime": dt,
                            "summary": e.get("summary", "")
                        })
            except Exception as e:
                print(f"Calendar: {calendar_id} 取得エラー = {type(e).__name__}: {str(e)}")
                continue

        # 時刺順にソート
        all_events.sort(key=lambda x: x["datetime"])

        # フォーマット
        lines = []
        for event in all_events:
            time = event["datetime"][11:16]
            lines.append(f"- {time} {event['summary']}")

        print(f"Calendar: イベント数 = {len(lines)}")
        return "\n".join(lines) or "なし", len(lines)
    except Exception as e:
        print(f"Calendar: エラー発生 = {type(e).__name__}: {str(e)}")
        return "⚠️ 取得エラー（ログ参照）", 0


# ---------- Slack ----------
def fetch_slack_messages(today, day_start_jst, day_end_jst):
    user_id = os.environ["SLACK_USER_ID"]
    
    # デバッグ: 日付範囲を広げてテスト
    after_date = (day_start_jst - timedelta(days=7)).strftime("%Y-%m-%d")
    before_date = (day_start_jst + timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"from:<@{user_id}> after:{after_date} before:{before_date}"

    print(f"Slack: 対象日(JST) = {today}")
    print(
        "Slack: 取得範囲(JST) = "
        f"{day_start_jst.strftime('%Y-%m-%d %H:%M:%S')} - "
        f"{day_end_jst.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print(f"Slack: デバッグ検索範囲 = {after_date} ~ {before_date} (7日間)")
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

        # チャンネルごとにグループ化
        channels = {}
        for m in matches[:50]:
            channel_name = m.get("channel", {}).get("name", "unknown")
            text = m.get("text", "").replace("\n", " ").strip()
            
            # デバッグ: メッセージの日付をログ出力
            ts = m.get("ts", "")
            if ts:
                msg_date = datetime.fromtimestamp(float(ts), tz=JST).strftime("%Y-%m-%d %H:%M:%S")
                print(f"Slack: メッセージ日時 = {msg_date}")
            
            if len(text) > SLACK_TEXT_LIMIT:
                text = f"{text[:SLACK_TEXT_LIMIT]}..."
            
            if channel_name not in channels:
                channels[channel_name] = []
            channels[channel_name].append(text)

        # チャンネルごとにフォーマット
        lines = []
        for channel_name, texts in channels.items():
            lines.append(f"\n### {channel_name}")
            for text in texts:
                lines.append(f"- {text}")

        print(f"Slack: 出力行数 = {len(lines)}")
        return "\n".join(lines) or "なし", len(matches), len(lines)
    except Exception as e:
        print(f"Slack: エラー発生 = {type(e).__name__}: {str(e)}")
        return "⚠️ 取得エラー（ログ参照）", 0, 0


# ---------- Markdown ----------
def build_markdown(today, github, calendar, slack_msg):
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
def post_to_notion(markdown, today):
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line}}]
            },
        }
        for line in markdown.split("\n")
    ]
    total_blocks = len(children)
    print(f"Notion: 送信予定ブロック数 = {total_blocks}")

    first_chunk = children[:NOTION_BLOCK_LIMIT]
    page = notion.pages.create(
        parent={"database_id": os.environ["NOTION_DATABASE_ID"]},
        properties={"title": {"title": [{"text": {"content": f"{today} 日報"}}]}},
        children=first_chunk,
    )
    page_id = page["id"]

    offset = NOTION_BLOCK_LIMIT
    while offset < total_blocks:
        chunk = children[offset : offset + NOTION_BLOCK_LIMIT]
        notion.blocks.children.append(block_id=page_id, children=chunk)
        print(
            f"Notion: 追加ブロック {offset + 1}-{offset + len(chunk)} / {total_blocks}"
        )
        offset += NOTION_BLOCK_LIMIT


# ---------- Handler ----------
def lambda_handler(event, context):
    today, day_start_jst, day_end_jst = get_report_window()
    print(f"=== 日報作成開始: {today} ===")
    github_line_count = 0
    github_event_count = 0
    slack_match_count = 0
    notion_block_count = 0
    try:
        init_clients()
        github, github_event_count, github_line_count = fetch_github_activity(
            today, day_start_jst, day_end_jst
        )
        calendar, _ = fetch_calendar_events(day_start_jst, day_end_jst)
        slack_msg, slack_match_count, _ = fetch_slack_messages(
            today, day_start_jst, day_end_jst
        )

        md = build_markdown(today, github, calendar, slack_msg)
        notion_block_count = len(md.split("\n"))
        print(
            f"Metrics: github_events={github_event_count}, github_lines={github_line_count}, "
            f"slack_matches={slack_match_count}, notion_blocks={notion_block_count}"
        )
        post_to_notion(md, today)
        print("=== Notion投稿完了 ===")
        return {"statusCode": 200, "body": "OK"}
    except Exception:
        print(
            f"FailureMetrics: github_events={github_event_count}, github_lines={github_line_count}, "
            f"slack_matches={slack_match_count}, notion_blocks={notion_block_count}"
        )
        raise
