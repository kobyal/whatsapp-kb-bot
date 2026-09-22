# The brain. tenants.json is assembled here from tenants/<id>/tenant.json + kb.json, exactly
# as brain/build.sh does it, and baked into the zip together with lambda_function.py. Each
# tenant's kb.json rides along as a fallback snapshot, so the function still answers if a
# table is unreachable and a fresh deploy works before the first publish.
locals {
  tenants_dir = "${path.module}/../../tenants"
  tenant_ids  = toset([for f in fileset(local.tenants_dir, "*/tenant.json") : dirname(f)])
  tenants = { for id in local.tenant_ids : id => merge(
    jsondecode(file("${local.tenants_dir}/${id}/tenant.json")),
    { snapshot = fileexists("${local.tenants_dir}/${id}/kb.json") ? jsondecode(file("${local.tenants_dir}/${id}/kb.json")).entries : [] }
  ) }
  tenants_json = jsonencode({ default = var.default_tenant, tenants = local.tenants })
}

data "archive_file" "brain" {
  type        = "zip"
  output_path = "${path.module}/build/brain.zip"

  source {
    content  = file("${path.module}/../../brain/lambda_function.py")
    filename = "lambda_function.py"
  }
  source {
    content  = local.tenants_json
    filename = "tenants.json"
  }
}

resource "aws_cloudwatch_log_group" "brain" {
  name              = "/aws/lambda/${local.brain_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "brain" {
  function_name    = local.brain_name
  description      = "WhatsApp KB bot brain: routes a message to a KB entry with Bedrock, asks one fixed question, or stays silent"
  role             = aws_iam_role.brain.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60 # every Bedrock call inside is bounded at 25 s read / 5 s connect
  memory_size      = 512
  filename         = data.archive_file.brain.output_path
  source_code_hash = data.archive_file.brain.output_base64sha256

  environment {
    variables = {
      KB_TABLE_PREFIX       = "${var.name_prefix}-kb-"
      CONVO_TABLE           = aws_dynamodb_table.convo.name
      DEFAULT_TENANT        = var.default_tenant
      CLASSIFY_MODEL        = var.classify_model
      VISION_MODEL          = var.vision_model
      MIN_CONFIDENCE        = tostring(var.min_confidence)
      CLARIFY_MIN_CANDIDATE = tostring(var.clarify_min_candidate)
      CLARIFY_ENABLED       = var.clarify_enabled ? "1" : "0"
      SUPPORTER_WINDOW      = tostring(var.supporter_window_seconds)
      ANSWER_MODE           = var.answer_mode
    }
  }

  lifecycle {
    precondition {
      condition     = contains(local.tenant_ids, var.default_tenant)
      error_message = "default_tenant must be one of the folders under tenants/ that has a tenant.json."
    }
  }

  depends_on = [aws_iam_role_policy_attachment.brain_logs, aws_cloudwatch_log_group.brain]
}
