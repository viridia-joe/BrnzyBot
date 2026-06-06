terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ── Static external IP ───────────────────────────────────────────────────────
# A reserved static IP doesn't change across VM restarts or re-creates.
# This is the address you put in GitHub secrets as GCE_HOST.
resource "google_compute_address" "brnzybot" {
  name   = "${var.instance_name}-ip"
  region = var.region
}

# ── VM instance ──────────────────────────────────────────────────────────────
# e2-micro in us-central1/us-east1/us-west1 is free-tier eligible:
#   - 1 vCPU, 1 GB RAM
#   - Up to 720 hours/month free
#   - 30 GB standard disk free
resource "google_compute_instance" "brnzybot" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = var.boot_disk_size   # GB — 30 GB total is free-tier
      type  = "pd-standard"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.brnzybot.address
    }
  }

  # Your public SSH key — set in terraform.tfvars (see variables.tf)
  metadata = {
    ssh-keys = "${var.ssh_user}:${var.ssh_public_key}"
  }

  # Bootstraps Docker + creates the brnz user on first boot (~2 min)
  metadata_startup_script = file("${path.module}/startup.sh")

  tags = [var.instance_name]

  # Grant the VM's service account permission to write to Cloud Logging and Monitoring.
  # Without this the gcplogs Docker driver fails with "Unauthenticated".
  service_account {
    scopes = [
      "logging-write",
      "monitoring-write",
      "storage-ro",
    ]
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }
}

# ── Firewall: allow SSH ──────────────────────────────────────────────────────
# Only SSH needs to be open. The webhook uses Cloudflare Tunnel (outbound
# connection from the container to Cloudflare) — no inbound HTTP port needed.
resource "google_compute_firewall" "allow-ssh" {
  name    = "${var.instance_name}-allow-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.instance_name]
}
