output "function_url" {
  description = "HTTPS endpoint for the Lambda Function URL (use as MCP server URL in Claude Web)"
  value       = aws_lambda_function_url.main.function_url
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret; set value via: aws secretsmanager put-secret-value --secret-id <arn> --secret-string '<token>'"
  value       = aws_secretsmanager_secret.bearer_token.arn
}

output "function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.main.function_name
}
