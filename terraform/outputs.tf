output "postgres_endpoint" {
  description = "Endpoint do banco PostgreSQL"
  value       = aws_db_instance.postgres.endpoint
}

output "postgres_port" {
  description = "Porta do PostgreSQL"
  value       = aws_db_instance.postgres.port
}

output "database_name" {
  description = "Nome do banco de dados"
  value       = aws_db_instance.postgres.db_name
}

output "database_secret_arn" {
  description = "ARN do secret gerenciado pelo RDS no AWS Secrets Manager"
  value       = try(aws_db_instance.postgres.master_user_secret[0].secret_arn, null)
}

output "postgres_address" {
  description = "Hostname do RDS, sem a porta"
  value       = aws_db_instance.postgres.address
}

output "nucleo_database_name" {
  description = "Banco logico do nucleo, preparado pelo bootstrap"
  value       = "oficina_db"
}

output "nucleo_database_username" {
  description = "Usuario do nucleo, preparado pelo bootstrap"
  value       = "nucleo_app"
}

output "produtos_database_name" {
  description = "Banco logico de produtos, preparado pelo bootstrap"
  value       = "oficina_produtos_db"
}

output "produtos_database_username" {
  description = "Usuario de produtos, preparado pelo bootstrap"
  value       = "catalogo_produto_app"
}
