# Daily Activity Report Compiler

毎日の活動を自動収集してNotionに日報を作成するLambda関数

## セットアップ

1. 依存関係のインストール:
```bash
pip install -r requirements.txt
```

2. 環境変数の設定:
`.env.example`をコピーして`.env`を作成し、各値を設定

3. デプロイ:
```bash
sam build
sam deploy --guided
```

## 環境変数

- `GITHUB_TOKEN` - GitHub Personal Access Token
- `GITHUB_USERNAME` - GitHubユーザー名
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Google Service Account JSON
- `GOOGLE_CALENDAR_ID` - Google Calendar ID
- `SLACK_TOKEN` - Slack Bot Token
- `SLACK_USER_ID` - Slack User ID
- `NOTION_TOKEN` - Notion Integration Token
- `NOTION_DATABASE_ID` - Notion Database ID
