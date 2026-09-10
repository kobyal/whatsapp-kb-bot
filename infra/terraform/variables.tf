variable "aws_region" {
  description = "Region for everything. Bedrock must offer the chosen models here (eu-west-1 and us-east-1 both do)."
  type        = string
  default     = "eu-west-1"
}

variable "name_prefix" {
  description = "Prefix for every resource name, so several bots can share an account."
  type        = string
  default     = "wakb"
}

variable "allowed_groups" {
  description = "WhatsApp groups the bot may answer in: group jids (…@g.us) or exact group subjects. Empty = answers nobody."
  type        = list(string)
  default     = []
}

variable "allow_dms" {
  description = "Also answer 1:1 chats sent to the bot number."
  type        = bool
  default     = false
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
  description = "Bedrock model id or inference profile used to pick the KB entry. Small and cheap is right here."
  type        = string
  default     = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "vision_model" {
  description = "Bedrock model used to read screenshots into text. Only called when a message carries an image."
  type        = string
  default     = "eu.anthropic.claude-sonnet-4-6"
}

variable "min_confidence" {
  description = "Below this classifier confidence the bot stays silent. 0.85 is a sane start; raise it if you see wrong answers."
  type        = number
  default     = 0.85
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

variable "bot_header" {
  description = "First line of every reply, so people know it came from a bot."
  type        = string
  default     = "🤖 _Automated answer from the support bot_"
}

variable "vpc_cidr" {
  description = "CIDR of the small dedicated VPC created for the listener."
  type        = string
  default     = "10.42.0.0/24"
}

variable "disable_api_termination" {
  description = "Protect the listener from accidental termination (and from account-wide instance schedulers that stop first)."
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
