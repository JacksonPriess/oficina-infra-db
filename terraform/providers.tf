terraform {
  # Trava a versão do Terraform para ser compatível com a que você instalou (1.15.6)
  required_version = ">= 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

  }
}

# Configuração do provedor de nuvem com o perfil "pos" e a região "us-east-1", trava de segurança
provider "aws" {
  region = "us-east-1"
  # profile = "pos"
}