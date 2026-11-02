// Shilpa on Azure: one environment (dev | staging | prod) in one resource group.
//
// Scope decision: resource-group scope. The pipeline (or an operator) creates the resource group once, so the
// deployment identity needs Contributor plus a role-assignment right (Role Based Access Control Administrator, or
// User Access Administrator) on that group only, never on the subscription. Subscription scope would be needed only
// to create resource groups or subscription-wide budgets; neither is wanted here (blueprint section 18: separate
// resource groups per environment).
targetScope = 'resourceGroup'

// ------------------------------------------------------------------ identity of the deployment
@allowed(['dev', 'staging', 'prod'])
param envName string
@description('[Verify] Region availability for every service and model (blueprint section 6).')
param location string = 'centralindia'
@description('Azure OpenAI can live in another region when the model is not offered in `location`. [Verify] Do not move engineering data across regions without sign-off.')
param openAiLocation string = location
param workload string = 'shilpa'
param tags object = {}

// ------------------------------------------------------------------ images (empty = placeholder bootstrap)
@description('Full reference incl. digest, e.g. <acr>.azurecr.io/shilpa-web@sha256:...')
param webImage string = ''
@description('One image for api, coordinator and worker.')
param backendImage string = ''

// ------------------------------------------------------------------ app settings
@allowed(['dev', 'entra'])
@description('SHILPA_AUTH_MODE. Hosted environments should use entra; JWT validation is hosting-plan step 3.')
param authMode string = 'entra'
@description('Entra settings the API validates tokens against (SHILPA_ENTRA_*). Audience is e.g. api://<app-id>; one of scope/role is required.')
param entraAudience string = ''
param entraRequiredScope string = ''
param entraRequiredRole string = ''
param openAiApiVersion string = '2024-10-21'
@description('Stage -> deployment name (keys: default, intake, plan, repair, edit). Names must exist in openAiDeployments.')
param modelDeployments object = {}
@description('Azure OpenAI deployments. Shape: { name, model: { format, name, version }, sku: { name, capacity } }. [Verify] availability and quota.')
param openAiDeployments array = []
@minValue(1)
param maxDeliveryCount int = 5
param lockDurationSeconds int = 60
param workerTimeoutSeconds int = 300

// ------------------------------------------------------------------ sizing
param webSize object = { cpu: '0.5', memory: '1Gi' }
param apiSize object = { cpu: '1.0', memory: '2Gi' }
param coordinatorSize object = { cpu: '0.5', memory: '1Gi' }
param workerSize object = { cpu: '2.0', memory: '4Gi' }
param webMinReplicas int = 1
param apiMinReplicas int = 1
param workerMaxExecutions int = 3

// ------------------------------------------------------------------ data services
param postgresSkuTier string = 'Burstable'
param postgresSkuName string = 'Standard_B2s'
param postgresStorageGB int = 32
param postgresBackupRetentionDays int = 7
param postgresGeoRedundantBackup bool = false
@allowed(['Disabled', 'ZoneRedundant', 'SameZone'])
param postgresHighAvailability string = 'Disabled'
@description('Entra object id of the group (or user) that administers PostgreSQL and creates the per-service roles.')
param postgresAdminObjectId string
param postgresAdminName string
@allowed(['Group', 'User', 'ServicePrincipal'])
param postgresAdminPrincipalType string = 'Group'
param storageSku string = 'Standard_LRS'
param blobSoftDeleteDays int = 14
@allowed(['Standard', 'Premium'])
param serviceBusSku string = 'Standard'
@allowed(['Basic', 'Standard', 'Premium'])
param acrSku string = 'Standard'
param keyVaultPurgeProtection bool = true
param logRetentionDays int = 30
param logDailyQuotaGb int = -1

// ------------------------------------------------------------------ optional modules
@description('VNet, private DNS and private endpoints; turns public network access off on the services that support it.')
param enablePrivateNetworking bool = false
@description('Public Postgres only: allow Azure-hosted clients through the 0.0.0.0 firewall rule.')
param postgresAllowAzureServices bool = true
param enableFrontDoor bool = false
@allowed(['Standard_AzureFrontDoor', 'Premium_AzureFrontDoor'])
param frontDoorSku string = 'Premium_AzureFrontDoor'
param zoneRedundantEnvironment bool = false

// ------------------------------------------------------------------ budget
@description('Monthly amount in the billing currency of the subscription.')
param budgetAmount int
param budgetContactEmails array

var envShort = envName == 'staging' ? 'stg' : envName == 'prod' ? 'prd' : 'dev'
var shilpaEnv = envName == 'prod' ? 'production' : envName
var baseName = '${workload}-${envShort}'
var suffix = take(uniqueString(subscription().subscriptionId, resourceGroup().id), 6)
var allTags = union({ workload: workload, environment: envName }, tags)

var sbPrivate = enablePrivateNetworking && serviceBusSku == 'Premium'
var acrPrivate = enablePrivateNetworking && acrSku == 'Premium'

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { name: baseName, location: location, tags: allTags, retentionInDays: logRetentionDays, dailyQuotaGb: logDailyQuotaGb }
}

module identities 'modules/identities.bicep' = {
  name: 'identities'
  params: { baseName: baseName, location: location, tags: allTags }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: { name: 'acr${workload}${envShort}${suffix}', location: location, tags: allTags, sku: acrSku, publicNetworkAccess: !acrPrivate }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: { name: 'kv-${workload}-${envShort}-${suffix}', location: location, tags: allTags, publicNetworkAccess: !enablePrivateNetworking, enablePurgeProtection: keyVaultPurgeProtection }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    name: 'st${workload}${envShort}${suffix}'
    location: location
    tags: allTags
    skuName: storageSku
    publicNetworkAccess: !enablePrivateNetworking
    blobSoftDeleteDays: blobSoftDeleteDays
  }
}

module serviceBus 'modules/servicebus.bicep' = {
  name: 'servicebus'
  params: {
    name: 'sb-${baseName}-${suffix}'
    location: location
    tags: allTags
    sku: serviceBusSku
    maxDeliveryCount: maxDeliveryCount
    lockDuration: 'PT${lockDurationSeconds}S'
    publicNetworkAccess: !sbPrivate
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    name: 'psql-${baseName}-${suffix}'
    location: location
    tags: allTags
    skuTier: postgresSkuTier
    skuName: postgresSkuName
    storageSizeGB: postgresStorageGB
    backupRetentionDays: postgresBackupRetentionDays
    geoRedundantBackup: postgresGeoRedundantBackup
    highAvailability: postgresHighAvailability
    publicNetworkAccess: !enablePrivateNetworking
    allowAzureServices: postgresAllowAzureServices
    adminObjectId: postgresAdminObjectId
    adminName: postgresAdminName
    adminPrincipalType: postgresAdminPrincipalType
  }
}

module openAi 'modules/openai.bicep' = {
  name: 'openai'
  params: {
    name: 'oai-${baseName}-${suffix}'
    location: openAiLocation
    tags: allTags
    publicNetworkAccess: !enablePrivateNetworking
    deployments: openAiDeployments
  }
}

module roles 'modules/roles.bicep' = {
  name: 'roles'
  params: {
    identities: {
      web: identities.outputs.web
      api: identities.outputs.api
      coordinator: identities.outputs.coordinator
      worker: identities.outputs.worker
    }
    acrName: registry.outputs.name
    keyVaultName: keyVault.outputs.name
    storageAccountName: storage.outputs.name
    artifactsContainerName: storage.outputs.containerName
    serviceBusName: serviceBus.outputs.name
    openAiName: openAi.outputs.name
  }
}

// ---- optional: private networking
module network 'modules/network.bicep' = if (enablePrivateNetworking) {
  name: 'network'
  params: { name: baseName, location: location, tags: allTags }
}

module pePostgres 'modules/privateendpoint.bicep' = if (enablePrivateNetworking) {
  name: 'pe-postgres'
  params: {
    name: '${baseName}-postgres'
    location: location
    tags: allTags
    subnetId: network!.outputs.endpointsSubnetId
    targetResourceId: postgres.outputs.id
    groupId: 'postgresqlServer'
    privateDnsZoneId: network!.outputs.dnsZoneIds.postgres
  }
}

module peBlob 'modules/privateendpoint.bicep' = if (enablePrivateNetworking) {
  name: 'pe-blob'
  params: {
    name: '${baseName}-blob'
    location: location
    tags: allTags
    subnetId: network!.outputs.endpointsSubnetId
    targetResourceId: storage.outputs.id
    groupId: 'blob'
    privateDnsZoneId: network!.outputs.dnsZoneIds.blob
  }
}

module peKv 'modules/privateendpoint.bicep' = if (enablePrivateNetworking) {
  name: 'pe-kv'
  params: {
    name: '${baseName}-kv'
    location: location
    tags: allTags
    subnetId: network!.outputs.endpointsSubnetId
    targetResourceId: keyVault.outputs.id
    groupId: 'vault'
    privateDnsZoneId: network!.outputs.dnsZoneIds.keyVault
  }
}

module peOpenai 'modules/privateendpoint.bicep' = if (enablePrivateNetworking) {
  name: 'pe-openai'
  params: {
    name: '${baseName}-openai'
    location: location
    tags: allTags
    subnetId: network!.outputs.endpointsSubnetId
    targetResourceId: openAi.outputs.id
    groupId: 'account'
    privateDnsZoneId: network!.outputs.dnsZoneIds.openAi
  }
}

module peSb 'modules/privateendpoint.bicep' = if (sbPrivate) {
  name: 'pe-sb'
  params: {
    name: '${baseName}-sb'
    location: location
    tags: allTags
    subnetId: network!.outputs.endpointsSubnetId
    targetResourceId: serviceBus.outputs.id
    groupId: 'namespace'
    privateDnsZoneId: network!.outputs.dnsZoneIds.serviceBus
  }
}

module peAcr 'modules/privateendpoint.bicep' = if (acrPrivate) {
  name: 'pe-acr'
  params: {
    name: '${baseName}-acr'
    location: location
    tags: allTags
    subnetId: network!.outputs.endpointsSubnetId
    targetResourceId: registry.outputs.id
    groupId: 'registry'
    privateDnsZoneId: network!.outputs.dnsZoneIds.acr
  }
}

// ---- container apps
module containerEnv 'modules/containerenv.bicep' = {
  name: 'containerenv'
  params: {
    name: baseName
    location: location
    tags: allTags
    logAnalyticsName: monitoring.outputs.workspaceName
    infrastructureSubnetId: enablePrivateNetworking ? network!.outputs.containerAppsSubnetId : ''
    zoneRedundant: zoneRedundantEnvironment
  }
}

module apps 'modules/apps.bicep' = {
  name: 'apps'
  params: {
    baseName: baseName
    location: location
    tags: allTags
    environmentId: containerEnv.outputs.id
    acrLoginServer: registry.outputs.loginServer
    identities: {
      web: identities.outputs.web
      api: identities.outputs.api
      coordinator: identities.outputs.coordinator
      worker: identities.outputs.worker
    }
    webImage: webImage
    backendImage: backendImage
    shilpaEnv: shilpaEnv
    authMode: authMode
    entraAudience: entraAudience
    entraRequiredScope: entraRequiredScope
    entraRequiredRole: entraRequiredRole
    databaseHost: postgres.outputs.fqdn
    databaseName: postgres.outputs.databaseName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    blobEndpoint: storage.outputs.blobEndpoint
    artifactsContainerName: storage.outputs.containerName
    serviceBusFqdn: serviceBus.outputs.fqdn
    serviceBusName: serviceBus.outputs.name
    openAiEndpoint: openAi.outputs.endpoint
    openAiApiVersion: openAiApiVersion
    modelDeployments: modelDeployments
    maxDeliveryCount: maxDeliveryCount
    lockDurationSeconds: lockDurationSeconds
    workerTimeoutSeconds: workerTimeoutSeconds
    webSize: webSize
    apiSize: apiSize
    coordinatorSize: coordinatorSize
    workerSize: workerSize
    webMinReplicas: webMinReplicas
    apiMinReplicas: apiMinReplicas
    workerMaxExecutions: workerMaxExecutions
  }
  // Role assignments (AcrPull above all) must exist before the first image pull.
  dependsOn: [roles, pePostgres, peBlob, peKv, peOpenai, peSb, peAcr]
}

module frontDoor 'modules/frontdoor.bicep' = if (enableFrontDoor) {
  name: 'frontdoor'
  params: { name: baseName, tags: allTags, sku: frontDoorSku, originHostName: apps.outputs.webFqdn }
}

module budget 'modules/budget.bicep' = {
  name: 'budget'
  params: { name: 'budget-${baseName}', amount: budgetAmount, contactEmails: budgetContactEmails }
}

// ------------------------------------------------------------------ outputs used by the pipeline and docs
output acrName string = registry.outputs.name
output acrLoginServer string = registry.outputs.loginServer
output webAppName string = apps.outputs.webAppName
output apiAppName string = apps.outputs.apiAppName
output coordinatorAppName string = apps.outputs.coordinatorAppName
output workerJobName string = apps.outputs.workerJobName
output webUrl string = 'https://${apps.outputs.webFqdn}'
output frontDoorHostName string = enableFrontDoor ? frontDoor!.outputs.endpointHostName : ''
output frontDoorId string = enableFrontDoor ? frontDoor!.outputs.frontDoorId : ''
output postgresFqdn string = postgres.outputs.fqdn
output postgresServerName string = postgres.outputs.name
output serviceBusName string = serviceBus.outputs.name
output storageAccountName string = storage.outputs.name
output keyVaultName string = keyVault.outputs.name
output openAiEndpoint string = openAi.outputs.endpoint
output identityNames object = {
  web: identities.outputs.web.name
  api: identities.outputs.api.name
  coordinator: identities.outputs.coordinator.name
  worker: identities.outputs.worker.name
}
