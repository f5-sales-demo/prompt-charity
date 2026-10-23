# GCP's implied rules are: egress allow-all, ingress deny-all.
#
# The CE initiates every connection it needs and those are stateful, so the
# implied egress rule is already sufficient in a default project. The explicit
# rules below exist so this still works in a project that has a default-deny
# egress policy -- common in enterprise projects, and otherwise the cause of a
# CE that boots fine and silently never registers.
#
# Reference: "F5 Customer Edge IP Address and Domain Reference for Firewall or
# Proxy Settings", section "Secure Mesh v2 CE Sites".

locals {
  # Worldwide Secure Mesh v2 ranges checked 2026-10-22. TCP and UDP differ.
  re_ranges_tcp = [
    "5.182.215.0/25",
    "84.54.61.0/25",
    "23.158.32.0/25",
    "84.54.62.0/25",
    "185.94.143.0/25",
    "185.94.142.0/24",
    "159.60.190.0/24",
    "159.60.168.0/24",
    "159.60.180.0/24",
    "159.60.174.0/24",
    "159.60.175.0/24",
    "159.60.176.0/24",
    "159.60.177.0/24",
    "159.60.179.0/24",
    "159.60.181.0/24",
    "159.60.183.0/24",
    "5.182.213.0/24",
    "5.182.212.0/25",
    "5.182.214.0/25",
    "84.54.60.0/25",
    "185.56.154.0/25",
    "159.60.160.0/24",
    "159.60.161.0/24",
    "159.60.162.0/24",
    "159.60.163.0/24",
    "159.60.188.0/24",
    "159.60.182.0/24",
    "159.60.178.0/24",
    "103.135.56.0/24",
    "103.135.57.0/25",
    "103.135.59.0/25",
    "103.135.58.0/24",
    "159.60.189.0/24",
    "159.60.166.0/24",
    "159.60.164.0/24",
    "159.60.170.0/24",
    "159.60.172.0/24",
    "159.60.191.0/24",
    "159.60.184.0/24",
    "159.60.185.0/24",
    "159.60.186.0/24",
  ]
  re_ranges_udp = [
    "5.182.215.0/25",
    "84.54.61.0/25",
    "23.158.32.0/25",
    "84.54.62.0/25",
    "185.94.143.0/25",
    "185.94.142.0/24",
    "159.60.190.0/24",
    "159.60.168.0/24",
    "159.60.180.0/24",
    "159.60.174.0/24",
    "159.60.175.0/24",
    "159.60.176.0/24",
    "159.60.177.0/24",
    "159.60.179.0/24",
    "159.60.181.0/24",
    "159.60.183.0/24",
    "5.182.213.0/24",
    "5.182.212.0/25",
    "5.182.214.0/25",
    "84.54.60.0/25",
    "185.56.154.0/25",
    "159.60.160.0/24",
    "159.60.161.0/24",
    "159.60.162.0/24",
    "159.60.163.0/24",
    "159.60.188.0/24",
    "159.60.182.0/24",
    "159.60.178.0/24",
    "103.135.56.0/24",
    "103.135.57.0/25",
    "103.135.59.0/25",
    "103.135.58.0/24",
    "159.60.189.0/24",
    "159.60.166.0/24",
    "159.60.164.0/24",
    "159.60.170.0/24",
    "159.60.172.0/24",
    "159.60.184.0/24",
    "159.60.185.0/24",
    "159.60.186.0/24",
  ]

  ce_tag = local.name
}

# Site registration and updates.
resource "google_compute_firewall" "slo_egress_registration" {
  name               = "${local.name}-slo-egress-registration"
  network            = google_compute_network.slo.id
  direction          = "EGRESS"
  priority           = 1000
  destination_ranges = ["159.60.141.140/32"]
  target_tags        = [local.ce_tag]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

# Regional Edge tunnels. UDP 500 and ESP are deliberately NOT opened -- those
# are only needed for CE-to-CE Site Mesh Group connectivity, which a single
# site does not have.
resource "google_compute_firewall" "slo_egress_re_tcp" {
  name               = "${local.name}-slo-egress-re-tcp"
  network            = google_compute_network.slo.id
  direction          = "EGRESS"
  priority           = 1000
  destination_ranges = local.re_ranges_tcp
  target_tags        = [local.ce_tag]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}
resource "google_compute_firewall" "slo_egress_re_udp" {
  name               = "${local.name}-slo-egress-re-udp"
  network            = google_compute_network.slo.id
  direction          = "EGRESS"
  priority           = 1000
  destination_ranges = local.re_ranges_udp
  target_tags        = [local.ce_tag]

  allow {
    protocol = "udp"
    ports    = ["4500", "123"]
  }
}

# Software download, image pull, blindfold, identity authority. These are
# *.volterra.io FQDNs behind CDNs with no stable IP set, so 443 is open wide.
resource "google_compute_firewall" "slo_egress_https" {
  name               = "${local.name}-slo-egress-https"
  network            = google_compute_network.slo.id
  direction          = "EGRESS"
  priority           = 1100
  destination_ranges = ["0.0.0.0/0"]
  target_tags        = [local.ce_tag]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

# DNS (8.8.8.8 / 8.8.4.4) and NTP (time.google.com) -- the SMSv2 defaults.
resource "google_compute_firewall" "slo_egress_dns_ntp" {
  name      = "${local.name}-slo-egress-dns-ntp"
  network   = google_compute_network.slo.id
  direction = "EGRESS"
  priority  = 1000
  destination_ranges = [
    "8.8.8.8/32", "8.8.4.4/32",
    "216.239.35.0/32", "216.239.35.4/32", "216.239.35.8/32", "216.239.35.12/32",
  ]
  target_tags = [local.ce_tag]

  allow {
    protocol = "udp"
    ports    = ["53", "123"]
  }

  allow {
    protocol = "tcp"
    ports    = ["53"]
  }
}

# Nothing inbound is required for registration: the CE dials out and return
# traffic is stateful. SSH is optional break-glass only.
resource "google_compute_firewall" "slo_ingress_ssh" {
  count = length(var.ssh_source_ranges) > 0 ? 1 : 0

  name          = "${local.name}-slo-ingress-ssh"
  network       = google_compute_network.slo.id
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = var.ssh_source_ranges
  target_tags   = [local.ce_tag]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
