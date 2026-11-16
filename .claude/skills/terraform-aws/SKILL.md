---
name: terraform-aws
description: Write or change Terraform for AWS under infra/ (resources, variables, outputs, tests) per project conventions.
---
1. Layout in `infra/`:
   - `versions.tf`: `required_version`, providers pinned with `~>`, provider `default_tags`, commented S3 backend with `use_lockfile = true`.
   - `variables.tf`: every variable has `type`, `description` and a `validation` where values are constrained; secrets get `sensitive = true` and no default; no account-specific defaults.
   - `main.tf`: grouped by `# ---------- section ----------` headers; `outputs.tf`: every output has `description`, `sensitive = true` when it carries anything secret.
   - Only `terraform.tfvars.example` is committed; real `*.tfvars`, `*.tfstate*` and `tfplan` are gitignored.
2. Naming: `local.name` prefix, `this` for singletons, snake_case; per-resource `tags` only for `Name`, everything else via `default_tags`.
3. Credentials never appear in `.tf`, tfvars, `user_data` or outputs:
   - CI: GitHub OIDC role (copy the `aws_iam_role.deploy` trust: `aud` plus environment-scoped `sub`). No `aws_iam_access_key` resources, no static keys in workflows.
   - Hosts: instance profile roles. Runtime secrets: SSM Parameter Store (SecureString) or Secrets Manager, passed by ARN/name, read at runtime.
4. Security defaults:
   - IAM via `data "aws_iam_policy_document"`; actions scoped to resource ARNs. `resources = ["*"]` only for actions that cannot be scoped (e.g. `ecr:GetAuthorizationToken`).
   - Security groups: separate `aws_vpc_security_group_ingress_rule` / `_egress_rule` with `description`; ingress CIDRs come from variables; no port 22 (use SSM).
   - EC2: IMDSv2 (`http_tokens = "required"`, hop limit 1), encrypted gp3 root volume.
   - S3: public access block, versioning, SSE. RDS/EBS/EFS: `storage_encrypted`. ECR: immutable tags, scan on push.
5. Cost and lifecycle: sizes as variables with the smallest sane default; no NAT gateway or load balancer unless asked; every `lifecycle` block gets a one-line reason comment.
6. Tests: extend `infra/tests/*.tftest.hcl` (offline, `mock_provider "aws"`; add `mock_data` defaults for new data sources). One `assert` per security property you introduce.
7. Verify from `infra/`: `terraform fmt -recursive`, `terraform init -backend=false -input=false`, `terraform validate`, `terraform test`. Never run `plan` against a real account, `apply` or `destroy` without explicit user approval.
8. Run the `iac-guard` agent on the change and fix every BLOCK item. Update README/ARCHITECTURE if the infrastructure shape changed.
