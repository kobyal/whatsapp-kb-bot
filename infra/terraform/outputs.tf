output "instance_id" {
  value = aws_instance.listener.id
}

output "brain_function" {
  value = aws_lambda_function.brain.function_name
}

output "kb_table" {
  value = aws_dynamodb_table.kb.name
}

output "next_steps" {
  value = <<-EOT

    1. Publish the KB:     python3 kb/publish.py --table ${aws_dynamodb_table.kb.name} --region ${var.aws_region}
    2. Test the brain:     scripts/ask.sh ${aws_lambda_function.brain.function_name} "my vpn keeps disconnecting"
    3. Link WhatsApp:      scripts/qr.sh ${aws_instance.listener.id}   then open http://localhost:8090
    4. Watch the logs:     scripts/logs.sh ${aws_instance.listener.id}
  EOT
}
