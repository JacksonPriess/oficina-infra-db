terraform {
  backend "s3" {
    bucket = "oficina-state-priess952"
    key    = "infra/db/terraform.tfstate"
    region = "us-east-1"
  }
}