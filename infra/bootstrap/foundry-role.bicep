// Module die op scope van rg-dev draait, zodat cicd.bicep (dat zelf in rg-cicd deployt)
// toch een rol kan toewijzen op het Foundry-account in een andere resource group.
param principalId string
param foundryAccountName string
param roleIds array

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryAccountName
}

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in roleIds: {
    name: guid(foundry.id, principalId, roleId)
    scope: foundry
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    }
  }
]
