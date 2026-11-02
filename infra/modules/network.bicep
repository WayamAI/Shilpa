// Optional (enablePrivateNetworking): VNet, subnets, private DNS zones linked to the VNet.
// The Container Apps environment goes into the delegated subnet; private endpoints go into the endpoints subnet.
param name string
param location string
param tags object = {}
param addressPrefix string = '10.20.0.0/16'
@description('Delegated to Microsoft.App/environments (workload-profiles environments need at least /27). [Verify] sizing against expected replica counts.')
param containerAppsSubnetPrefix string = '10.20.0.0/23'
param endpointsSubnetPrefix string = '10.20.2.0/24'

var zones = [
  'privatelink.postgres.database.azure.com'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.vaultcore.azure.net'
  'privatelink.openai.azure.com'
  'privatelink.servicebus.windows.net'
  'privatelink.azurecr.io'
]

resource vnet 'Microsoft.Network/virtualNetworks@2025-05-01' = {
  name: 'vnet-${name}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [addressPrefix] }
    subnets: [
      {
        name: 'snet-containerapps'
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          delegations: [{ name: 'containerapps', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-endpoints'
        properties: { addressPrefix: endpointsSubnetPrefix, privateEndpointNetworkPolicies: 'Disabled' }
      }
    ]
  }
}

resource dns 'Microsoft.Network/privateDnsZones@2024-06-01' = [for z in zones: {
  name: z
  location: 'global'
  tags: tags
}]

resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (z, i) in zones: {
  parent: dns[i]
  name: 'link-${name}'
  location: 'global'
  properties: { virtualNetwork: { id: vnet.id }, registrationEnabled: false }
}]

output vnetId string = vnet.id
output containerAppsSubnetId string = vnet.properties.subnets[0].id
output endpointsSubnetId string = vnet.properties.subnets[1].id
output dnsZoneIds object = {
  postgres: dns[0].id
  blob: dns[1].id
  keyVault: dns[2].id
  openAi: dns[3].id
  serviceBus: dns[4].id
  acr: dns[5].id
}
