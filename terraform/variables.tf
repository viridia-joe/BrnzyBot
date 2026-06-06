variable "project_id" {
  description = "Your GCP project ID (visible in the GCP Console header)"
  type        = string
}

variable "region" {
  description = "GCP region — must be us-central1, us-east1, or us-west1 to qualify for the free tier e2-micro"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone within the region"
  type        = string
  default     = "us-central1-a"
}

variable "ssh_user" {
  description = "Linux username created on the VM (used for SSH and file ownership)"
  type        = string
  default     = "brnz"
}

variable "ssh_public_key" {
  description = "Contents of your SSH public key (e.g. the output of `cat ~/.ssh/id_rsa.pub` or `cat ~/.ssh/id_ed25519.pub`)"
  type        = string
}

# ── Per-instance naming — set a distinct name to stand up a SECOND instance ──
# (e.g. instance_name = "brnzybot-prod") so its VM, static IP, firewall rule and
# network tag don't collide with the dev instance in the same project.
variable "instance_name" {
  description = "Base name for this instance's VM, static IP, firewall rule and tag"
  type        = string
  default     = "brnzybot"
}

# ── Box size — bump for the paid/LLM tier (e.g. "e2-standard-2") ─────────────
# e2-micro is free-tier eligible; larger types are billed.
variable "machine_type" {
  description = "GCE machine type. e2-micro = free tier; larger = billed (LLM tier)"
  type        = string
  default     = "e2-micro"
}

variable "boot_disk_size" {
  description = "Boot disk size in GB (30 GB total is free-tier)"
  type        = number
  default     = 20
}
