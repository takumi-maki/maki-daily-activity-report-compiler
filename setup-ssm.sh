#!/bin/bash

PROFILE="jsl"

echo "SSMパラメータを登録します..."

read -p "GITHUB_TOKEN: " GITHUB_TOKEN
read -p "GITHUB_USERNAME: " GITHUB_USERNAME
read -p "GOOGLE_SERVICE_ACCOUNT_JSON: " GOOGLE_SERVICE_ACCOUNT_JSON
read -p "GOOGLE_CALENDAR_ID: " GOOGLE_CALENDAR_ID
read -p "SLACK_TOKEN: " SLACK_TOKEN
read -p "SLACK_USER_ID: " SLACK_USER_ID
read -p "NOTION_TOKEN: " NOTION_TOKEN
read -p "NOTION_DATABASE_ID: " NOTION_DATABASE_ID

aws ssm put-parameter --name /maki-daily-report/GITHUB_TOKEN --value "$GITHUB_TOKEN" --type SecureString --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/GITHUB_USERNAME --value "$GITHUB_USERNAME" --type String --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/GOOGLE_SERVICE_ACCOUNT_JSON --value "$GOOGLE_SERVICE_ACCOUNT_JSON" --type SecureString --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/GOOGLE_CALENDAR_ID --value "$GOOGLE_CALENDAR_ID" --type String --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/SLACK_TOKEN --value "$SLACK_TOKEN" --type SecureString --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/SLACK_USER_ID --value "$SLACK_USER_ID" --type String --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/NOTION_TOKEN --value "$NOTION_TOKEN" --type SecureString --profile $PROFILE
aws ssm put-parameter --name /maki-daily-report/NOTION_DATABASE_ID --value "$NOTION_DATABASE_ID" --type String --profile $PROFILE

echo "完了しました"
