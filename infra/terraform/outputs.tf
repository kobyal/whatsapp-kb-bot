output "instance_id" {
  value = aws_instance.listener.id
}

output "brain_function" {
  value = aws_lambda_function.brain.function_name
}

output "kb_tables" {
  value = { for id, t in aws_dynamodb_table.kb : id => t.name }
}

output "convo_table" {
  value = aws_dynamodb_table.convo.name
}

output "next_steps" {
  value = <<-EOT

    1. Publish the KB(s):  %{for id in local.tenant_ids~}KB_TENANT=${id} python3 kb/publish.py --table-prefix ${var.name_prefix}-kb- --region ${var.aws_region}
                           %{endfor~}
    2. Test the brain:     scripts/ask.sh ${aws_lambda_function.brain.function_name} "my vpn keeps disconnecting"
    3. Link WhatsApp:      scripts/qr.sh ${aws_instance.listener.id}   then open http://localhost:8090
    4. Watch the logs:     scripts/logs.sh ${aws_instance.listener.id}
  EOT
}
