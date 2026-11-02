// Azure OpenAI (Foundry) account + model deployments. Entra-only: API keys are disabled.
param name string
param location string
param tags object = {}
param publicNetworkAccess bool = true
@description('Deployments to create. Shape: { name, model: { format, name, version }, sku: { name, capacity } }. Nothing is hardcoded here. [Verify] model, version, SKU type (Standard / DataZoneStandard / GlobalStandard) and quota per region.')
param deployments array = []

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: publicNetworkAccess ? 'Enabled' : 'Disabled'
    networkAcls: { defaultAction: publicNetworkAccess ? 'Allow' : 'Deny' }
  }
}

// Deployments on one account must be created one at a time.
@batchSize(1)
resource dep 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [for d in deployments: {
  parent: account
  name: d.name
  sku: d.sku
  properties: { model: d.model }
}]

output id string = account.id
output name string = account.name
output endpoint string = account.properties.endpoint
