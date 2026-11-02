using '../main.bicep'

// Dev: small, public endpoints behind Entra, synthetic data only.
param envName = 'dev'
// [Verify] Central India offers every service below (Container Apps jobs, PostgreSQL Flexible Server SKU, Service Bus, Azure OpenAI model). Fall back to an approved region otherwise.
param location = 'centralindia'
// [Verify] If the models are not offered in Central India, point this at another approved region (data residency sign-off needed).
param openAiLocation = 'centralindia'

// Set by the pipeline (SHILPA_WEB_IMAGE); empty deploys a placeholder image.
param webImage = readEnvironmentVariable('SHILPA_WEB_IMAGE', '')
param backendImage = readEnvironmentVariable('SHILPA_BACKEND_IMAGE', '')

param authMode = 'entra'
// [Decide] App registration of the API (Entra app id URI) and the scope or app role the API requires.
param entraAudience = 'api://00000000-0000-0000-0000-000000000000'
param entraRequiredScope = 'access_as_user'
// [Decide] Replace with the object id of the Entra group that administers PostgreSQL.
param postgresAdminObjectId = '00000000-0000-0000-0000-000000000000'
param postgresAdminName = 'shilpa-dev-db-admins'
param postgresAdminPrincipalType = 'Group'

// [Verify] SKU availability and vCore quota in the region.
param postgresSkuTier = 'Burstable'
param postgresSkuName = 'Standard_B2s'
param postgresBackupRetentionDays = 7
param storageSku = 'Standard_LRS'
param serviceBusSku = 'Standard'
param acrSku = 'Standard'
param keyVaultPurgeProtection = false
param logRetentionDays = 30
param logDailyQuotaGb = 1

param workerMaxExecutions = 2
param enablePrivateNetworking = false
param enableFrontDoor = false

// Illustrative placeholder in the subscription billing currency. [Decide] real dev ceiling.
param budgetAmount = 150
// [Decide] Alert recipients.
param budgetContactEmails = ['finops@example.invalid']

// [Verify] EXAMPLE deployments only. Model names, versions, SKU type (Standard = regional, DataZoneStandard,
// GlobalStandard) and quota differ per region and subscription. Run the language eval comparison before choosing
// (hosting-plan section 2). GlobalStandard may process data outside the region: needs data-residency sign-off.
param openAiDeployments = [
  {
    name: 'shilpa-plan'
    model: { format: 'OpenAI', name: 'gpt-5.5', version: '<verify-version>' }
    sku: { name: 'GlobalStandard', capacity: 50 }
  }
  {
    name: 'shilpa-intake'
    model: { format: 'OpenAI', name: 'gpt-5-mini', version: '<verify-version>' }
    sku: { name: 'GlobalStandard', capacity: 50 }
  }
]
param modelDeployments = {
  default: 'shilpa-plan'
  intake: 'shilpa-intake'
  plan: 'shilpa-plan'
  repair: 'shilpa-plan'
  edit: 'shilpa-plan'
}
