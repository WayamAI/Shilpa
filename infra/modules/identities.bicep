// One user-assigned managed identity per service. Roles are granted in roles.bicep.
param baseName string
param location string
param tags object = {}

var services = ['web', 'api', 'coordinator', 'worker']

resource ids 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for s in services: {
  name: 'id-${baseName}-${s}'
  location: location
  tags: tags
}]

output web object = { id: ids[0].id, name: ids[0].name, principalId: ids[0].properties.principalId, clientId: ids[0].properties.clientId }
output api object = { id: ids[1].id, name: ids[1].name, principalId: ids[1].properties.principalId, clientId: ids[1].properties.clientId }
output coordinator object = { id: ids[2].id, name: ids[2].name, principalId: ids[2].properties.principalId, clientId: ids[2].properties.clientId }
output worker object = { id: ids[3].id, name: ids[3].name, principalId: ids[3].properties.principalId, clientId: ids[3].properties.clientId }
