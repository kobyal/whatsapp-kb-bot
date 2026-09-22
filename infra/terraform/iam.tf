# ---- EC2 listener role: SSM access + permission to invoke exactly one Lambda ----------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "listener" {
  name               = "${var.name_prefix}-listener"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "listener_ssm" {
  role       = aws_iam_role.listener.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "listener_invoke" {
  name = "invoke-brain"
  role = aws_iam_role.listener.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.brain.arn
    }]
  })
}

resource "aws_iam_instance_profile" "listener" {
  name = "${var.name_prefix}-listener"
  role = aws_iam_role.listener.name
}

# ---- Lambda brain role: logs, Bedrock invoke, read every KB table, read/write convo state --

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "brain" {
  name               = "${var.name_prefix}-brain"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "brain_logs" {
  role       = aws_iam_role.brain.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "brain" {
  name = "bedrock-kb-convo"
  role = aws_iam_role.brain.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Cross-region inference profiles (eu.*, us.*) resolve to foundation models in
        # several regions, so the foundation-model ARN is region-wildcarded on purpose.
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Scan"]
        Resource = [for t in aws_dynamodb_table.kb : t.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.convo.arn
      },
    ]
  })
}
