// Container apps: web (external ingress), api (internal ingress), coordinator (no ingress),
// and the CAD worker as an event-driven Container Apps Job (KEDA azure-servicebus rule, managed-identity auth).
//
// Bootstrap: when an image parameter is empty a public placeholder is deployed, so the infrastructure can be created
// before the first image exists. The pipeline then redeploys with real digests (image@sha256:...).
param baseName string
param location string
param tags object = {}
param environmentId string
param acrLoginServer string
param identities object

param webImage string = ''
param backendImage string = ''

@description('SHILPA_ENV: dev | staging | production. The settings layer refuses ollama outside dev.')
param shilpaEnv string
param authMode string = 'entra'
@description('SHILPA_ENTRA_TENANT_ID, _AUDIENCE (comma separated), _REQUIRED_SCOPE / _REQUIRED_ROLE. settings.startup_problems() refuses to start without tenant, audience and one of scope/role.')
param entraTenantId string = tenant().tenantId
param entraAudience string = ''
param entraRequiredScope string = ''
param entraRequiredRole string = ''
@description('PostgreSQL FQDN and database. Each service connects as its own managed identity (user = identity name, token as password).')
param databaseHost string
param databaseName string = 'shilpa'
param appInsightsConnectionString string
param blobEndpoint string
param artifactsContainerName string
param serviceBusFqdn string
param serviceBusName string
param cadQueueName string = 'cad'
param openAiEndpoint string
param openAiApiVersion string
@description('Stage -> deployment name. Keys: default, intake, plan, repair, edit. Blank = unset.')
param modelDeployments object = {}
param maxDeliveryCount int = 5
param lockDurationSeconds int = 60
param workerTimeoutSeconds int = 300

param webSize object = { cpu: '0.5', memory: '1Gi' }
param apiSize object = { cpu: '1.0', memory: '2Gi' }
param coordinatorSize object = { cpu: '0.5', memory: '1Gi' }
param workerSize object = { cpu: '2.0', memory: '4Gi' }
param webMinReplicas int = 1
param webMaxReplicas int = 3
param apiMinReplicas int = 1
param apiMaxReplicas int = 3
param workerMaxExecutions int = 3
@description('shilpa/api/app.py serves /v1/health today (the image HEALTHCHECK uses it). Point these at /v1/health/live and /v1/health/ready when step 3 lands them.')
param apiLivenessPath string = '/v1/health'
param apiReadinessPath string = '/v1/health'

var placeholder = 'mcr.microsoft.com/k8se/quickstart:latest'
var webBootstrap = empty(webImage)
var backendBootstrap = empty(backendImage)

func identityBlock(id string) object => { type: 'UserAssigned', userAssignedIdentities: { '${id}': {} } }
func env(name string, value string) object => { name: name, value: value }

// The URL carries no password: DATABASE_AUTH=entra makes shilpa/db.py fetch an Entra token per connection, and
// AZURE_CLIENT_ID selects the user-assigned identity for DefaultAzureCredential.
func dbUrl(user string, host string, db string) string => 'postgresql+psycopg://${user}@${host}:5432/${db}?sslmode=require'

// Settings shared by every service.
var dbEnv = [
  env('SHILPA_ENV', shilpaEnv)
  env('SHILPA_AUTH_MODE', authMode)
  env('SHILPA_ENTRA_TENANT_ID', entraTenantId)
  env('SHILPA_ENTRA_AUDIENCE', entraAudience)
  env('SHILPA_ENTRA_REQUIRED_SCOPE', entraRequiredScope)
  env('SHILPA_ENTRA_REQUIRED_ROLE', entraRequiredRole)
  env('DATABASE_AUTH', 'entra')
  env('APPLICATIONINSIGHTS_CONNECTION_STRING', appInsightsConnectionString)
]
// Names from the cloud adapters block of shilpa/settings.py (CloudSettings).
var blobEnv = [
  env('SHILPA_BLOB_BACKEND', 'azure')
  env('SHILPA_BLOB_ACCOUNT_URL', blobEndpoint)
  env('SHILPA_BLOB_CONTAINER', artifactsContainerName)
]
var queueEnv = [
  env('SHILPA_QUEUE_BACKEND', 'servicebus')
  env('SHILPA_SERVICEBUS_NAMESPACE', serviceBusFqdn)
  env('SHILPA_MAX_DELIVERY_COUNT', string(maxDeliveryCount))
  env('SHILPA_LOCK_DURATION_S', string(lockDurationSeconds))
]
// Names below exist in shilpa/settings.py today.
var llmEnv = [
  env('SHILPA_LLM', 'on')
  env('SHILPA_LLM_PROVIDER', 'azure')
  env('AZURE_OPENAI_ENDPOINT', openAiEndpoint)
  env('AZURE_OPENAI_AUTH', 'default')
  env('AZURE_OPENAI_API_VERSION', openAiApiVersion)
  env('AZURE_OPENAI_DEPLOYMENT', modelDeployments.?default ?? '')
  env('SHILPA_MODEL_INTAKE', modelDeployments.?intake ?? '')
  env('SHILPA_MODEL_PLAN', modelDeployments.?plan ?? '')
  env('SHILPA_MODEL_REPAIR', modelDeployments.?repair ?? '')
  env('SHILPA_MODEL_EDIT', modelDeployments.?edit ?? '')
]

// ------------------------------------------------------------------ api (internal ingress)
resource api 'Microsoft.App/containerApps@2025-07-01' = {
  name: 'ca-${baseName}-api'
  location: location
  tags: tags
  identity: identityBlock(identities.api.id)
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: acrLoginServer, identity: identities.api.id }]
      ingress: { external: false, targetPort: backendBootstrap ? 80 : 8000, transport: 'auto', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: backendBootstrap ? placeholder : backendImage
          // The image CMD already starts uvicorn on :8000.
          resources: apiSize
          env: concat(dbEnv, blobEnv, llmEnv, [env('DATABASE_URL', dbUrl(identities.api.name, databaseHost, databaseName)), env('AZURE_CLIENT_ID', identities.api.clientId)])
          probes: backendBootstrap ? [] : [
            { type: 'Liveness', httpGet: { path: apiLivenessPath, port: 8000 }, periodSeconds: 20, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: apiReadinessPath, port: 8000 }, periodSeconds: 10, failureThreshold: 3 }
          ]
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '50' } } }]
      }
    }
  }
}

// ------------------------------------------------------------------ web (external ingress)
resource web 'Microsoft.App/containerApps@2025-07-01' = {
  name: 'ca-${baseName}-web'
  location: location
  tags: tags
  identity: identityBlock(identities.web.id)
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: acrLoginServer, identity: identities.web.id }]
      ingress: { external: true, targetPort: webBootstrap ? 80 : 3000, transport: 'auto', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webBootstrap ? placeholder : webImage
          resources: webSize
          env: [
            env('NODE_ENV', 'production')
            env('PORT', '3000')
            env('HOSTNAME', '0.0.0.0')
            // /v1 is proxied to the internal API; docker-entrypoint.sh swaps this in at container start (docs/azure/containers.md).
            env('SHILPA_API_ORIGIN', 'https://${api.properties.configuration.ingress.fqdn}')
          ]
          probes: webBootstrap ? [] : [
            { type: 'Liveness', httpGet: { path: '/login', port: 3000 }, periodSeconds: 20, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/login', port: 3000 }, periodSeconds: 10, failureThreshold: 3 }
          ]
        }
      ]
      scale: {
        minReplicas: webMinReplicas
        maxReplicas: webMaxReplicas
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '100' } } }]
      }
    }
  }
}

// ------------------------------------------------------------------ coordinator (no ingress)
resource coordinator 'Microsoft.App/containerApps@2025-07-01' = {
  name: 'ca-${baseName}-coord'
  location: location
  tags: tags
  identity: identityBlock(identities.coordinator.id)
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: acrLoginServer, identity: identities.coordinator.id }]
    }
    template: {
      containers: [
        {
          name: 'coordinator'
          image: backendBootstrap ? placeholder : backendImage
          command: backendBootstrap ? null : ['python', '-m', 'shilpa.coordinator']
          resources: coordinatorSize
          env: concat(dbEnv, queueEnv, llmEnv, [env('DATABASE_URL', dbUrl(identities.coordinator.name, databaseHost, databaseName)), env('AZURE_CLIENT_ID', identities.coordinator.clientId)])
        }
      ]
      // Exactly one dispatcher for now; the outbox publisher is duplicate-safe, so raising this is possible later.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// ------------------------------------------------------------------ CAD worker (event-driven job)
resource worker 'Microsoft.App/jobs@2025-07-01' = {
  name: 'job-${baseName}-cad'
  location: location
  tags: tags
  identity: identityBlock(identities.worker.id)
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Event'
      // Hard stop above the app-level timeout (SHILPA_WORKER_TIMEOUT_S) plus startup and publish time.
      replicaTimeout: workerTimeoutSeconds + 300
      replicaRetryLimit: 0 // Redelivery is Service Bus's job (maxDeliveryCount), not the platform's.
      registries: [{ server: acrLoginServer, identity: identities.worker.id }]
      eventTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
        scale: {
          minExecutions: 0
          maxExecutions: workerMaxExecutions
          pollingInterval: 15
          rules: [
            {
              name: 'cad-queue'
              type: 'azure-servicebus'
              metadata: { queueName: cadQueueName, namespace: serviceBusName, messageCount: '1' }
              identity: identities.worker.id
            }
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: 'cad-worker'
          image: backendBootstrap ? placeholder : backendImage
          // [Assumption] shilpa.workers.cad.main() loops forever; a job execution must process one message and exit,
          // so this calls run_once() (exists today). Replace with a `--once` flag when the worker gets one.
          command: backendBootstrap ? null : ['python', '-c', 'from shilpa.workers.cad import run_once; run_once()']
          resources: workerSize
          // No model credentials: the kill switch is forced off and no OpenAI endpoint is passed. No Key Vault access either.
          env: concat(dbEnv, blobEnv, queueEnv, [
            env('SHILPA_LLM', 'off')
            env('DATABASE_URL', dbUrl(identities.worker.name, databaseHost, databaseName))
            env('SHILPA_WORKER_TIMEOUT_S', string(workerTimeoutSeconds))
            env('AZURE_CLIENT_ID', identities.worker.clientId)
          ])
        }
      ]
    }
  }
}

output webFqdn string = web.properties.configuration.ingress.fqdn
output apiFqdn string = api.properties.configuration.ingress.fqdn
output webAppName string = web.name
output apiAppName string = api.name
output coordinatorAppName string = coordinator.name
output workerJobName string = worker.name
