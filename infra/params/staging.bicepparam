using '../main.bicep'

// Staging: same shape as prod where it matters (images by digest, Entra auth), anonymised pilot data.
param envName = 'staging'
// [Verify] Region availability and quotas (see dev.bicepparam).
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
param postgresAdminName = 'shilpa-stg-db-admins'
param postgresAdminPrincipalType = 'Group'

param postgresSkuTier = 'Burstable' // [Verify] SKU and quota
param postgresSkuName = 'Standard_B2s'
param postgresBackupRetentionDays = 14
param storageSku = 'Standard_ZRS' // [Verify] ZRS offered in the region
param serviceBusSku = 'Standard'
param acrSku = 'Standard'
param keyVaultPurgeProtection = true
param logRetentionDays = 30

param workerMaxExecutions = 3
param enablePrivateNetworking = false
param enableFrontDoor = false

param budgetAmount = 400 // illustrative [Decide]
param budgetContactEmails = ['finops@example.invalid'] // [Decide]

// [Verify] EXAMPLE deployments only. Model names, versions, SKU type (Standard = regional, DataZoneStandard,
// GlobalStandard) and quota differ per region and subscription. Run the language eval comparison before choosing
// (hosting-plan section 2). GlobalStandard may process data outside the region: needs data-residency sign-off.
param openAiDeployments = [
  {
    name: 'shilpa-plan'
    model: { format: 'OpenAI', name: 'gpt-5.5', version: '<verify-version>' }
    sku: { name: 'GlobalStandard', capacity: 100 }
  }
  {
    name: 'shilpa-intake'
    model: { format: 'OpenAI', name: 'gpt-5-mini', version: '<verify-version>' }
    sku: { name: 'GlobalStandard', capacity: 100 }
  }
]
param modelDeployments = {
  default: 'shilpa-plan'
  intake: 'shilpa-intake'
  plan: 'shilpa-plan'
  repair: 'shilpa-plan'
  edit: 'shilpa-plan'
}
