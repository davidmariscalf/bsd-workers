output "worker_public_ips" {
  description = "Public IP addresses of the two Oracle BSD workers"
  value       = [for instance in oci_core_instance.bsd_worker : instance.public_ip]
}

output "worker_names" {
  description = "Oracle BSD worker instance names"
  value       = [for instance in oci_core_instance.bsd_worker : instance.display_name]
}
