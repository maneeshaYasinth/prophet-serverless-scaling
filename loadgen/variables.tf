variable "region" {
  description = "Same region as sandbox-lambda, so client latency to Lambda is a few ms"
  type        = string
  default     = "ap-south-1"
}

variable "function_name" {
  description = "Lambda the load generator may invoke and whose Provisioned Concurrency the controller may set"
  type        = string
  default     = "sandbox-lambda"
}

variable "alias_name" {
  description = "Alias Locust invokes and Provisioned Concurrency attaches to"
  type        = string
  default     = "prod"
}

variable "instance_type" {
  description = "Non-burstable on purpose: a t3 instance runs out of CPU credits during a 90-minute run and throttles, which is the failure this instance exists to remove. c7i-flex.large is the non-burstable type the account's Free plan allows (c6i.large is rejected)."
  type        = string
  default     = "c7i-flex.large"
}

variable "repo_url" {
  description = "Public repository cloned onto the instance (git pull to update)"
  type        = string
  default     = "https://github.com/maneeshaYasinth/prophet-serverless-scaling.git"
}

variable "python_version" {
  description = "Python package available on Amazon Linux 2023"
  type        = string
  default     = "3.11"
}
