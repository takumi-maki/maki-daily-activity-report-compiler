# Daily Activity Report Compiler

毎日の活動を自動収集してNotionに日報を作成するLambda関数

## 技術スタック

- **AWS Lambda** - サーバーレス実行環境（Python 3.11）
- **SAM (AWS Serverless Application Model)** - インフラをコードで定義・デプロイ
- **SSM Parameter Store** - 環境変数とシークレットの安全な管理
- **EventBridge** - 平日14:00 UTC（JST 23:00）の定期実行スケジュール
- **GitHub API** - Public リポジトリの活動取得
- **Google Calendar API** - カレンダーイベント取得
- **Slack API** - メッセージ検索
- **Notion API** - 日報ページ作成

## セットアップ

### 1. SSMパラメータの登録

```bash
./setup-ssm.sh
```

または手動で登録（`{prefix}` は任意のパス、例: `/your-name-daily-report`）：

```bash
aws ssm put-parameter --name /{prefix}/GITHUB_TOKEN --value "your_token" --type SecureString
aws ssm put-parameter --name /{prefix}/GITHUB_USERNAME --value "your_username" --type String
# ... 他の環境変数も同様に登録
```

### 2. デプロイ

```bash
sam build
sam deploy --guided
```

初回は `--guided` で対話的に設定。2回目以降は `sam deploy` のみでOK。

## 環境変数

SSM Parameter Storeに以下のパラメータを登録（`{prefix}` は任意のパス）：

- `/{prefix}/GITHUB_TOKEN` (SecureString) - GitHub Personal Access Token
- `/{prefix}/GITHUB_USERNAME` (String) - GitHubユーザー名
- `/{prefix}/GOOGLE_SERVICE_ACCOUNT_JSON` (SecureString) - Google Service Account JSON
- `/{prefix}/GOOGLE_CALENDAR_IDS` (String) - Google Calendar IDs（カンマ区切り）
- `/{prefix}/SLACK_TOKEN` (SecureString) - Slack Bot Token
- `/{prefix}/SLACK_USER_ID` (String) - Slack User ID
- `/{prefix}/NOTION_TOKEN` (SecureString) - Notion Integration Token
- `/{prefix}/NOTION_DATABASE_ID` (String) - Notion Database ID
