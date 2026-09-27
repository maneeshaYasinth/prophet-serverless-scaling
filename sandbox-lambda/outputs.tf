output "function_name" {
  value = aws_lambda_function.sandbox.function_name
}

output "function_arn" {
  value = aws_lambda_function.sandbox.arn
}

output "alias_name" {
  value = aws_lambda_alias.prod.name
}

output "function_url" {
  description = "Public HTTPS endpoint -- point Locust's traffic_shapes.py at this"
  value       = aws_lambda_function_url.sandbox_url.function_url
}
