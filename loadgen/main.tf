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
  region = var.region
}

data "aws_caller_identity" "current" {}

# Fails at plan time if sandbox-lambda is not deployed, instead of every request
# failing at run time (Known issue 4).
data "aws_lambda_function" "target" {
  function_name = var.function_name
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  name         = "${var.function_name}-loadgen"
  function_arn = data.aws_lambda_function.target.arn
  alias_arn    = "${data.aws_lambda_function.target.arn}:${var.alias_name}"
}

# --- Results bucket: the instance uploads run outputs, you download them ----

resource "aws_s3_bucket" "results" {
  bucket = "${local.name}-results-${data.aws_caller_identity.current.account_id}"
  # force_destroy stays false: `terraform destroy` refuses while run data is in
  # here, so results cannot be deleted by accident.
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket                  = aws_s3_bucket.results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- IAM: only what Locust and the controller need ---------------------------

resource "aws_iam_role" "loadgen" {
  name = "${local.name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# Session Manager access: no SSH key, no open inbound port
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.loadgen.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "experiment" {
  name = "${local.name}-experiment"
  role = aws_iam_role.loadgen.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeSandbox"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = [local.function_arn, local.alias_arn]
      },
      {
        Sid    = "ControllerProvisionedConcurrency"
        Effect = "Allow"
        Action = [
          "lambda:PutProvisionedConcurrencyConfig",
          "lambda:GetProvisionedConcurrencyConfig",
          "lambda:DeleteProvisionedConcurrencyConfig",
          "lambda:ListProvisionedConcurrencyConfigs",
        ]
        Resource = [local.function_arn, local.alias_arn]
      },
      {
        # Start protocol: run_experiment.sh publishes a fresh version and points the
        # alias at it, so every run starts with no warm environments (Known issue 12)
        Sid    = "StartProtocolFreshVersion"
        Effect = "Allow"
        Action = [
          "lambda:GetFunctionConfiguration",
          "lambda:UpdateFunctionConfiguration",
          "lambda:PublishVersion",
          "lambda:GetAlias",
          "lambda:UpdateAlias",
        ]
        Resource = [local.function_arn, local.alias_arn]
      },
      {
        Sid      = "ReadMetrics" # GetMetricData has no resource-level permissions
        Effect   = "Allow"
        Action   = "cloudwatch:GetMetricData"
        Resource = "*"
      },
      {
        Sid      = "Results"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.results.arn, "${aws_s3_bucket.results.arn}/*"]
      },
    ]
  })
}

resource "aws_iam_instance_profile" "loadgen" {
  name = "${local.name}-profile"
  role = aws_iam_role.loadgen.name
}

# --- Instance -----------------------------------------------------------------

resource "aws_security_group" "loadgen" {
  name        = "${local.name}-sg"
  description = "No inbound; outbound for AWS APIs, dnf, pip and git"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "loadgen" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.loadgen.id]
  iam_instance_profile        = aws_iam_instance_profile.loadgen.name
  associate_public_ip_address = true # outbound internet via the default VPC's gateway

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 20 # GiB; invoke logs are ~150 MB per 90-minute run
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url       = var.repo_url
    python_version = var.python_version
    region         = var.region
    bucket         = aws_s3_bucket.results.bucket
  })

  tags = { Name = local.name }

  lifecycle {
    # A newer AL2023 AMI must not replace the instance mid-experiment, and a stopped
    # instance reads back with no public IP, which would otherwise force a replacement
    ignore_changes = [ami, associate_public_ip_address]
  }
}
