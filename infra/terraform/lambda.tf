# The brain. kb/kb.json is baked into the zip as a fallback snapshot so the function
# still answers if the table is unreachable, and so a fresh deploy works before the
# first publish.
data "archive_file" "brain" {
  type        = "zip"
  output_path = "${path.module}/build/brain.zip"

  source {
    content  = file("${path.module}/../../brain/lambda_function.py")
    filename = "lambda_function.py"
  }
  source {
    content  = file("${path.module}/../../kb/kb.json")
    filename = "kb.json"
  }
}

resource "aws_cloudwatch_log_group" "brain" {
  name              = "/aws/lambda/${local.brain_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "brain" {
  function_name    = local.brain_name
  description      = "WhatsApp KB bot brain: routes a message to a KB entry with Bedrock, or stays silent"
  role             = aws_iam_role.brain.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 512
  filename         = data.archive_file.brain.output_path
  source_code_hash = data.archive_file.brain.output_base64sha256

  environment {
    variables = {
      KB_TABLE       = aws_dynamodb_table.kb.name
      CLASSIFY_MODEL = var.classify_model
      VISION_MODEL   = var.vision_model
      MIN_CONFIDENCE = tostring(var.min_confidence)
      ANSWER_MODE    = var.answer_mode
      BOT_HEADER     = var.bot_header
    }
  }

  depends_on = [aws_iam_role_policy_attachment.brain_logs, aws_cloudwatch_log_group.brain]
}
