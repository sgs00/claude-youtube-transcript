terraform {
  backend "s3" {
    # Values supplied via -backend-config flags in deploy.sh
    # to avoid hard-coding bucket names in version control.
    # Example:
    #   terraform init \
    #     -backend-config="bucket=my-tfstate-bucket" \
    #     -backend-config="key=claude-yt-companion/terraform.tfstate" \
    #     -backend-config="region=eu-south-1" \
    #     -backend-config="dynamodb_table=terraform-state-lock" \
    #     -backend-config="encrypt=true"
  }
}
