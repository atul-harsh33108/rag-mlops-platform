output "vpc_id"              { value = module.vpc.vpc_id }
output "private_subnet_ids"   { value = module.vpc.private_subnets }
output "public_subnet_ids"    { value = module.vpc.public_subnets }
output "database_subnet_ids"  { value = module.vpc.database_subnets }
output "vpc_cidr"            { value = module.vpc.vpc_cidr_block }
output "azs"                 { value = var.azs }