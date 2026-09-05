variable "tenancy_ocid" {
  type        = string
  description = "OCI tenancy OCID"
}

variable "user_ocid" {
  type        = string
  description = "OCI user OCID used by Terraform"
}

variable "fingerprint" {
  type        = string
  description = "Fingerprint of the OCI API signing key"
}

variable "private_key_path" {
  type        = string
  description = "Local path to the OCI API private key"
}

variable "region" {
  type        = string
  description = "OCI home region, for example eu-madrid-1"
}

variable "compartment_ocid" {
  type        = string
  description = "Compartment in which the worker resources are created"
}

variable "ssh_public_key" {
  type        = string
  description = "OpenSSH public key installed for the ubuntu user"
}

variable "ssh_allowed_cidr" {
  type        = string
  description = "CIDR allowed to reach SSH. Replace the default with your public IP/32 when possible."
  default     = "0.0.0.0/0"
}

variable "repo_url" {
  type        = string
  description = "Public bsd-workers repository cloned onto each VM"
  default     = "https://github.com/davidmariscalf/bsd-workers.git"
}
