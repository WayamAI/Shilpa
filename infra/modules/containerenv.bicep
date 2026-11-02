// Container Apps environment (workload-profiles type, Consumption profile) wired to Log Analytics.
param name string
param location string
param tags object = {}
param logAnalyticsName string
@description('Empty = no VNet integration. Otherwise a subnet delegated to Microsoft.App/environments.')
param infrastructureSubnetId string = ''
param zoneRedundant bool = false

resource law 'Microsoft.OperationalInsights/workspaces@2025-02-01' existing = { name: logAnalyticsName }

resource env 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: 'cae-${name}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: law.properties.customerId, sharedKey: law.listKeys().primarySharedKey }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    vnetConfiguration: empty(infrastructureSubnetId) ? null : { infrastructureSubnetId: infrastructureSubnetId, internal: false }
    zoneRedundant: zoneRedundant
  }
}

output id string = env.id
output name string = env.name
output defaultDomain string = env.properties.defaultDomain
