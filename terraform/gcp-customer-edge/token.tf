# Node registration token.
#
# Must be type JWT (not NORMAL). The JWT embeds the site name and tenant, which
# is why the SMSv2 cloud-init needs nothing but `token:`.
#
# The value handed to the node is `.content`, NOT `.id`.
# `.id` is "<namespace>/<name>" -- a node booted with that never registers.
# This is a real bug in at least one widely-copied community example.

resource "f5xc_token" "ce" {
  name      = "${local.name}-token"
  namespace = var.xc_namespace

  description = "JWT node registration token for ${local.name}"

  type      = ["JWT"]
  site_name = f5xc_securemesh_site_v2.ce.name
}
