variable "aws_region" {
  description = "Region for everything. Bedrock must offer the chosen models here (eu-west-1 and us-east-1 both do)."
  type        = string
  default     = "eu-west-1"
}

variable "name_prefix" {
  description = "Prefix for every resource name, so several bots can share an account. KB tables are <prefix>-kb-<tenant id>."
  type        = string
  default     = "wakb"
}

variable "default_tenant" {
  description = "The tenant (a folder under tenants/) that answers a group not claimed by any tenant.json. With one tenant this is simply it."
  type        = string
  default     = "dev-platform"
}

variable "allowed_groups" {
  description = "WhatsApp groups the bot may answer in: group jids (…@g.us) or exact group subjects. Empty = answers nobody."
  type        = list(string)
  default     = []
}

variable "dm_enabled" {
  description = "1:1 mode. When true, members of the groups in dm_roster_groups may message the bot directly. Strangers are dropped in silence."
  type        = bool
  default     = false
}

variable "dm_roster_groups" {
  description = "Group jid -> tenant id. Members of each group may DM the bot and get that tenant's KB. Must be jids (the roster is read with groupMetadata)."
  type        = map(string)
  default     = {}
}

variable "call_words" {
  description = "A message starting with one of these words is an explicit call to the bot (always answered, if only with the no-match text)."
  type        = list(string)
  default     = ["bot", "בוט"]
}

variable "repo_url" {
  description = "Git repo the EC2 clones at boot to get the listener code. Fork it and point this at your fork."
  type        = string
  default     = "https://github.com/kobyal/whatsapp-kb-bot.git"
}

variable "git_ref" {
  description = "Branch or tag of repo_url to deploy."
  type        = string
  default     = "main"
}

variable "instance_type" {
  description = "The listener idles at ~150 MB RSS; t3.small is comfortable, t4g.small (arm64) is cheaper but needs an arm64 AMI."
  type        = string
  default     = "t3.small"
}

variable "classify_model" {
  description = "Bedrock model id or inference profile used for the screen and to pick the KB entry. Small and cheap is right here."
  type        = string
  default     = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "vision_model" {
  description = "Bedrock model used to read screenshots into text. Only called when a message carries an image."
  type        = string
  default     = "eu.anthropic.claude-sonnet-4-6"
}

variable "min_confidence" {
  description = "At or above this classifier confidence the bot answers. 0.85 is a sane start; the production bot measured and moved to 0.90."
  type        = number
  default     = 0.85
}

variable "clarify_min_candidate" {
  description = "From here up to min_confidence the bot asks ONE fixed clarifying question instead of answering. Below it, silence."
  type        = number
  default     = 0.70
}

variable "clarify_enabled" {
  description = "Turn the clarifying question off entirely (silence below the floor, as in the first version of this template)."
  type        = bool
  default     = true
}

variable "supporter_window_seconds" {
  description = "After one of a tenant's supporters speaks in a group, the bot withholds clarifying questions there for this long."
  type        = number
  default     = 180
}

variable "answer_mode" {
  description = "verbatim = send the KB answer exactly as written. compose = let the model rephrase that one entry for the question."
  type        = string
  default     = "verbatim"
  validation {
    condition     = contains(["verbatim", "compose"], var.answer_mode)
    error_message = "answer_mode must be verbatim or compose."
  }
}

variable "vpc_cidr" {
  description = "CIDR of the small dedicated VPC created for the listener."
  type        = string
  default     = "10.42.0.0/24"
}

variable "disable_api_stop" {
  description = "Stop protection. Turn on if your account runs an instance scheduler or a cost enforcer that stops instances: they must call StopInstances first, and this makes that fail. NOTE: it also blocks `terraform destroy` until turned off."
  type        = bool
  default     = false
}

variable "ignore_tag_keys" {
  description = "Tag keys added by account-level automation (auto-taggers, schedulers) that Terraform should not fight over, e.g. [\"schedule\"]."
  type        = list(string)
  default     = []
}

variable "disable_api_termination" {
  description = "Protect the listener from accidental termination."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = { Project = "whatsapp-kb-bot" }
}
