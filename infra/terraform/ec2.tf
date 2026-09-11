# The always-on half. A linked WhatsApp device is a persistent socket, so this cannot be a
# Lambda; a t3.small is plenty. Everything the box needs is installed by user-data from
# the git repo, so replacing the instance is `terraform taint` away.
resource "aws_instance" "listener" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.listener.id]
  iam_instance_profile        = aws_iam_instance_profile.listener.name
  associate_public_ip_address = true
  disable_api_termination     = var.disable_api_termination
  disable_api_stop            = var.disable_api_stop

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 16
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    repo_url       = var.repo_url
    git_ref        = var.git_ref
    brain_function = aws_lambda_function.brain.function_name
    aws_region     = var.aws_region
    allowed_groups = join(",", var.allowed_groups)
    allow_dms      = var.allow_dms ? "1" : "0"
  })
  user_data_replace_on_change = true

  tags = { Name = "${var.name_prefix}-listener" }

  # The AMI comes from the "latest AL2023" SSM parameter, which changes every few weeks.
  # Without this, a routine apply would replace the instance and drop the WhatsApp session.
  lifecycle {
    ignore_changes = [ami]
  }
}
