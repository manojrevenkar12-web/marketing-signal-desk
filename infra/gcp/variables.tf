variable "project" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west3" # Frankfurt
}

variable "image" {
  type        = string
  description = "Artifact Registry image, pinned by digest"
}

variable "hostname" {
  type        = string
  description = "Public hostname of the web service"
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}
