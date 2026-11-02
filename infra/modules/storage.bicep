// Artifact storage: StorageV2, no shared keys, no anonymous access, soft delete + versioning, "artifacts" container.
param name string
param location string
param tags object = {}
@allowed(['Standard_LRS', 'Standard_ZRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_GZRS'])
param skuName string = 'Standard_LRS'
@description('When false, only private endpoints can reach the account (the API proxies all browser traffic).')
param publicNetworkAccess bool = true
@minValue(1)
param blobSoftDeleteDays int = 14
@minValue(1)
param containerSoftDeleteDays int = 14
param containerName string = 'artifacts'

resource sa 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: skuName }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: publicNetworkAccess ? 'Enabled' : 'Disabled'
    networkAcls: { defaultAction: publicNetworkAccess ? 'Allow' : 'Deny', bypass: 'AzureServices' }
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: sa
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: { enabled: true, days: blobSoftDeleteDays }
    containerDeleteRetentionPolicy: { enabled: true, days: containerSoftDeleteDays }
  }
}

resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blob
  name: containerName
  properties: { publicAccess: 'None' }
}

output id string = sa.id
output name string = sa.name
output blobEndpoint string = sa.properties.primaryEndpoints.blob
output containerName string = artifacts.name
