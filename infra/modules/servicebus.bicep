// Service Bus namespace + queues. Semantics mirror shilpa/queue.py: peek-lock, finite delivery count, dead letters,
// duplicate detection on message_id. Entra-only (local auth disabled).
param name string
param location string
param tags object = {}
@allowed(['Standard', 'Premium'])
@description('Private endpoints require Premium (blueprint section 6).')
param sku string = 'Standard'
@description('Queue names. The code uses "plan" and "cad" (shilpa/queue.py QUEUES).')
param queueNames array = ['cad', 'plan']
@description('SHILPA_MAX_DELIVERY_COUNT; after this many deliveries the broker dead-letters the message.')
@minValue(1)
param maxDeliveryCount int = 5
@description('SHILPA_LOCK_DURATION_S as ISO 8601 (max 5 minutes). Workers renew the lock while executing.')
param lockDuration string = 'PT1M'
param defaultMessageTimeToLive string = 'P1D'
param duplicateDetectionWindow string = 'PT10M'
param publicNetworkAccess bool = true
param premiumCapacityUnits int = 1

resource ns 'Microsoft.ServiceBus/namespaces@2026-01-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku
    tier: sku
    capacity: sku == 'Premium' ? premiumCapacityUnits : null
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: publicNetworkAccess ? 'Enabled' : 'Disabled'
  }
}

resource queues 'Microsoft.ServiceBus/namespaces/queues@2026-01-01' = [for q in queueNames: {
  parent: ns
  name: q
  properties: {
    lockDuration: lockDuration
    maxDeliveryCount: maxDeliveryCount
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: duplicateDetectionWindow
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: defaultMessageTimeToLive
    requiresSession: false
    enablePartitioning: false
  }
}]

output id string = ns.id
output name string = ns.name
output fqdn string = '${ns.name}.servicebus.windows.net'
