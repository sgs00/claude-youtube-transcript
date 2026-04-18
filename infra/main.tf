terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------------------------------------------------------------------------
# Secrets Manager — token value is set via CLI, never via Terraform
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "bearer_token" {
  name                    = var.secret_name
  description             = "Bearer token for claude-yt-companion Lambda Function URL"
  recovery_window_in_days = 0
}

# ---------------------------------------------------------------------------
# IAM role for Lambda
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.function_name}-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "secrets_read" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.bearer_token.arn]
  }
}

resource "aws_iam_role_policy" "secrets_read" {
  name   = "${var.function_name}-secrets-read"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.secrets_read.json
}

# ---------------------------------------------------------------------------
# Lambda function — deployment package built by deploy.sh
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "main" {
  function_name    = var.function_name
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 60
  reserved_concurrent_executions = 2

  filename         = "${path.module}/../dist/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../dist/lambda.zip")

  environment {
    variables = {
      SECRET_NAME = var.secret_name
    }
  }

  depends_on = [aws_iam_role_policy_attachment.basic_execution]
}

# ---------------------------------------------------------------------------
# Function URL — auth handled at application level via Bearer token
# ---------------------------------------------------------------------------

resource "aws_lambda_function_url" "main" {
  function_name      = aws_lambda_function.main.function_name
  authorization_type = "NONE"
  invoke_mode        = "BUFFERED"
}
