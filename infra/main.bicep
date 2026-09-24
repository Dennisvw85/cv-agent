// cv-agent: de workload bovenop de landing zone (github.com/Dennisvw85/foundry-landing-zone).
// azd beheert alleen rg-cv-agent. Foundry en de website staan in andere resource groups en
// worden in scripts/postprovision.sh apart bijgewerkt, zodat `azd down` ze nooit kan weggooien.
targetScope = 'subscription'

@minLength(1)
@maxLength(20)
param environmentName string
param location string

@description('Resource group en namen uit de landing zone')
param foundryResourceGroup string
param foundryAccountName string
param foundryProjectName string
param appInsightsName string

param agentName string = 'cv-agent'
param modelDeploymentName string = 'cv-chat'

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-cv-agent-${environmentName}'
  location: location
  tags: tags
}

// Alleen lezen (existing): azd ziet dit niet als eigen resource.
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  scope: resourceGroup(foundryResourceGroup)
  name: appInsightsName
}

var projectEndpoint = 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'

module api 'modules/function.bicep' = {
  scope: rg
  params: {
    name: resourceToken
    location: location
    tags: tags
    appSettings: {
      AZURE_AI_PROJECT_ENDPOINT: projectEndpoint
      AGENT_NAME: agentName
      APPLICATIONINSIGHTS_CONNECTION_STRING: appInsights.properties.ConnectionString
    }
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_FUNCTION_APP_NAME string = api.outputs.name
output AZURE_FUNCTION_APP_ID string = api.outputs.id
output AZURE_FUNCTION_LOCATION string = location
output AZURE_FUNCTION_PRINCIPAL_ID string = api.outputs.principalId
output AZURE_AI_PROJECT_ENDPOINT string = projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = modelDeploymentName
output AGENT_NAME string = agentName
