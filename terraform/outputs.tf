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