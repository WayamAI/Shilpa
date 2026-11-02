// Azure Container Registry. Images are deployed by digest; admin user is off, pulls use managed identity (AcrPull).
param name string
param location string
param tags object = {}
@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Standard'
@description('Public network access. Private endpoints need Premium.')
param publicNetworkAccess bool = true

resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: publicNetworkAccess ? 'Enabled' : 'Disabled'
  }
}

output id string = acr.id
output name string = acr.name
output loginServer string = acr.properties.loginServer
