variable "name" {
  description = "Bucket name prefix"
  type        = string
}

variable "environment" {
  description = "Environment name, used for tagging"
  type        = string
}

variable "versioning_enabled" {
  description = "Whether to enable versioning"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}