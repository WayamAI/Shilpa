using '../main.bicep'

// Production: General Purpose Postgres, zone redundancy, private networking, Front Door + WAF.
// Everything marked [Decide] or [Verify] must be settled before the first deployment.
param envName = 'prod'
// [Verify] Region availability and quotas (see dev.bicepparam). [Decide] data residency: Central India mandatory?
param location = 'centralindia'
param openAiLocation = 'centralindia'

// Set by the pipeline (SHILPA_WEB_IMAGE); empty deploys a placeholder image.
param webImage = readEnvironmentVariable('SHILPA_WEB_IMAGE', '')
param backendImage = readEnvironmentVariable('SHILPA_BACKEND_IMAGE', '')

param authMode = 'entra'
// [Decide] App registration of the API (Entra app id URI) and the scope or app role the API requires.
param entraAudience = 'api://00000000-0000-0000-0000-000000000000'
param entraRequiredScope = 'access_as_user'
param postgresAdminObjectId = '00000000-0000-0000-0000-000000000000' // [Decide]
param postgresAdminName = 'shilpa-prod-db-admins'
param postgresAdminPrincipalType = 'Group'

// [Verify] SKU and zone support in the region. [Decide] zone-redundant HA (extra cost).
param postgresSkuTier = 'GeneralPurpose'
param postgresSkuName = 'Standard_D2ds_v5'
param postgresStorageGB = 64
param postgresBackupRetentionDays = 35
param postgresGeoRedundantBackup = false // [Decide] requires a paired region that satisfies residency
param postgresHighAvailability = 'ZoneRedundant'
param storageSku = 'Standard_ZRS' // [Verify]
param blobSoftDeleteDays = 30
// Private Service Bus connectivity requires Premium (blueprint section 6). [Decide] Standard keeps the queue public (Entra-only).
param serviceBusSku = 'Premium'
// Premium is required to put ACR behind a private endpoint. [Decide]
param acrSku = 'Premium'
param keyVaultPurgeProtection = true
param logRetentionDays = 90
param zoneRedundantEnvironment = false // [Verify] only valid with a VNet and zone support

param webMinReplicas = 2
param apiMinReplicas = 2
param workerMaxExecutions = 5

param enablePrivateNetworking = true
param enableFrontDoor = true // [Decide] pilot is external?
param frontDoorSku = 'Premium_AzureFrontDoor'

param budgetAmount = 1500 // illustrative [Decide]
param budgetContactEmails = ['finops@example.invalid'] // [Decide]

// [Verify] EXAMPLE deployments only. Model names, versions, SKU type (Standard = regional, DataZoneStandard,
// GlobalStandard) and quota differ per region and subscription. Run the language eval comparison before choosing
// (hosting-plan section 2). GlobalStandard may process data outside the region: needs data-residency sign-off.
param openAiDeployments = [
  {
    name: 'shilpa-plan'
    model: { format: 'OpenAI', name: 'gpt-5.5', version: '<verify-version>' }
    sku: { name: 'GlobalStandard', capacity: 200 }
  }
  {
    name: 'shilpa-intake'
    model: { format: 'OpenAI', name: 'gpt-5-mini', version: '<verify-version>' }
    sku: { name: 'GlobalStandard', capacity: 200 }
  }
]
param modelDeployments = {
  default: 'shilpa-plan'
  intake: 'shilpa-intake'
  plan: 'shilpa-plan'
  repair: 'shilpa-plan'
  edit: 'shilpa-plan'
}
