variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-south-1"
}

variable "function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "claude-yt-companion"
}

variable "secret_name" {
  description = "Secrets Manager secret name holding the Bearer token"
  type        = string
  default     = "youtube-transcript/bearer-token"
}

variable "tfstate_bucket" {
  description = "S3 bucket name for Terraform remote state"
  type        = string
}

variable "tfstate_table" {
  description = "DynamoDB table name for Terraform state locking"
  type        = string
  default     = "terraform-state-lock"
}
