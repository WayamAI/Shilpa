// Log Analytics workspace + workspace-based Application Insights.
param name string
param location string
param tags object = {}
@minValue(30)
param retentionInDays int = 30
@description('Daily ingestion cap in GB. -1 = no cap. A cap protects the budget but drops telemetry once reached.')
param dailyQuotaGb int = -1

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: 'log-${name}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
    workspaceCapping: { dailyQuotaGb: dailyQuotaGb }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

output workspaceId string = workspace.id
output workspaceName string = workspace.name
// Prompts, CAD files and tokens must never be logged (blueprint section 17); the app owns that redaction.
// The connection string holds the instrumentation key, which identifies the resource but does not grant reads.
#disable-next-line outputs-should-not-contain-secrets
output appInsightsConnectionString string = appInsights.properties.ConnectionString
