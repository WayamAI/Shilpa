// Optional (enableFrontDoor): Azure Front Door + WAF in front of the web app, for external pilots.
// Custom domains and certificates are intentionally not created here; add them once the DNS owner is known.
param name string
param tags object = {}
@allowed(['Standard_AzureFrontDoor', 'Premium_AzureFrontDoor'])
@description('Managed WAF rule sets need Premium; Standard supports custom rules only.')
param sku string = 'Premium_AzureFrontDoor'
@description('FQDN of the web container app (the origin).')
param originHostName string
@allowed(['Detection', 'Prevention'])
param wafMode string = 'Prevention'

var premium = sku == 'Premium_AzureFrontDoor'
var wafName = replace('waf-${name}', '-', '')

resource profile 'Microsoft.Cdn/profiles@2025-06-01' = {
  name: 'afd-${name}'
  location: 'global'
  tags: tags
  sku: { name: sku }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2025-06-01' = {
  parent: profile
  name: 'ep-${name}'
  location: 'global'
  properties: { enabledState: 'Enabled' }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2025-06-01' = {
  parent: profile
  name: 'og-web'
  properties: {
    loadBalancingSettings: { sampleSize: 4, successfulSamplesRequired: 3 }
    healthProbeSettings: { probePath: '/', probeRequestType: 'HEAD', probeProtocol: 'Https', probeIntervalInSeconds: 60 }
    sessionAffinityState: 'Disabled'
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2025-06-01' = {
  parent: originGroup
  name: 'web'
  properties: {
    hostName: originHostName
    originHostHeader: originHostName
    httpPort: 80
    httpsPort: 443
    priority: 1
    weight: 1000
    enabledState: 'Enabled'
    enforceCertificateNameCheck: true
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2025-06-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    originGroup: { id: originGroup.id }
    supportedProtocols: ['Https']
    patternsToMatch: ['/*']
    forwardingProtocol: 'HttpsOnly'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
  }
  dependsOn: [origin]
}

resource waf 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2025-03-01' = {
  name: wafName
  location: 'global'
  tags: tags
  sku: { name: sku }
  properties: {
    policySettings: { enabledState: 'Enabled', mode: wafMode }
    // [Verify] rule set versions currently offered for Front Door; these are example versions.
    managedRules: premium ? {
      managedRuleSets: [
        { ruleSetType: 'Microsoft_DefaultRuleSet', ruleSetVersion: '2.1', ruleSetAction: 'Block' }
        { ruleSetType: 'Microsoft_BotManagerRuleSet', ruleSetVersion: '1.1' }
      ]
    } : { managedRuleSets: [] }
  }
}

resource security 'Microsoft.Cdn/profiles/securityPolicies@2025-06-01' = {
  parent: profile
  name: 'sp-web'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: waf.id }
      associations: [{ domains: [{ id: endpoint.id }], patternsToMatch: ['/*'] }]
    }
  }
}

output endpointHostName string = endpoint.properties.hostName
output frontDoorId string = profile.properties.frontDoorId
