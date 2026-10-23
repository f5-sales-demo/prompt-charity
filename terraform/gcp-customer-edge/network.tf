# A GCP VM cannot have two NICs on the same VPC network, so a dual-NIC CE
# requires two separate VPCs: one for SLO (outside) and one for SLI (inside).

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  name = "${var.name_prefix}-${random_id.suffix.hex}"

  # Console host, derived from the API URL so the output link is clickable.
  tenant_host = replace(replace(trimsuffix(trimsuffix(var.xc_api_url, "/"), "/api"), "https://", ""), "http://", "")
}

# ---------- SLO (outside) ----------

resource "google_compute_network" "slo" {
  name                    = "${local.name}-slo-vpc"
  auto_create_subnetworks = false
  description             = "SLO (outside) network for F5XC CE ${local.name}"
}

resource "google_compute_subnetwork" "slo" {
  name          = "${local.name}-slo-subnet"
  ip_cidr_range = var.slo_cidr
  region        = var.gcp_region
  network       = google_compute_network.slo.id
}

# ---------- SLI (inside) ----------

resource "google_compute_network" "sli" {
  name                    = "${local.name}-sli-vpc"
  auto_create_subnetworks = false
  description             = "SLI (inside) network for F5XC CE ${local.name}"
}

resource "google_compute_subnetwork" "sli" {
  name          = "${local.name}-sli-subnet"
  ip_cidr_range = var.sli_cidr
  region        = var.gcp_region
  network       = google_compute_network.sli.id
}

# ---------- Egress for registration ----------
#
# The CE has no external IP. All outbound traffic (registration, RE tunnels,
# DNS, NTP, software download during provisioning) leaves through Cloud NAT on
# the SLO network. Without this the node boots but never registers.

resource "google_compute_router" "slo" {
  name    = "${local.name}-slo-router"
  region  = var.gcp_region
  network = google_compute_network.slo.id
}

resource "google_compute_router_nat" "slo" {
  name                               = "${local.name}-slo-nat"
  router                             = google_compute_router.slo.name
  region                             = var.gcp_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.slo.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
