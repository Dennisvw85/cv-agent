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

@description('Door azd ingevuld na de eerste deploy')
param apiImage string = ''

@description('Door azd ingevuld na de eerste deploy van api-v2')
param apiV2Image string = ''

// Alleen lezen (existing): azd ziet dit niet als eigen resource.
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  scope: resourceGroup(foundryResourceGroup)
  name: appInsightsName
}

var projectEndpoint = 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'

module api 'modules/api.bicep' = {
  scope: rg
  params: {
    name: resourceToken
    location: location
    tags: tags
    image: apiImage
    imageV2: apiV2Image
    logAnalyticsWorkspaceId: appInsights.properties.WorkspaceResourceId
    appInsightsConnectionString: appInsights.properties.ConnectionString
    env: [
      { name: 'AZURE_AI_PROJECT_ENDPOINT', value: projectEndpoint }
      { name: 'AGENT_NAME', value: agentName }
      { name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME', value: modelDeploymentName }
    ]
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_API_NAME string = api.outputs.name
output AZURE_API_ID string = api.outputs.id
output AZURE_API_V2_ID string = api.outputs.idV2
output AZURE_API_LOCATION string = location
output AZURE_API_PRINCIPAL_ID string = api.outputs.principalId
output AZURE_BROWSER_PRINCIPAL_ID string = api.outputs.browserPrincipalId
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = api.outputs.registryEndpoint
output AZURE_AI_PROJECT_ENDPOINT string = projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = modelDeploymentName
output AGENT_NAME string = agentName
