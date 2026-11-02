// Key Vault in RBAC mode (no access policies). Holds external credentials and certificates only;
// app-to-Azure auth uses managed identities, so the platform needs no secret to run.
param name string
param location string
param tags object = {}
param tenantId string = tenant().tenantId
param publicNetworkAccess bool = true
@description('Cannot be turned off once on. Dev may pass false so names can be reused after a delete.')
param enablePurgeProtection bool = true

resource kv 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: enablePurgeProtection ? true : null
    publicNetworkAccess: publicNetworkAccess ? 'Enabled' : 'Disabled'
    networkAcls: { defaultAction: publicNetworkAccess ? 'Allow' : 'Deny', bypass: 'AzureServices' }
  }
}

output id string = kv.id
output name string = kv.name
output uri string = kv.properties.vaultUri
