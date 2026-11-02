// One private endpoint plus its DNS zone group. Called once per target service from main.bicep.
param name string
param location string
param tags object = {}
param subnetId string
param targetResourceId string
@description('Sub-resource: postgresqlServer, blob, vault, account, namespace, registry.')
param groupId string
param privateDnsZoneId string

resource pe 'Microsoft.Network/privateEndpoints@2025-05-01' = {
  name: 'pe-${name}'
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      { name: name, properties: { privateLinkServiceId: targetResourceId, groupIds: [groupId] } }
    ]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2025-05-01' = {
  parent: pe
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: 'config', properties: { privateDnsZoneId: privateDnsZoneId } }] }
}
