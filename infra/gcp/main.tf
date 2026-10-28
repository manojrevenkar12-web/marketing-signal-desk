# Signal Desk on Google Cloud, EU region: Cloud Run (web and task worker), Cloud SQL for
# PostgreSQL over private IP, Secret Manager for the app's and the ad platforms' secrets, and
# Cloud Scheduler to sync the sources every night. `terraform validate` runs in CI.

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

resource "google_service_account" "app" {
  account_id   = "signal-desk"
  display_name = "Signal Desk web and worker"
}

resource "google_project_iam_member" "app_sql" {
  project = var.project
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_compute_network" "vpc" {
  name                    = "signal-desk"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "app" {
  name                     = "signal-desk-app"
  ip_cidr_range            = "10.30.0.0/24"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql_range" {
  name          = "signal-desk-sql"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_range.name]
}

resource "google_sql_database_instance" "db" {
  name                = "signal-desk"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = true
  depends_on          = [google_service_networking_connection.sql]

  settings {
    tier              = var.db_tier
    availability_type = "REGIONAL"
    disk_autoresize   = true
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
  }
}

resource "google_sql_database" "app" {
  name     = "msd"
  instance = google_sql_database_instance.db.name
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_user" "app" {
  # an ordinary role: row-level security binds it (no superuser, no BYPASSRLS)
  name     = "msd"
  instance = google_sql_database_instance.db.name
  password = random_password.db.result
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(["msd-secret-key", "msd-database-url", "anthropic-api-key", "openai-api-key", "openrouter-api-key", "langsmith-api-key"])
  secret_id = each.key
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "app" {
  for_each  = google_secret_manager_secret.secrets
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

locals {
  env = {
    MSD_ENV                  = "prod"
    MSD_ALLOWED_HOSTS        = var.hostname
    MSD_TASK_BACKEND         = "django_tasks_db.DatabaseBackend"
    LANGSMITH_TRACING        = "true"
    MSD_SSL_REDIRECT         = "0" # Cloud Run terminates TLS
    MSD_CSRF_TRUSTED_ORIGINS = "https://${var.hostname}"
  }
  secret_env = {
    MSD_SECRET_KEY     = "msd-secret-key"
    DATABASE_URL       = "msd-database-url"
    ANTHROPIC_API_KEY  = "anthropic-api-key"
    OPENAI_API_KEY     = "openai-api-key"
    OPENROUTER_API_KEY = "openrouter-api-key"
    LANGSMITH_API_KEY  = "langsmith-api-key"
  }
}

resource "google_cloud_run_v2_service" "web" {
  name     = "signal-desk-web"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.app.email
    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.app.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image
      ports {
        container_port = 8000
      }
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }
}

resource "google_cloud_run_v2_worker_pool" "worker" {
  name     = "signal-desk-worker"
  location = var.region

  template {
    service_account = google_service_account.app.email
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.app.id
      }
    }
    containers {
      image   = var.image
      command = ["python", "manage.py", "db_worker"]
      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job" "nightly_sync" {
  name     = "signal-desk-nightly-sync"
  location = var.region

  template {
    template {
      service_account = google_service_account.app.email
      vpc_access {
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.app.id
        }
      }
      containers {
        image   = var.image
        command = ["python", "manage.py", "sync_all"]
        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.secrets[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }
}

resource "google_cloud_scheduler_job" "nightly_sync" {
  name      = "signal-desk-nightly-sync"
  region    = var.region
  schedule  = "17 4 * * *"
  time_zone = "Europe/Berlin"
  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project}/jobs/${google_cloud_run_v2_job.nightly_sync.name}:run"
    oauth_token {
      service_account_email = google_service_account.app.email
    }
  }
}
