terraform {
  required_version = ">= 1.5.0"

  required_providers {
    f5xc = {
      source = "registry.terraform.io/F5Networks/f5xc"
      # Discovery must add version = "= <exact latest preview version>" before init.
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
