output "site_name" {
  description = "Name of the Secure Mesh Site v2 object in F5XC."
  value       = f5xc_securemesh_site_v2.ce.name
}

output "node_name" {
  description = "Name of the CE instance in GCP."
  value       = google_compute_instance.ce.name
}

output "slo_internal_ip" {
  description = "SLO (outside) internal IP of the CE node."
  value       = google_compute_instance.ce.network_interface[0].network_ip
}

output "sli_internal_ip" {
  description = "SLI (inside) internal IP of the CE node."
  value       = google_compute_instance.ce.network_interface[1].network_ip
}

output "console_url" {
  description = "Direct link to this site in the F5XC console."
  value       = "https://${local.tenant_host}/web/workspaces/multi-cloud-network-connect/sites/sites/${f5xc_securemesh_site_v2.ce.name}"
}
