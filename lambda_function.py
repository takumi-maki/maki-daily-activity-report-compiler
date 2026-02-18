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
SLACK_TEXT_LIMIT = 150

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
        username = os.environ['GITHUB_USERNAME']
        headers = {"Authorization": f"Bearer {get_secret('GITHUB_TOKEN')}"}
        
        # ユーザーのリポジトリ一覧を取得
        repos_url = f"https://api.github.com/users/{username}/repos?type=owner&sort=pushed&per_page=10"
        repos_res = requests.get(repos_url, headers=headers, timeout=15)
        print(f"GitHub: リポジトリ取得ステータス = {repos_res.status_code}")
        
        repos = repos_res.json() if repos_res.status_code == 200 else []
        print(f"GitHub: リポジトリ数 = {len(repos) if isinstance(repos, list) else 0}")
        print(f"GitHub: 対象日 = {today}")
        
        if not isinstance(repos, list):
            return "なし", 0, 0
        
        lines = []
        total_commits = 0
        
        # 各リポジトリのコミットを確認
        for repo in repos[:5]:  # 最新5リポジトリのみ
            repo_name = repo.get("full_name", "")
            if not repo_name:
                continue
            
            # コミット履歴を取得（対象日のみ）
            commits_url = f"https://api.github.com/repos/{repo_name}/commits"
            params = {
                "author": username,
                "since": day_start_jst.isoformat(),
                "until": day_end_jst.isoformat(),
                "per_page": 30
            }
            commits_res = requests.get(commits_url, headers=headers, params=params, timeout=15)
            
            if commits_res.status_code != 200:
                continue
            
            commits = commits_res.json()
            if not isinstance(commits, list) or len(commits) == 0:
                continue
            
            print(f"GitHub: {repo_name} のコミット数 = {len(commits)}")
            total_commits += len(commits)
            
            for commit in commits:
                commit_data = commit.get("commit", {})
                message = commit_data.get("message", "").split("\n")[0]  # 1行目のみ
                lines.append(f"- [{repo.get('name', repo_name)}] {message}")
        
        print(f"GitHub: 合計コミット数 = {total_commits}")
        print(f"GitHub: 結果行数 = {len(lines)}")
        return "\n".join(lines) or "なし", total_commits, len(lines)
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

        # チャンネルごとにグループ化（タイムスタンプ付き）
        channels = {}
        for m in matches[:50]:
            channel_name = m.get("channel", {}).get("name", "unknown")
            text = m.get("text", "").replace("\n", " ").strip()
            ts = m.get("ts", "")
            
            # デバッグ: メッセージの日付をログ出力
            if ts:
                msg_date = datetime.fromtimestamp(float(ts), tz=JST).strftime("%Y-%m-%d %H:%M:%S")
                print(f"Slack: メッセージ日時 = {msg_date}")
            
            if len(text) > SLACK_TEXT_LIMIT:
                text = f"{text[:SLACK_TEXT_LIMIT]}..."
            
            if channel_name not in channels:
                channels[channel_name] = []
            channels[channel_name].append({"ts": float(ts) if ts else 0, "text": text})

        # チャンネルごとにフォーマット（時系列順にソート）
        lines = []
        for channel_name, messages in channels.items():
            # タイムスタンプで昇順ソート
            messages.sort(key=lambda x: x["ts"])
            lines.append(f"\n### {channel_name}")
            for msg in messages:
                lines.append(f"- {msg['text']}")

        print(f"Slack: 出力行数 = {len(lines)}")
        return "\n".join(lines) or "なし", len(matches), len(lines)
    except Exception as e:
        print(f"Slack: エラー発生 = {type(e).__name__}: {str(e)}")
        return "⚠️ 取得エラー（ログ参照）", 0, 0


# ---------- Notion Boki Learning ----------
def fetch_boki_learning(day_start_jst, day_end_jst):
    try:
        boki_db_id = os.environ.get("NOTION_BOKI_DATABASE_ID")
        if not boki_db_id:
            print("Boki: NOTION_BOKI_DATABASE_IDが設定されていません")
            return ""
        
        print(f"Boki: 対象DB = {boki_db_id}")
        print(f"Boki: 取得範囲(JST) = {day_start_jst.isoformat()} ~ {day_end_jst.isoformat()}")
        
        # Notion APIでデータベースをクエリ
        response = notion.data_sources.query(
            data_source_id=boki_db_id,
            filter={
                "and": [
                    {
                        "property": "作成日時",
                        "created_time": {
                            "on_or_after": day_start_jst.isoformat()
                        }
                    },
                    {
                        "property": "作成日時",
                        "created_time": {
                            "on_or_before": day_end_jst.isoformat()
                        }
                    },
                    {
                        "property": "時間(m)",
                        "number": {
                            "greater_than": 0
                        }
                    }
                ]
            },
            sorts=[{"property": "作成日時", "direction": "descending"}],
            page_size=1
        )
        
        results = response.get("results", [])
        print(f"Boki: 取得件数 = {len(results)}")
        
        if not results:
            return ""
        
        page = results[0]
        props = page.get("properties", {})
        
        # 「やったこと」取得
        title_prop = props.get("やったこと", {})
        title_list = title_prop.get("rich_text", [])
        title = title_list[0].get("plain_text", "") if title_list else ""
        
        # 「時間(m)」取得
        time_prop = props.get("時間(m)", {})
        time_minutes = time_prop.get("number", 0)
        
        # 「理解したこと」取得
        memo_prop = props.get("理解したこと", {})
        memo_list = memo_prop.get("rich_text", [])
        memo = memo_list[0].get("plain_text", "") if memo_list else ""
        
        print(f"Boki: タイトル = {title}")
        print(f"Boki: 時間 = {time_minutes}分")
        print(f"Boki: メモ = {memo[:50]}...")
        
        # Markdown生成
        lines = []
        lines.append(f"- {title}（{time_minutes}分）")
        if memo:
            lines.append(f"- 理解したこと：{memo}")
        
        return "\n".join(lines)
        
    except Exception as e:
        print(f"Boki: エラー発生 = {type(e).__name__}: {str(e)}")
        return ""


# ---------- Markdown ----------
def build_markdown(today, github, calendar, slack_msg, boki_learning=""):
    sections = []
    sections.append(f"# {today} 日報")
    sections.append("")
    sections.append("## 🛠 実装・作業（GitHub Public）")
    sections.append(github)
    sections.append("")
    sections.append("## 🗓 時間の使い方（Calendar）")
    sections.append(calendar)
    sections.append("")
    sections.append("## 💬 思考・議論（Slack）")
    sections.append(slack_msg)
    
    # 簿記学習ログがあれば追加
    if boki_learning:
        sections.append("")
        sections.append("## 📚 学習（簿記3級）")
        sections.append(boki_learning)
    
    sections.append("")
    sections.append("## 🧠 今日の学び（手書き1行）")
    
    return "\n".join(sections)


# ---------- Notion ----------
def line_to_block(line):
    """Markdown行をNotion Blockに変換"""
    line = line.strip()
    
    if not line:
        return None
    
    # 2000文字制限チェック
    def truncate(text):
        return text[:1997] + "..." if len(text) > 2000 else text
    
    if line.startswith("# "):
        return {
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": truncate(line[2:])}}]}
        }
    elif line.startswith("## "):
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": truncate(line[3:])}}]}
        }
    elif line.startswith("### "):
        return {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": truncate(line[4:])}}]}
        }
    elif line.startswith("- "):
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": truncate(line[2:])}}]}
        }
    else:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": truncate(line)}}]}
        }


def post_to_notion(markdown, today):
    children = []
    for line in markdown.split("\n"):
        block = line_to_block(line)
        if block:
            children.append(block)
    
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
        boki_learning = fetch_boki_learning(day_start_jst, day_end_jst)

        md = build_markdown(today, github, calendar, slack_msg, boki_learning)
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
