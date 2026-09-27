terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.region
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/handler.py"
  output_path = "${path.module}/build/handler.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name = "${var.function_name}-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "sandbox" {
  function_name    = var.function_name
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 30
  memory_size      = 128

  # publish = true creates a numbered version on every apply that changes the
  # code -- Provisioned Concurrency needs a version or alias qualifier, it
  # cannot attach to $LATEST.
  publish = true

  environment {
    variables = {
      SIMULATED_INIT_DELAY_SECONDS = var.simulated_init_delay_seconds
    }
  }
}

# Alias so PC has a stable qualifier to attach to even as new versions publish.
resource "aws_lambda_alias" "prod" {
  name             = var.alias_name
  function_name    = aws_lambda_function.sandbox.function_name
  function_version = aws_lambda_function.sandbox.version
}

# Public Function URL so Locust can hit this directly with no API Gateway
# needed. authorization_type = NONE is fine for a throwaway sandbox target;
# do not reuse this pattern for snip-infra itself.
resource "aws_lambda_function_url" "sandbox_url" {
  function_name      = aws_lambda_function.sandbox.function_name
  qualifier          = aws_lambda_alias.prod.name
  authorization_type = var.function_url_auth_type
}

# Only needed/relevant when auth type is NONE -- with AWS_IAM, access is
# governed by the caller's identity-based policy instead, so this resource
# is skipped (count = 0) while function_url_auth_type = "AWS_IAM".
resource "aws_lambda_permission" "public_url_invoke" {
  count                   = var.function_url_auth_type == "NONE" ? 1 : 0
  statement_id            = "AllowPublicFunctionUrlInvoke"
  action                  = "lambda:InvokeFunctionUrl"
  function_name           = aws_lambda_function.sandbox.function_name
  qualifier               = aws_lambda_alias.prod.name
  principal               = "*"
  function_url_auth_type  = "NONE"
}