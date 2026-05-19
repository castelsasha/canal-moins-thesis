###############################################################################
# Canal Moins — Terraform Outputs
###############################################################################

output "bronze_bucket_name" {
  description = "S3 Bronze bucket name"
  value       = aws_s3_bucket.bronze.bucket
}

output "silver_bucket_name" {
  description = "S3 Silver bucket name"
  value       = aws_s3_bucket.silver.bucket
}

output "gold_bucket_name" {
  description = "S3 Gold bucket name"
  value       = aws_s3_bucket.gold.bucket
}

output "redshift_endpoint" {
  description = "Redshift cluster endpoint"
  value       = aws_redshift_cluster.main.endpoint
  sensitive   = true
}

output "redshift_database" {
  description = "Redshift database name"
  value       = aws_redshift_cluster.main.database_name
}

output "glue_role_arn" {
  description = "Glue IAM role ARN"
  value       = aws_iam_role.glue.arn
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}
