variable "gcp_project_id" {
  description = "Existing GCP project to deploy the CE into."
  type        = string
}

variable "gcp_region" {
  description = "GCP region for the VPC subnets and the CE instance."
  type        = string
}

variable "gcp_zone" {
  description = "GCP zone for the CE instance. Must be inside var.gcp_region."
  type        = string
}

variable "name_prefix" {
  description = <<-EOT
    Prefix for every created object. A random suffix is appended so repeated
    PoC runs cannot collide in a shared project or a shared XC tenant.
  EOT
  type        = string
  default     = "ce-poc-gcp"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]*[a-z0-9])?$", var.name_prefix))
    error_message = "name_prefix must be DNS-1035: start with a letter, then lowercase letters, digits or dashes."
  }
}

variable "slo_cidr" {
  description = "CIDR for the SLO (outside) subnet. Must not overlap sli_cidr."
  type        = string
}

variable "sli_cidr" {
  description = "CIDR for the SLI (inside) subnet. Must not overlap slo_cidr."
  type        = string
}

variable "machine_type" {
  description = <<-EOT
    CE machine type. Minimum supported size is 8 vCPU / 32 GB.
    Prefer n2-* over t2d-*: n2 has AVX-512, which F5 requires if you ever
    enable the Distributed Cloud WAF on this site.
  EOT
  type        = string
  default     = "n2-standard-8"
}

variable "boot_disk_size_gb" {
  description = "CE boot disk size in GB. Default 120 reserves 50% above F5's 80 GB minimum; increase for newer image or sizing requirements."
  type        = number
  default     = 120

  validation {
    condition     = var.boot_disk_size_gb >= 120 && var.boot_disk_size_gb == floor(var.boot_disk_size_gb)
    error_message = "Use a whole-number boot disk size of at least 120 GB to preserve operating and upgrade headroom."
  }
}

variable "boot_disk_type" {
  description = "Boot disk type. F5's doc says pd-standard; pd-balanced is the pragmatic choice."
  type        = string
  default     = "pd-balanced"
}

variable "ce_image" {
  description = <<-EOT
    Fully-qualified CE image to boot.

    PINNED ON PURPOSE. F5 publishes NO image family for CE images, and image
    creation timestamps are NOT in version order -- f5xc-ce-crt-20251002-0027-byol
    was created AFTER f5xc-ce-crt-20260201-byol. A `most_recent = true` lookup
    can therefore silently select an older software build. Pin it, bump deliberately.

    To see what is currently published:
      gcloud compute images list --project=f5-7626-networks-public \
        --filter="name~'^f5xc-ce-crt-'" --no-standard-images \
        --format="table(name,creationTimestamp)" --sort-by=creationTimestamp
  EOT
  type        = string
}

variable "xc_namespace" {
  description = "XC namespace for the site object. Site objects live in `system`."
  type        = string
  default     = "system"
}

variable "xc_api_url" {
  description = "F5XC tenant API URL. Used only to build a clickable console link in the outputs."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "Optional SSH public key for break-glass access. Not required for registration."
  type        = string
  default     = ""
}

variable "ssh_source_ranges" {
  description = "Source CIDRs allowed to SSH to the CE. Empty list disables the rule."
  type        = list(string)
  default     = []
}
