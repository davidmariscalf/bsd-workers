# Oracle Always Free BSD workers

This directory defines **two persistent ARM workers**, each with 1 OCPU and 6 GB RAM, using OCI `VM.Standard.A1.Flex`. Together they stay inside the Always Free allowance of 2 OCPUs / 12 GB RAM.

The official SageMath Docker image is currently amd64-only, so these ARM workers install SageMath from conda-forge through Miniforge instead.

## What Terraform creates

- VCN + public subnet
- Internet gateway and route table
- SSH-only ingress security list
- 2 × `VM.Standard.A1.Flex` instances
- 1 OCPU / 6 GB RAM per instance
- 47 GB boot volume per instance
- Ubuntu ARM image selected automatically
- cloud-init installation of SageMath and this repository

No API keys, SSH private keys, tokens, or OCIDs are stored in the repository.

## Required values

Create a `terraform.tfvars` locally with:

```hcl
tenancy_ocid     = "ocid1.tenancy..."
user_ocid        = "ocid1.user..."
fingerprint      = "aa:bb:cc:..."
private_key_path = "C:/path/to/oci_api_key.pem"
region           = "<your OCI home region>"
compartment_ocid = "ocid1.compartment..."
ssh_public_key   = "ssh-ed25519 AAAA..."
ssh_allowed_cidr = "YOUR.PUBLIC.IP/32"
```

Then:

```bash
terraform init
terraform plan
terraform apply
terraform output worker_public_ips
```

`ssh_allowed_cidr` defaults to `0.0.0.0/0` only so Terraform can be planned without an extra value. For a real deployment, restrict it to the controller's public IP `/32` whenever possible.

## Bootstrap

Cloud-init installs Miniforge under `/opt/conda`, creates a SageMath environment at `/opt/sage`, clones the repository to `/opt/bsd-workers`, and exposes:

```bash
bsd-run-task <base64-json-task>
```

The controller-side `oracle_dispatch.py` uses that command over SSH. Set:

```text
BSD_ORACLE_HOSTS=<ip1>,<ip2>
BSD_ORACLE_SSH_KEY=<path-to-private-ssh-key>
BSD_ORACLE_SSH_USER=ubuntu
```

and dispatch a task array with:

```bash
python oracle_dispatch.py tasks.json
```

The dispatcher uses both hosts concurrently and continues in two-task waves for larger batches.

## OCI caveat

Always Free A1 capacity is not guaranteed. OCI can return an out-of-host-capacity error, in which case the instances cannot be created until capacity becomes available in the home region / availability domain.
