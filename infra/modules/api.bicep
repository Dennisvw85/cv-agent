// De API als Container App: tekst-chat en de WebRTC-handshake voor spraak.
// Geen keys: de app haalt zijn image op en praat met Foundry via een managed identity.
@minLength(3)
param name string
param location string
param tags object

@description('Leeg bij de eerste uitrol; daarna vult azd het gebouwde image in (SERVICE_API_IMAGE_NAME)')
param image string = ''

@description('Agent voor de v2-API: zuinigere variant, zie README "v2-agent"')
param agentNameV2 string = 'cv-agent-v2'

@description('Image van de v2-API (aparte container voor de v2-omgeving van de site)')
param imageV2 string = ''

@description('Log Analytics-workspace van de landing zone, voor de containerlogs')
param logAnalyticsWorkspaceId string

param env array

@secure()
param appInsightsConnectionString string

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-api-${name}'
  location: location
  tags: tags
}

// Aparte identiteit waarvan de browser (avatar-gesprek) een token krijgt. Los intrekbaar en los te volgen.
resource browserIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-browser-${name}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${name}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, acrPullRoleId)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}'
  location: location
  tags: tags
  properties: {
    // Logs via Azure Monitor naar de bestaande workspace: geen workspace-key nodig.
    appLogsConfiguration: { destination: 'azure-monitor' }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}

resource logs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: environment
  name: 'logs-to-landing-zone'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-api-${name}'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {}, '${browserIdentity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [{ name: 'appinsights-connection-string', value: appInsightsConnectionString }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: empty(image) ? placeholderImage : image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(env, [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'BROWSER_TOKEN_CLIENT_ID', value: browserIdentity.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
          ])
        }
      ]
      // Kostenrem: schaalt naar nul, en nooit meer dan één replica (max. 2 spraakgesprekken tegelijk).
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPull]
}

// v2: een tweede API naast productie, gekoppeld aan de v2-omgeving van de site.
// Zelfde omgeving, registry en identiteit; eigen container, zodat experimenten productie niet raken.
resource apiV2 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-apiv2-${name}'
  location: location
  tags: union(tags, { 'azd-service-name': 'api-v2' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {}, '${browserIdentity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [{ name: 'appinsights-connection-string', value: appInsightsConnectionString }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: empty(imageV2) ? placeholderImage : imageV2
          resources: { cpu: json('0.5'), memory: '1Gi' }
          // Zelfde instellingen als productie, maar met de v2-agent (in code vastgelegd, niet met de hand).
          env: concat(filter(env, e => e.name != 'AGENT_NAME'), [
            { name: 'AGENT_NAME', value: agentNameV2 }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'BROWSER_TOKEN_CLIENT_ID', value: browserIdentity.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
          ])
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPull]
}

output name string = api.name
output id string = api.id
output principalId string = identity.properties.principalId
output browserPrincipalId string = browserIdentity.properties.principalId
output registryEndpoint string = registry.properties.loginServer
output idV2 string = apiV2.id
