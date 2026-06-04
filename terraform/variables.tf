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
