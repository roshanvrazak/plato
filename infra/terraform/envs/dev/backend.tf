terraform {
  required_version = ">= 1.5"
  backend "s3" {
    bucket         = "plato-tfstate-323690581633"
    key            = "envs/dev/terraform.tfstate"
    region         = "eu-west-2"
    dynamodb_table = "plato-tfstate-lock"
    encrypt        = true
  }
}