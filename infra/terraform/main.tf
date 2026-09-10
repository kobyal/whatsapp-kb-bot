data "aws_caller_identity" "current" {}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  brain_name = "${var.name_prefix}-brain"
  table_name = "${var.name_prefix}-kb-entries"
}
