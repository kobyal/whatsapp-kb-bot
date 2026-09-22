# One knowledge-base table per tenant (folder under tenants/). kb/publish.py fills each from
# its kb.json. On-demand billing: a support bot does a handful of scans a minute at most.
resource "aws_dynamodb_table" "kb" {
  for_each     = local.tenant_ids
  name         = "${var.name_prefix}-kb-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery { enabled = true }
}

# Per-conversation state, shared by all tenants: the remembered clarifying question and its
# rate limit (`<jid>#<participant>`), the supporter-activity window (`<jid>#__supporter__`),
# and the 1:1 tenant choice (`dmpref#<user>`). Rows expire through the TTL attribute; nothing
# sweeps this table. DynamoDB deletes expired items only eventually, so the brain never treats
# "row exists" as "still inside the window".
resource "aws_dynamodb_table" "convo" {
  name         = "${var.name_prefix}-convo-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "convo"

  attribute {
    name = "convo"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
