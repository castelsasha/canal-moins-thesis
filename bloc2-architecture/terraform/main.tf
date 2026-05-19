###############################################################################
# Canal Moins — Data Platform Infrastructure
# Terraform main.tf
# Block 2 — Cloud Architecture | JHEDA Master Thesis
###############################################################################

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "canal-moins-thesis"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "data-team"
    }
  }
}

###############################################################################
# VPC & NETWORKING
###############################################################################

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.project}-public-a" }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.project}-public-b" }
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.10.0/24"
  availability_zone = "${var.aws_region}a"
  tags              = { Name = "${var.project}-private-a" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${var.project}-public-rt" }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

###############################################################################
# SECURITY GROUPS
###############################################################################

resource "aws_security_group" "redshift" {
  name        = "${var.project}-redshift-sg"
  description = "Canal Moins Redshift cluster"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 5439
    to_port     = 5439
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
    description = "Redshift port — internal VPC only"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-redshift-sg" }
}

###############################################################################
# S3 BUCKETS — MEDALLION ARCHITECTURE
###############################################################################

# Bronze — raw ingestion
resource "aws_s3_bucket" "bronze" {
  bucket        = "${var.project}-bronze-${var.environment}"
  force_destroy = true
  tags          = { Layer = "bronze", Description = "Raw events — immutable landing zone" }
}

resource "aws_s3_bucket_versioning" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Silver — cleaned & validated
resource "aws_s3_bucket" "silver" {
  bucket        = "${var.project}-silver-${var.environment}"
  force_destroy = true
  tags          = { Layer = "silver", Description = "Cleaned and validated data" }
}

resource "aws_s3_bucket_versioning" "silver" {
  bucket = aws_s3_bucket.silver.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "silver" {
  bucket = aws_s3_bucket.silver.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# Gold — analytics-ready
resource "aws_s3_bucket" "gold" {
  bucket        = "${var.project}-gold-${var.environment}"
  force_destroy = true
  tags          = { Layer = "gold", Description = "Analytics-ready serving layer" }
}

resource "aws_s3_bucket_versioning" "gold" {
  bucket = aws_s3_bucket.gold.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "gold" {
  bucket = aws_s3_bucket.gold.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# Logs bucket
resource "aws_s3_bucket" "logs" {
  bucket        = "${var.project}-logs-${var.environment}"
  force_destroy = true
  tags          = { Layer = "logs" }
}

###############################################################################
# IAM ROLES
###############################################################################

# Glue service role
resource "aws_iam_role" "glue" {
  name = "${var.project}-glue-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${var.project}-glue-s3-policy"
  role = aws_iam_role.glue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.bronze.arn, "${aws_s3_bucket.bronze.arn}/*",
        aws_s3_bucket.silver.arn, "${aws_s3_bucket.silver.arn}/*",
        aws_s3_bucket.gold.arn,   "${aws_s3_bucket.gold.arn}/*",
      ]
    }]
  })
}

# Redshift service role
resource "aws_iam_role" "redshift" {
  name = "${var.project}-redshift-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "redshift.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "redshift_s3" {
  name = "${var.project}-redshift-s3-policy"
  role = aws_iam_role.redshift.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.gold.arn, "${aws_s3_bucket.gold.arn}/*"]
    }]
  })
}

###############################################################################
# GLUE DATA CATALOG
###############################################################################

resource "aws_glue_catalog_database" "bronze" {
  name        = "${var.project}_bronze"
  description = "Canal Moins Bronze layer — raw events"
}

resource "aws_glue_catalog_database" "silver" {
  name        = "${var.project}_silver"
  description = "Canal Moins Silver layer — cleaned data"
}

resource "aws_glue_catalog_database" "gold" {
  name        = "${var.project}_gold"
  description = "Canal Moins Gold layer — analytics-ready"
}

# Glue crawler — Bronze S3
resource "aws_glue_crawler" "bronze_events" {
  name          = "${var.project}-bronze-events-crawler"
  database_name = aws_glue_catalog_database.bronze.name
  role          = aws_iam_role.glue.arn
  description   = "Crawls raw viewing events from S3 Bronze bucket"
  schedule      = "cron(0 * * * ? *)"  # hourly

  s3_target {
    path = "s3://${aws_s3_bucket.bronze.bucket}/viewing_events/"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
  })
}

###############################################################################
# REDSHIFT CLUSTER
###############################################################################

resource "aws_redshift_subnet_group" "main" {
  name       = "${var.project}-subnet-group"
  subnet_ids = [aws_subnet.public_a.id, aws_subnet.public_b.id]
  tags       = { Name = "${var.project}-redshift-subnet-group" }
}

resource "aws_redshift_cluster" "main" {
  cluster_identifier        = "${var.project}-cluster"
  database_name             = "canalmoins"
  master_username           = var.redshift_username
  master_password           = var.redshift_password
  node_type                 = "dc2.large"
  cluster_type              = "single-node"
  number_of_nodes           = 1
  vpc_security_group_ids    = [aws_security_group.redshift.id]
  cluster_subnet_group_name = aws_redshift_subnet_group.main.name
  iam_roles                 = [aws_iam_role.redshift.arn]
  encrypted                 = true
  skip_final_snapshot       = true
  publicly_accessible       = false

  tags = { Name = "${var.project}-redshift" }
}

###############################################################################
# CLOUDWATCH ALARMS
###############################################################################

resource "aws_cloudwatch_metric_alarm" "redshift_cpu" {
  alarm_name          = "${var.project}-redshift-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/Redshift"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "Redshift CPU > 80% for 10 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterIdentifier = aws_redshift_cluster.main.cluster_identifier
  }
}

resource "aws_cloudwatch_log_group" "glue" {
  name              = "/aws/glue/${var.project}"
  retention_in_days = 30
}
