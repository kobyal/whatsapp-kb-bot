# The knowledge base the brain reads at runtime. kb/publish.py fills it from kb/kb.json.
# On-demand billing: a support bot does a handful of scans a minute at most.
resource "aws_dynamodb_table" "kb" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery { enabled = true }
}
