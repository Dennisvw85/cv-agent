// Wat de cv-agent in het Foundry-account van de landing zone nodig heeft.
// Wordt uitgerold naar de resource group van de landing zone door scripts/postprovision.sh.
param foundryAccountName string

@description('Principal-ID van de managed identity van de API (Container App)')
param apiPrincipalId string

@description('Principal-ID van de identiteit waarvan de browser een token krijgt voor het avatar-gesprek')
param browserPrincipalId string

param modelDeploymentName string = 'cv-chat'
param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'

@description('Duizenden tokens per minuut. Dit is de harde rem op kosten en misbruik.')
param capacity int = 10

var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
// Voice Live vraagt daarnaast Cognitive Services User op het account.
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = {
  name: foundryAccountName
}

resource chatModel 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// Vision (build-time): beelden maken en beschrijven. Na elkaar uitrollen: het account
// accepteert één wijziging tegelijk (RequestConflict).
resource imageModel 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: 'flux-2-pro'
  sku: { name: 'GlobalStandard', capacity: 1 }
  properties: {
    model: { format: 'Black Forest Labs', name: 'FLUX.2-pro', version: '1' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [chatModel]
}

resource visionModel 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: 'phi-4-multimodal'
  sku: { name: 'GlobalStandard', capacity: 1 }
  properties: {
    model: { format: 'Microsoft', name: 'Phi-4-multimodal-instruct', version: '1' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [imageModel]
}

// Eigen deployment voor de vacature-matcher: eigen kostenrem, zodat hij de chat nooit blokkeert.
resource matchModel 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: 'cv-match'
  sku: { name: 'GlobalStandard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [visionModel]
}

resource apiFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apiPrincipalId, foundryUserRoleId)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

resource apiCognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apiPrincipalId, cognitiveServicesUserRoleId)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}

// De browser-identiteit krijgt dezelfde twee rollen als Voice Live vraagt, en niets meer.
resource browserFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, browserPrincipalId, foundryUserRoleId)
  properties: {
    principalId: browserPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

resource browserCognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, browserPrincipalId, cognitiveServicesUserRoleId)
  properties: {
    principalId: browserPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}
