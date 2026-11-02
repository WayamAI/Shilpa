// Least-privilege role assignments for the four service identities. See docs/azure/infra.md for the matrix.
//
//   web          AcrPull
//   api          AcrPull, Key Vault Secrets User, Blob Data Contributor (artifacts container), OpenAI User
//   coordinator  AcrPull, Key Vault Secrets User, SB Data Sender (cad, plan), SB Data Receiver (plan), OpenAI User
//   worker       AcrPull, Blob Data Contributor (artifacts container), SB Data Receiver (cad)
//
// The CAD worker gets no OpenAI role (the planner runs in the coordinator; the worker only re-queues repair work
// through the DB outbox) and no Key Vault role. It still needs the database (jobs, attempts, artifacts), which is
// granted through a PostgreSQL role for its identity, not an Azure role.
param identities object
param acrName string
param keyVaultName string
param storageAccountName string
param artifactsContainerName string
param serviceBusName string
param cadQueueName string = 'cad'
param planQueueName string = 'plan'
param openAiName string

var roleIds = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  sbSender: '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
  sbReceiver: '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = { name: acrName }
resource kv 'Microsoft.KeyVault/vaults@2026-02-01' existing = { name: keyVaultName }
resource sa 'Microsoft.Storage/storageAccounts@2025-01-01' existing = { name: storageAccountName }
resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' existing = { parent: sa, name: 'default' }
resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' existing = { parent: blobSvc, name: artifactsContainerName }
resource sb 'Microsoft.ServiceBus/namespaces@2026-01-01' existing = { name: serviceBusName }
resource cadQueue 'Microsoft.ServiceBus/namespaces/queues@2026-01-01' existing = { parent: sb, name: cadQueueName }
resource planQueue 'Microsoft.ServiceBus/namespaces/queues@2026-01-01' existing = { parent: sb, name: planQueueName }
resource openAi 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = { name: openAiName }

// ---- web
resource webAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identities.web.principalId, roleIds.acrPull)
  properties: { principalId: identities.web.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull) }
}

// ---- api
resource apiAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identities.api.principalId, roleIds.acrPull)
  properties: { principalId: identities.api.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull) }
}
resource apiKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, identities.api.principalId, roleIds.kvSecretsUser)
  properties: { principalId: identities.api.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.kvSecretsUser) }
}
resource apiBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: artifacts
  name: guid(artifacts.id, identities.api.principalId, roleIds.blobContributor)
  properties: { principalId: identities.api.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.blobContributor) }
}
resource apiAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, identities.api.principalId, roleIds.openAiUser)
  properties: { principalId: identities.api.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.openAiUser) }
}

// ---- coordinator
resource coordAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identities.coordinator.principalId, roleIds.acrPull)
  properties: { principalId: identities.coordinator.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull) }
}
resource coordKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, identities.coordinator.principalId, roleIds.kvSecretsUser)
  properties: { principalId: identities.coordinator.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.kvSecretsUser) }
}
resource coordAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, identities.coordinator.principalId, roleIds.openAiUser)
  properties: { principalId: identities.coordinator.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.openAiUser) }
}
resource coordSendCad 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cadQueue
  name: guid(cadQueue.id, identities.coordinator.principalId, roleIds.sbSender)
  properties: { principalId: identities.coordinator.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.sbSender) }
}
resource coordSendPlan 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: planQueue
  name: guid(planQueue.id, identities.coordinator.principalId, roleIds.sbSender)
  properties: { principalId: identities.coordinator.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.sbSender) }
}
resource coordRecvPlan 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: planQueue
  name: guid(planQueue.id, identities.coordinator.principalId, roleIds.sbReceiver)
  properties: { principalId: identities.coordinator.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.sbReceiver) }
}

// ---- worker (no OpenAI, no Key Vault)
resource workerAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identities.worker.principalId, roleIds.acrPull)
  properties: { principalId: identities.worker.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull) }
}
resource workerBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: artifacts
  name: guid(artifacts.id, identities.worker.principalId, roleIds.blobContributor)
  properties: { principalId: identities.worker.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.blobContributor) }
}
resource workerRecvCad 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cadQueue
  name: guid(cadQueue.id, identities.worker.principalId, roleIds.sbReceiver)
  properties: { principalId: identities.worker.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.sbReceiver) }
}
