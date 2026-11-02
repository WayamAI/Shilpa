// PostgreSQL Flexible Server: Entra auth only (password auth disabled), PITR backups, database "shilpa".
// Per-service database roles are created after deployment (see docs/azure/infra.md); Bicep cannot run SQL.
param name string
param location string
param tags object = {}
param tenantId string = tenant().tenantId
@description('Burstable for dev/staging, GeneralPurpose for prod.')
@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param skuTier string = 'Burstable'
@description('[Verify] SKU and quota in the target region, e.g. Standard_B2s (Burstable) or Standard_D2ds_v5 (GeneralPurpose).')
param skuName string = 'Standard_B2s'
@minValue(32)
param storageSizeGB int = 32
@allowed(['14', '15', '16', '17'])
param version string = '16'
@minValue(7)
@maxValue(35)
param backupRetentionDays int = 7
param geoRedundantBackup bool = false
@allowed(['Disabled', 'ZoneRedundant', 'SameZone'])
@description('Not available on Burstable. [Verify] zone support in the region.')
param highAvailability string = 'Disabled'
param databaseName string = 'shilpa'
param publicNetworkAccess bool = true
@description('Adds the 0.0.0.0 rule so Azure-hosted clients (Container Apps) can connect over the public endpoint. Use private endpoints instead for staging/prod.')
param allowAzureServices bool = true
@description('Entra object id of the Postgres admin (a group is recommended).')
param adminObjectId string
param adminName string
@allowed(['Group', 'User', 'ServicePrincipal'])
param adminPrincipalType string = 'Group'

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: skuName, tier: skuTier }
  properties: {
    version: version
    createMode: 'Default'
    storage: { storageSizeGB: storageSizeGB, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: backupRetentionDays, geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled' }
    highAvailability: { mode: highAvailability }
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenantId }
    network: { publicNetworkAccess: publicNetworkAccess ? 'Enabled' : 'Disabled' }
  }
}

resource admin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2025-08-01' = {
  parent: pg
  name: adminObjectId
  properties: { principalType: adminPrincipalType, principalName: adminName, tenantId: tenantId }
}

resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: pg
  name: databaseName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [admin]
}

resource azureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = if (publicNetworkAccess && allowAzureServices) {
  parent: pg
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [db]
}

output id string = pg.id
output name string = pg.name
output fqdn string = pg.properties.fullyQualifiedDomainName
output databaseName string = db.name
