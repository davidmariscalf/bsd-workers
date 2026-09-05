terraform {
  required_version = ">= 1.5.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 8.29"
    }
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu_arm" {
  compartment_id   = var.compartment_ocid
  operating_system = "Canonical Ubuntu"
  shape            = "VM.Standard.A1.Flex"
  sort_by          = "TIMECREATED"
  sort_order       = "DESC"
}

resource "oci_core_vcn" "bsd" {
  compartment_id = var.compartment_ocid
  cidr_block     = "10.20.0.0/16"
  display_name   = "bsd-workers-vcn"
  dns_label      = "bsdworkers"
}

resource "oci_core_internet_gateway" "bsd" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.bsd.id
  display_name   = "bsd-workers-igw"
  enabled        = true
}

resource "oci_core_route_table" "bsd" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.bsd.id
  display_name   = "bsd-workers-route"

  route_rules {
    network_entity_id = oci_core_internet_gateway.bsd.id
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
  }
}

resource "oci_core_security_list" "bsd" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.bsd.id
  display_name   = "bsd-workers-security"

  ingress_security_rules {
    protocol = "6"
    source   = var.ssh_allowed_cidr

    tcp_options {
      min = 22
      max = 22
    }
  }

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_subnet" "bsd" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.bsd.id
  cidr_block                 = "10.20.1.0/24"
  display_name               = "bsd-workers-public"
  dns_label                  = "bsdpub"
  route_table_id             = oci_core_route_table.bsd.id
  security_list_ids          = [oci_core_security_list.bsd.id]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_instance" "bsd_worker" {
  count               = 2
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[count.index % length(data.oci_identity_availability_domains.ads.availability_domains)].name
  display_name        = "bsd-oracle-${count.index + 1}"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 1
    memory_in_gbs = 6
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.bsd.id
    assign_public_ip = true
    display_name     = "bsd-oracle-${count.index + 1}-vnic"
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 47
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      repo_url = var.repo_url
    }))
  }

  preserve_boot_volume = false
}
