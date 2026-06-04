output "vm_external_ip" {
  description = "External IP of the VM — save this as the GCE_HOST secret in GitHub"
  value       = google_compute_address.brnzybot.address
}

output "ssh_command" {
  description = "SSH command to log into the VM"
  value       = "ssh ${var.ssh_user}@${google_compute_address.brnzybot.address}"
}
