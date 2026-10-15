output "instance_id" {
  value = aws_instance.loadgen.id
}

output "results_bucket" {
  value = aws_s3_bucket.results.bucket
}

output "connect" {
  description = "Open a shell on the instance (needs the Session Manager plugin locally)"
  value       = "aws ssm start-session --target ${aws_instance.loadgen.id} --region ${var.region}"
}
