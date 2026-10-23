# NOTE: the argument is `url` (not `api_url`) and it MUST include the /api suffix.
# Credentials come from F5XCProvider_URL and F5XCProvider_API_TOKEN in the environment,
# keep credentials out of configuration; state and VM metadata remain private.
provider "f5xc" {
  timeout = "60s"

  # Back off politely if the tenant rate-limits us.
  throttling = {}
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
