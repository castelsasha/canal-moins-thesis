###############################################################################
# Canal Moins — Terraform Variables
###############################################################################

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-3"  # Paris — closest to Canal Moins subscribers
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "project" {
  description = "Project name — used as prefix for all resources"
  type        = string
  default     = "canal-moins"
}

variable "redshift_username" {
  description = "Redshift master username"
  type        = string
  default     = "admin"
  sensitive   = true
}

variable "redshift_password" {
  description = "Redshift master password (min 8 chars, 1 uppercase, 1 number)"
  type        = string
  sensitive   = true
}
