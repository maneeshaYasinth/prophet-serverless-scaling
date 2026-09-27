variable "region" {
  description = "AWS region to deploy the sandbox Lambda into"
  type        = string
  default     = "ap-south-1"
}

variable "function_name" {
  description = "Name of the sandbox Lambda function"
  type        = string
  default     = "sandbox-lambda"
}

variable "alias_name" {
  description = "Alias to publish, so Provisioned Concurrency has a qualifier to attach to"
  type        = string
  default     = "prod"
}

variable "simulated_init_delay_seconds" {
  description = "Artificial cold-start delay (seconds) baked into the handler, so PC pre-warming has something observable to prevent"
  type        = number
  default     = 3
}

variable "function_url_auth_type" {
  description = "Function URL auth type. AWS_IAM works around the new-account restriction on anonymous Function URL invocation; switch to NONE later if the restriction gets lifted and you want a plain public curl target."
  type        = string
  default     = "AWS_IAM"
}