locals {
  # SMSv2 cloud-init. This is the entire payload for a DHCP dual-NIC GCP node.
  #
  # Do NOT use the SMSv1 shape (/etc/vpm/config.yaml with nested Vpm:/Kubernetes:
  # keys, ClusterName, Latitude, Longitude, CertifiedHardwareEndpoint).
  ce_user_data = <<-EOT
    #cloud-config
    write_files:
      - path: /etc/vpm/user_data
        permissions: "0600"
        owner: root
        content: |
          token: ${sensitive(f5xc_token.ce.content)}
    runcmd:
      - |
        {
          printf 'CE_DISK_DIAGNOSTICS_BEGIN\n'
          df -Pk / /var /var/lib /var/log
          lsblk -b -o NAME,SIZE,TYPE,MOUNTPOINT
          printf 'CE_DISK_DIAGNOSTICS_END\n'
        } > /dev/console 2>&1
  EOT
}

resource "google_compute_instance" "ce" {
  #checkov:skip=CKV_GCP_36:IP forwarding is required for the CE router.
  #checkov:skip=CKV_GCP_38:Disposable test CE uses Google-managed disk encryption; customer-supplied keys are outside this PoC.
  #checkov:skip=CKV_GCP_39:The pinned CE image lacks UEFI_COMPATIBLE; Shielded VM is unsupported.
  name         = local.name
  machine_type = var.machine_type
  zone         = var.gcp_zone

  # Required. The CE is a router: it forwards packets whose source/destination
  # is not its own IP. Without this GCP silently drops that traffic and the
  # SLI -> SLO path does not work. Many public examples omit it.
  can_ip_forward = true

  tags = [local.ce_tag]

  boot_disk {
    initialize_params {
      image = var.ce_image
      size  = var.boot_disk_size_gb
      type  = var.boot_disk_type
    }
  }

  # NIC ORDER IS THE CONTRACT.
  #   nic0 (first block)  -> ens4 in the guest -> SLO
  #   nic1 (second block) -> ens5 in the guest -> SLI
  #
  # There is no NIC-role setting in the cloud-init; interface ORDER assigns the
  # roles. The node self-reports both interfaces on registration and F5XC fills
  # in node_list with the correct SLO/SLI roles -- verified on a real run. This
  # is why node_list is deliberately NOT declared in site.tf.
  #
  # Note the guest device names are ens4/ens5 (predictable network interface
  # naming), not eth0/eth1.
  #
  # No access_config block: the node has no external IP and egresses via Cloud NAT.
  network_interface {
    subnetwork = google_compute_subnetwork.slo.id
  }

  network_interface {
    subnetwork = google_compute_subnetwork.sli.id
  }

  metadata = {
    user-data = local.ce_user_data

    # GCP's valid values are GlobalDefault, ZonalOnly and ZonalPreferred.
    # Some F5 docs print "ZonePreferred", which is not valid -- GCP ignores
    # unrecognised values and falls back to the project default.
    VmDnsSetting = "ZonalPreferred"

    # Optional SSH must not inherit project-wide public keys.
    block-project-ssh-keys = "true"

    ssh-keys = var.ssh_public_key != "" ? "admin:${var.ssh_public_key}" : null
  }

  # Shielded VM is deliberately not configured: the CE images do not carry the
  # UEFI_COMPATIBLE guest OS feature, so it cannot be enabled.

  lifecycle {
    # The user-data carries a JWT that changes whenever the token is replaced.
    # Without this, a plan after token rotation would destroy and recreate a
    # perfectly healthy CE.
    ignore_changes = [metadata["user-data"]]
  }

  depends_on = [
    f5xc_securemesh_site_v2.ce,
    f5xc_token.ce,
    google_compute_router_nat.slo,
  ]
}
