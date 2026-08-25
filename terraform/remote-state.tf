# Esse arquivo vai ler o state produzido pelo oficina-infra-k8s.
data "terraform_remote_state" "infra_k8s" {
  backend = "s3"

  config = {
    bucket = "oficina-state-priess951"
    key    = "infra/k8s/terraform.tfstate"
    region = "us-east-1"
  }
}