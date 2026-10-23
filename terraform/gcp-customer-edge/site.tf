# Secure Mesh Site v2.
#
# SYNTAX: this provider is built on the Terraform Plugin Framework, so every
# nested structure is an ATTRIBUTE assigned with `=`, not an HCL block.

resource "f5xc_securemesh_site_v2" "ce" {
  name      = local.name
  namespace = var.xc_namespace

  description = "Dual-NIC CE proof of concept, created by Terraform"

  labels = {
    deployment = "poc"
  }

  # GCP supports exactly one orchestration mode: not_managed. F5XC will not
  # create the VM -- Terraform does, and the node registers itself. node_list
  # is populated by the API after registration, which is why it is not set here.
  provider_choice = {
    gcp = {
      orchestration_choice = {
        not_managed = {}
      }
    }
  }

  # Provider 0.9.7 documents this choice as "Enable all Node Local Services".
  # Disclose that policy during planning; the field name does not mean disabled.
  # Confirm selected-release semantics; GCP SSH access is approved separately.
  blocked_services_choice = {
    block_all_services = true
  }

  logs_receiver_choice = {
    logs_streaming_disabled = true
  }

  node_ha_choice = {
    disable_ha = true
  }

  dns_ntp_config = {
    dns_server_choice = { f5_dns_default = true }
    ntp_server_choice = { f5_ntp_default = true }
  }

  re_select = {
    re_selection_choice = {
      geo_proximity = true
    }
  }

  admin_user_credentials = {
    ssh_key = var.ssh_public_key
  }

  timeouts = {
    create = "30m"
    update = "30m"
    delete = "30m"
  }

  lifecycle {
    # REQUIRED FOR IDEMPOTENCY -- do not remove.
    #
    # Once the node registers, F5XC populates these four fields on the site
    # object from what the node reports about itself. Terraform did not set
    # them, so the next plan tries to remove them again.
    #
    # node_list (inside provider_choice) is the dangerous one: applying that
    # diff strips the node's discovered SLO/SLI interface configuration out of
    # the site object.
    #
    #   provider_choice           - contains node_list: the interfaces found at
    #                               registration (ens4 -> SLO, ens5 -> SLI)
    #   labels                    - hardware facts (hw-vendor, host-os-version, ...)
    #   operating_system_version  - actual OS version running on the node
    #   volterra_software_version - actual CE software version running
    ignore_changes = [
      provider_choice,
      labels,
      operating_system_version,
      volterra_software_version,
    ]
  }
}
