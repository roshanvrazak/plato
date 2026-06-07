provider "aws" {
  region = "eu-west-2"
  default_tags {
    tags = {
      Environment = "dev"
      Project     = "plato"
      ManagedBy   = "terraform"
    }
  }
}

module "example_bucket" {
  source = "../../modules/example-bucket"

  name        = var.bucket_name
  environment = "dev"
  versioning_enabled = false  
}

variable "bucket_name" {
  type = string
}

output "bucket_id" {
  value = module.example_bucket.bucket_id
}

