# AWS Profile Rule

このプロジェクトでは、すべてのAWS CLIコマンドに `--profile jsl` を使用してください。

例:
- `aws lambda invoke --profile jsl --function-name ...`
- `aws logs tail --profile jsl ...`
- `aws ssm get-parameter --profile jsl ...`
